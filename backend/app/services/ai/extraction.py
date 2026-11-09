"""AI order capture: message -> reviewable candidate lines. Never creates an order.

Flow:
  1. LLM (if configured) segments the message and proposes SKU/qty/unit per line.
     Without a key, the clearly-labelled rule-based fallback parser is used.
  2. Every proposed line is re-checked deterministically: the original phrase
     must exist in the message, the quantity must agree with the text, the unit
     word is resolved only from explicit words or this retailer's confirmed
     aliases, and the SKU is scored from checkable evidence (see matching.py).
  3. Anything uncertain becomes an explicit clarification for the retailer.
"""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.models import AiExtraction, Product, Retailer, User
from app.services.aliases import active_sku_aliases, active_unit_aliases
from app.services.ai.matching import ProductProfile, band, score_products
from app.services.ai.parsing import (
    HINGLISH_NUMBERS,
    contains_phrase,
    is_filler_only,
    normalize,
    parse_message,
    parse_segment,
    split_segments,
    strip_leading_filler,
    tokenize,
    unit_kind,
)
from app.services.ai.provider import LlmError, build_messages, call_llm
from app.services.catalogue import catalogue_item, load_products, price_for, retailer_prices, stock_status

FALLBACK_PROVIDER = "fallback-rules"


class _Candidate:
    def __init__(
        self,
        original_text: str,
        *,
        llm_sku: str | None = None,
        llm_qty: float | None = None,
        llm_unit_text: str | None = None,
        llm_description: str | None = None,
        llm_reasoning: str | None = None,
        unmatched: bool = False,
    ):
        self.original_text = original_text
        self.llm_sku = llm_sku
        self.llm_qty = llm_qty
        self.llm_unit_text = llm_unit_text
        self.llm_description = llm_description
        self.llm_reasoning = llm_reasoning
        self.unmatched = unmatched


def _profile(p: Product) -> ProductProfile:
    return ProductProfile(
        id=p.id,
        sku_code=p.sku_code,
        name=p.name,
        pack_size_value=p.pack_size_value,
        pack_size_unit=p.pack_size_unit,
        keywords=list(p.match_keywords or []) + [p.name],
    )


def _qty_in_text(qty: float, text: str) -> bool:
    tokens = tokenize(text)
    for t in tokens:
        try:
            if Decimal(t) == Decimal(str(qty)):
                return True
        except Exception:
            if t in HINGLISH_NUMBERS and HINGLISH_NUMBERS[t] == qty:
                return True
    return False


def _resolve_quantity(cand: _Candidate, det_qty: Decimal | None, llm_path: bool) -> tuple[int | None, dict | None]:
    """Returns (quantity, clarification-or-None)."""
    qty: Decimal | None = det_qty
    if llm_path and cand.llm_qty is not None:
        llm_q = Decimal(str(cand.llm_qty))
        if det_qty is not None and llm_q != det_qty:
            return int(det_qty) if det_qty == det_qty.to_integral_value() and det_qty > 0 else None, {
                "type": "quantity",
                "question": f"We read {det_qty.normalize():f} but the AI read {llm_q.normalize():f}. How many cases do you want?",
            }
        if det_qty is None:
            if not _qty_in_text(cand.llm_qty, cand.original_text):
                return None, {"type": "quantity", "question": "How many cases do you want for this line?"}
            qty = llm_q
    if qty is None:
        return None, {"type": "quantity", "question": "No quantity was found. How many cases do you want?"}
    if qty <= 0 or qty != qty.to_integral_value():
        return None, {"type": "quantity", "question": f"'{qty.normalize():f}' is not a whole number of cases. How many cases?"}
    return int(qty), None


