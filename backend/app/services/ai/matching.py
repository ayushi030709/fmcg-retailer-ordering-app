"""Deterministic SKU matching and heuristic confidence scoring.

The LLM's self-reported confidence is NOT used. The score shown to users is a
heuristic built from evidence we can check:

  score = 0.50 x lexical      (retailer alias / catalogue keyword / fuzzy token match)
        + 0.20 x pack size    (1 = size agrees, 0.5 = no size given, 0 = conflicts)
        + 0.15 x LLM agrees   (the model proposed the same SKU)
        + 0.15 x uniqueness   (margin over the next-best product's lexical score)

When no LLM is configured the LLM term is dropped and the rest re-normalised.
A confirmed retailer alias floors the score at 0.95; a conflicting pack size
caps it at 0.55. Bands: high >= 0.85, medium 0.60-0.84, low < 0.60. These are
implementation heuristics calibrated on the sample messages in the tests, not
client-specified thresholds.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from difflib import SequenceMatcher

from app.services.ai.parsing import normalize, tokenize

W_LEX, W_SIZE, W_LLM, W_UNIQ = 0.50, 0.20, 0.15, 0.15
HIGH, MEDIUM = 0.85, 0.60
ALIAS_FLOOR = 0.95
SIZE_CONFLICT_CAP = 0.55
FUZZY_TOKEN_MIN = 0.85


@dataclass
class ProductProfile:
    id: int
    sku_code: str
    name: str
    pack_size_value: Decimal
    pack_size_unit: str
    keywords: list[str]


@dataclass
class ScoredProduct:
    product: ProductProfile
    score: float
    lexical: float
    size_match: bool | None
    llm_agrees: bool
    alias_match: bool
    evidence: list[str] = field(default_factory=list)


def band(score: float) -> str:
    if score >= HIGH:
        return "high"
    if score >= MEDIUM:
        return "medium"
    return "low"


def _to_grams(value: Decimal, unit: str) -> Decimal | None:
    factors = {"g": Decimal(1), "kg": Decimal(1000), "ml": Decimal(1), "l": Decimal(1000)}
    return value * factors[unit] if unit in factors else None


def size_matches(product: ProductProfile, size_value: Decimal | None, size_unit: str | None) -> bool | None:
    """True/False when the phrase mentions a size, None when it does not."""
    if size_value is None:
        return None
    if size_unit is None:  # bare "250 wala"
        return size_value == product.pack_size_value or size_value == _to_grams(
            product.pack_size_value, product.pack_size_unit
        )
    a = _to_grams(size_value, size_unit)
    b = _to_grams(product.pack_size_value, product.pack_size_unit)
    return a is not None and a == b


def _token_present(token: str, phrase_tokens: list[str]) -> bool:
    if token in phrase_tokens:
        return True
    if len(token) < 4:
        return False
    return any(SequenceMatcher(None, token, t).ratio() >= FUZZY_TOKEN_MIN for t in phrase_tokens if len(t) >= 3)


def lexical_score(phrase: str, product: ProductProfile) -> tuple[float, str | None]:
    tokens = tokenize(phrase)
    if not tokens:
        return 0.0, None
    best, why = 0.0, None
    for kw in product.keywords:
        kw_tokens = tokenize(kw)
        if kw_tokens and all(_token_present(t, tokens) for t in kw_tokens):
            s = 1.0 if len(kw_tokens) >= 2 else 0.85
            if s > best:
                best, why = s, f"matches catalogue keyword '{kw}'"
    if best == 0.0:
        # Weak partial evidence: the best fuzzy similarity of any keyword token.
        for kw in product.keywords:
            for kt in tokenize(kw):
                if len(kt) < 4:
                    continue
                for t in tokens:
                    r = SequenceMatcher(None, kt, t).ratio()
                    if r >= 0.7 and 0.6 * r > best:
                        best, why = 0.6 * r, f"partly resembles '{kt}'"
    return best, why


def score_products(
    phrase: str,
    products: list[ProductProfile],
    *,
    size_value: Decimal | None,
    size_unit: str | None,
    llm_sku: str | None,
    llm_description: str | None,
    aliases: dict[str, int],
    llm_available: bool,
) -> list[ScoredProduct]:
    norm_phrase = normalize(phrase)
    lexicals: dict[int, tuple[float, str | None]] = {}
    for p in products:
        lex, why = lexical_score(phrase, p)
        if llm_description:
            # The LLM's English description can bridge Hindi words we have no keyword for,
            # but it is discounted relative to the retailer's own words.
            d_lex, d_why = lexical_score(llm_description, p)
            if 0.9 * d_lex > lex:
                lex, why = 0.9 * d_lex, f"AI description {d_why}" if d_why else None
        lexicals[p.id] = (lex, why)

    alias_hits = {pid for alias, pid in aliases.items() if alias and (alias == norm_phrase or f" {alias} " in f" {norm_phrase} ")}

    results: list[ScoredProduct] = []
    for p in products:
        lex, why = lexicals[p.id]
        others = [lexicals[o.id][0] for o in products if o.id != p.id]
        best_other = max(others) if others else 0.0
        uniq = max(0.0, min(1.0, (lex - best_other) / 0.5)) if lex > 0 else 0.0
        sm = size_matches(p, size_value, size_unit)
        size_component = 0.5 if sm is None else (1.0 if sm else 0.0)
        llm_agrees = bool(llm_sku) and llm_sku == p.sku_code
        evidence: list[str] = []
        if why:
            evidence.append(why)
        if sm is True:
            evidence.append(f"pack size agrees ({p.pack_size_value.normalize():f} {p.pack_size_unit})")
        elif sm is False:
            evidence.append("pack size in message differs from this SKU")

        if llm_available:
            score = W_LEX * lex + W_SIZE * size_component + W_LLM * (1.0 if llm_agrees else 0.0) + W_UNIQ * uniq
            if llm_agrees:
                evidence.append("AI proposed this SKU")
        else:
            score = (W_LEX * lex + W_SIZE * size_component + W_UNIQ * uniq) / (W_LEX + W_SIZE + W_UNIQ)

        if lex == 0.0 and not llm_agrees:
            score = min(score, 0.15)  # size/uniqueness alone is not evidence of a product
        alias_match = p.id in alias_hits
        if alias_match:
            score = max(score, ALIAS_FLOOR)
            evidence.insert(0, "matches this retailer's confirmed phrase")
        if sm is False:
            score = min(score, SIZE_CONFLICT_CAP)
        results.append(
            ScoredProduct(
                product=p,
                score=round(score, 2),
                lexical=lex,
                size_match=sm,
                llm_agrees=llm_agrees,
                alias_match=alias_match,
                evidence=evidence,
            )
        )
    results.sort(key=lambda r: (-r.score, r.product.sku_code))
    return results