def _build_line(
    idx: int,
    cand: _Candidate,
    *,
    products: list[Product],
    profiles: list[ProductProfile],
    overrides: dict[int, Decimal],
    alias_map: dict[str, int],
    unit_aliases: set[str],
    llm_path: bool,
) -> dict:
    parsed = parse_segment(cand.original_text)
    by_sku = {p.sku_code: p for p in products}
    by_id = {p.id: p for p in products}
    clarifications: list[dict] = []

    quantity, q_clar = _resolve_quantity(cand, parsed.quantity, llm_path)
    if q_clar:
        clarifications.append(q_clar)

    # Unit: only explicit "case" words or this retailer's confirmed words count.
    unit_text = parsed.unit_text
    if unit_text is None and cand.llm_unit_text and normalize(cand.llm_unit_text) in tokenize(cand.original_text):
        unit_text = normalize(cand.llm_unit_text)
    kind = unit_kind(unit_text)
    if kind == "case":
        unit, unit_confirmed, unit_source = "case", True, "explicit"
    elif unit_text and normalize(unit_text) in unit_aliases:
        unit, unit_confirmed, unit_source = "case", True, "retailer_alias"
    elif kind == "piece":
        unit, unit_confirmed, unit_source = "piece", False, "explicit"
    else:
        unit, unit_confirmed, unit_source = "unknown", False, "none" if unit_text is None else "ambiguous"

    phrase = parsed.product_phrase or normalize(cand.original_text)
    scored = score_products(
        phrase,
        profiles,
        size_value=parsed.size_value,
        size_unit=parsed.size_unit,
        llm_sku=cand.llm_sku,
        llm_description=cand.llm_description,
        aliases=alias_map,
        llm_available=llm_path,
    )
    top = scored[0] if scored else None
    has_evidence = bool(top) and (top.lexical > 0 or top.alias_match or top.llm_agrees) and not cand.unmatched

    candidate = None
    confidence = 0.0
    confidence_band = "none"
    evidence: list[str] = []
    needs_sku_choice = True
    # Alternatives: products with checkable evidence first. For lines the retailer must verify
    # (medium/low confidence, brief 7.4) we always offer two, topping up with the next-best SKUs;
    # weak ones are labelled "unlikely" in the UI. No-match lines rely on the full product picker.
    plausible = [s for s in scored if s.lexical > 0 or s.alias_match or s.llm_agrees]
    if has_evidence:
        alts = [s for s in plausible if s is not top]
        if top is not None and band(top.score) in ("medium", "low"):
            alts += [s for s in scored if s is not top and s not in alts]
        alternatives_src = alts[:2]
    else:
        alternatives_src = plausible[:2]
    if has_evidence and top is not None:
        product = by_id[top.product.id]
        candidate = catalogue_item(product, price_for(product, overrides))
        confidence = top.score
        confidence_band = band(top.score)
        evidence = top.evidence
        tie = len(scored) > 1 and scored[1].lexical > 0 and scored[1].score >= top.score - 0.05
        needs_sku_choice = confidence_band == "low" or tie
        if needs_sku_choice:
            clarifications.append(
                {"type": "sku", "question": f"Which product did you mean by “{cand.original_text}”?"}
            )
    else:
        clarifications.append(
            {
                "type": "sku",
                "question": f"We could not match “{cand.original_text}” to a catalogue product. Pick one or remove this line.",
            }
        )

    units_per_case = by_id[top.product.id].units_per_case if (candidate and top) else None
    if unit == "piece":
        per = f" ({units_per_case} per case)" if units_per_case else ""
        clarifications.append(
            {
                "type": "unit",
                "question": f"“{unit_text}” looks like pieces, but this product is sold by the case{per}. How many cases do you want?",
                "unit_text": unit_text,
            }
        )
    elif unit == "unknown":
        if unit_text:
            per = f" of {units_per_case} packs" if units_per_case else ""
            q = f"Does “{unit_text}” mean one case{per}?"
        else:
            q = "No unit was given. Is this quantity in cases?"
        clarifications.append({"type": "unit", "question": q, "unit_text": unit_text})

    alternatives = []
    for alt in alternatives_src:
        p = by_id[alt.product.id]
        available = p.inventory.available_cases if p.inventory else 0
        alternatives.append(
            {
                "sku_code": p.sku_code,
                "name": p.name,
                "pack_size": p.pack_size_label,
                "score": alt.score,
                "stock_status": stock_status(available),
                "available_cases": max(available, 0),
            }
        )

    out_of_stock = bool(candidate) and candidate["stock_status"] == "out_of_stock"
    if candidate is None:
        status = "no_match"
    elif out_of_stock:
        status = "out_of_stock"
    elif clarifications:
        status = "needs_attention"
    else:
        status = "ready"

    return {
        "line_id": idx,
        "original_text": cand.original_text,
        "product_phrase": phrase,
        "ai_description": cand.llm_description,
        "ai_reasoning": cand.llm_reasoning,
        "ai_suggested_sku": cand.llm_sku if cand.llm_sku in by_sku else None,
        "quantity": quantity,
        "unit": unit,
        "unit_text": unit_text,
        "unit_confirmed": unit_confirmed,
        "unit_source": unit_source,
        "candidate": candidate,
        "confidence": confidence,
        "confidence_band": confidence_band,
        "evidence": evidence,
        "alternatives": alternatives,
        "needs_sku_choice": needs_sku_choice,
        "clarifications": clarifications,
        "out_of_stock": out_of_stock,
        "status": status,
    }


def _covered(segment: str, lines: list[_Candidate]) -> bool:
    seg_tokens = set(tokenize(segment))
    if not seg_tokens:
        return True
    for c in lines:
        if contains_phrase(segment, c.original_text) or contains_phrase(c.original_text, segment):
            return True
        ct = set(tokenize(c.original_text))
        if ct and len(seg_tokens & ct) / len(seg_tokens) >= 0.5:
            return True
    return False


def _fail(db: Session, user: User, retailer: Retailer, message: str, hint: str | None, exc: LlmError) -> AppError:
    settings = get_settings()
    extraction = AiExtraction(
        retailer_id=retailer.id,
        user_id=user.id,
        original_message=message,
        language_hint=hint,
        provider=settings.ai_provider,
        model=settings.ai_model,
        status="failed",
        error_message=f"{exc.code}: {str(exc)[:400]}",
    )
    db.add(extraction)
    db.commit()
    return AppError(exc.status_code, exc.code, exc.user_message, details={"extraction_id": extraction.id})


def extract_text(db: Session, user: User, retailer: Retailer, message: str, language_hint: str | None) -> dict:
    settings = get_settings()
    message = message.strip()
    if not message:
        raise AppError(422, "empty_message", "Type or paste an order message first.")
    if len(message) > settings.ai_max_message_chars:
        raise AppError(422, "message_too_long", f"Messages can be at most {settings.ai_max_message_chars} characters.")

    products = load_products(db)
    profiles = [_profile(p) for p in products]
    overrides = retailer_prices(db, retailer, [p.id for p in products])
    sku_aliases = active_sku_aliases(db, retailer.id)
    alias_map = {a.alias_text: a.product_id for a in sku_aliases}
    unit_aliases = {a.alias_text for a in active_unit_aliases(db, retailer.id)}
    by_id = {p.id: p for p in products}

    warnings: list[str] = []
    llm_output: dict | None = None
    latency_ms: int | None = None
    message_language: str | None = None
    candidates: list[_Candidate] = []

    if settings.ai_configured:
        llm_path, provider, model = True, settings.ai_provider, settings.ai_model
        catalogue_lines = [
            f"{p.sku_code} | {p.name} | {p.pack_size_label} | case of {p.units_per_case} | also called: "
            + ", ".join(p.match_keywords or [])
            for p in products
        ]
        alias_lines = [f'"{a.alias_text}" -> {by_id[a.product_id].sku_code}' for a in sku_aliases if a.product_id in by_id]
        prompt_message = message if not language_hint else f"{message}\n\n(language hint: {language_hint})"
        try:
            res = call_llm(build_messages(prompt_message, catalogue_lines, alias_lines, sorted(unit_aliases)))
        except LlmError as exc:
            raise _fail(db, user, retailer, message, language_hint, exc)
        latency_ms = res.latency_ms
        llm_output = res.output.model_dump()
        message_language = res.output.message_language
        if res.ignored_fields:
            warnings.append(f"Ignored unsupported fields in the AI response: {', '.join(res.ignored_fields)}.")
        valid_skus = {p.sku_code for p in products}
        for line in res.output.lines:
            text = line.original_text.strip()
            if not contains_phrase(message, text):
                warnings.append(
                    f"The AI paraphrased “{text[:60]}” instead of quoting the message; that line was re-read from your text."
                )
                continue  # uncovered text is picked up by the coverage check below
            sku = line.candidate_sku if line.candidate_sku in valid_skus else None
            if line.candidate_sku and sku is None:
                warnings.append(f"The AI suggested an unknown SKU ({line.candidate_sku[:40]}); it was ignored.")
            candidates.append(
                _Candidate(
                    strip_leading_filler(text),
                    llm_sku=sku,
                    llm_qty=line.quantity,
                    llm_unit_text=line.unit_text,
                    llm_description=line.product_description,
                    llm_reasoning=line.reasoning_summary,
                )
            )
        for phrase in res.output.unmatched_phrases:
            if phrase.strip() and contains_phrase(message, phrase) and not is_filler_only(phrase):
                candidates.append(_Candidate(strip_leading_filler(phrase.strip()), unmatched=True))
    else:
        llm_path, provider, model = False, FALLBACK_PROVIDER, None
        warnings.append(
            "No AI provider key is configured, so the rule-based fallback parser was used. "
            "Results are less flexible than the LLM path."
        )
        candidates = [_Candidate(p.original_text) for p in parse_message(message)]

    # Coverage: anything in the message that no line accounts for is surfaced, never dropped.
    for seg in split_segments(message):
        if not is_filler_only(seg) and not _covered(seg, candidates):
            candidates.append(_Candidate(strip_leading_filler(seg)))
            if llm_path:
                warnings.append(f"Part of the message was not extracted by the AI: “{seg[:60]}”.")

    lines = [
        _build_line(
            i,
            c,
            products=products,
            profiles=profiles,
            overrides=overrides,
            alias_map=alias_map,
            unit_aliases=unit_aliases,
            llm_path=llm_path,
        )
        for i, c in enumerate(candidates)
    ]
    if not lines:
        warnings.append("No order lines were found in this message.")

    extraction = AiExtraction(
        retailer_id=retailer.id,
        user_id=user.id,
        original_message=message,
        language_hint=language_hint,
        provider=provider,
        model=model,
        status="extracted",
        llm_output=llm_output,
        latency_ms=latency_ms,
    )
    db.add(extraction)
    db.flush()
    result = {
        "extraction_id": extraction.id,
        "provider": provider,
        "model": model,
        "is_fallback": not llm_path,
        "message_language": message_language,
        "original_message": message,
        "lines": lines,
        "warnings": warnings,
    }
    extraction.result = _jsonable(result)
    db.commit()
    return extraction.result


def _jsonable(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


def get_extraction(db: Session, retailer: Retailer, extraction_id: int) -> dict:
    extraction = db.get(AiExtraction, extraction_id)
    if extraction is None or extraction.retailer_id != retailer.id or extraction.result is None:
        raise AppError(404, "not_found", "AI extraction not found.")
    return {**extraction.result, "status": extraction.status, "order_id": extraction.order_id}
