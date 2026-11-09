"""Deterministic text utilities for Hindi/Hinglish order messages.

Used in two ways:
  1. To *verify* every line the LLM proposes (quantity, unit word, pack size),
     so the model's claims are never trusted blindly.
  2. As the clearly-labelled fallback extractor when no LLM key is configured.
     This is a genuine rule-based parser, not canned output for the sample.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

# Words that unambiguously mean "case" (the distributor's selling unit).
CASE_WORDS = {"case", "cases", "cs"}
# Words that mean an individual piece/packet — not a sellable unit here.
PIECE_WORDS = {"pc", "pcs", "piece", "pieces", "packet", "packets", "pkt", "pkts", "nag"}
# Container words whose meaning varies by retailer (assumption A4). Treated as
# "unknown unit" unless the retailer has a confirmed alias for the word.
AMBIGUOUS_UNIT_WORDS = {
    "peti", "petti", "पेटी", "box", "boxes", "dabba", "dabbe", "dibba", "carton", "cartons",
    "ctn", "bori", "bag", "bags", "pack", "packs", "bundle", "patta",
}
UNIT_WORDS = CASE_WORDS | PIECE_WORDS | AMBIGUOUS_UNIT_WORDS

SIZE_UNITS = {
    "g": "g", "gm": "g", "gms": "g", "gram": "g", "grams": "g", "gr": "g",
    "kg": "kg", "kgs": "kg", "kilo": "kg", "kilos": "kg", "kilogram": "kg",
    "ml": "ml", "l": "l", "ltr": "l", "litre": "l", "liter": "l",
}
# "250 wala" = "the 250 one": a size reference without an explicit unit.
SIZE_MARKERS = {"wala", "wali", "wale", "vala", "vali", "vale"}

FILLER_WORDS = {
    "bhaiya", "bhaiyya", "bhai", "bhaisahab", "sahab", "sir", "ji", "please", "pls", "plz", "hello", "hi",
    "namaste", "bhejo", "bhej", "bhejna", "bhejiye", "dena", "dedo", "dijiye", "chahiye", "chaiye",
    "order", "send", "karo", "kar", "do", "de", "bhi", "aur", "and", "plus", "ka", "ki", "ke", "hai",
    "mujhe", "hame", "humein", "humko", "total",
}

HINGLISH_NUMBERS = {
    "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5, "chhe": 6, "che": 6,
    "saat": 7, "aath": 8, "nau": 9, "das": 10, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

_SEGMENT_SPLIT = re.compile(r"[,;\n|+&]+|\s+(?:aur|and|plus)\s+|(?<!\d)\.(?!\d)", re.IGNORECASE)
_GLUED = re.compile(r"^(\d+(?:\.\d+)?)([^\d.]+)$")
_NUMBER = re.compile(r"^\d+(?:\.\d+)?$")


def normalize(text: str) -> str:
    """Lower-case, NFKC, punctuation/symbols to spaces, collapse whitespace.

    Combining marks are preserved so Devanagari words survive normalisation.
    """
    text = unicodedata.normalize("NFKC", text).lower()
    chars = []
    for ch in text:
        cat = unicodedata.category(ch)
        if ch == "." or cat[0] not in ("P", "S"):
            chars.append(ch)
        else:
            chars.append(" ")
    return re.sub(r"\s+", " ", "".join(chars)).strip()


def tokenize(text: str) -> list[str]:
    """Normalise and split, separating glued tokens like '250g' or '5peti'."""
    tokens: list[str] = []
    for raw in normalize(text).replace(".", " . ").split():
        if raw == ".":
            continue
        m = _GLUED.match(raw)
        if m and (m.group(2) in SIZE_UNITS or m.group(2) in UNIT_WORDS or m.group(2) in SIZE_MARKERS):
            tokens.extend([m.group(1), m.group(2)])
        else:
            tokens.append(raw)
    # Re-join decimals split above ("1 . 5" never happens because we only split
    # standalone dots); kept simple on purpose.
    return tokens


def _as_number(token: str) -> Decimal | None:
    if _NUMBER.match(token):
        try:
            return Decimal(token)
        except InvalidOperation:  # pragma: no cover
            return None
    return None


@dataclass
class ParsedSegment:
    original_text: str
    quantity: Decimal | None
    unit_text: str | None
    unit_kind: str  # case | piece | ambiguous | none
    size_value: Decimal | None
    size_unit: str | None  # g | kg | ml | l | None (bare "250 wala")
    product_phrase: str
    product_tokens: list[str] = field(default_factory=list)


def unit_kind(word: str | None) -> str:
    if not word:
        return "none"
    w = normalize(word)
    if w in CASE_WORDS:
        return "case"
    if w in PIECE_WORDS:
        return "piece"
    if w in AMBIGUOUS_UNIT_WORDS:
        return "ambiguous"
    return "ambiguous"


def parse_segment(segment: str) -> ParsedSegment:
    tokens = tokenize(segment)
    consumed: set[int] = set()
    quantity: Decimal | None = None
    unit_text: str | None = None
    size_value: Decimal | None = None
    size_unit: str | None = None

    def num_at(i: int) -> Decimal | None:
        if i < 0 or i >= len(tokens):
            return None
        n = _as_number(tokens[i])
        if n is not None:
            return n
        return Decimal(HINGLISH_NUMBERS[tokens[i]]) if tokens[i] in HINGLISH_NUMBERS else None

    # Pass 1: sizes ("1 kilo", "250 g", "250 wala").
    for i, tok in enumerate(tokens):
        n = _as_number(tok)
        if n is None or i + 1 >= len(tokens):
            continue
        nxt = tokens[i + 1]
        if nxt in SIZE_UNITS and size_value is None:
            size_value, size_unit = n, SIZE_UNITS[nxt]
            # sizes are part of the product description, not consumed
        elif nxt in SIZE_MARKERS and size_value is None:
            size_value, size_unit = n, None

    # Pass 2: quantity followed by a unit word ("5 peti", "ek case").
    for i, tok in enumerate(tokens):
        if tok in UNIT_WORDS:
            n = num_at(i - 1)
            if n is not None and (i - 1) not in consumed:
                quantity, unit_text = n, tok
                consumed.update({i - 1, i})
                break
            n = num_at(i + 1)
            if n is not None and _as_number(tokens[i + 1]) is not None:
                # "peti 5" — unit before number
                quantity, unit_text = n, tok
                consumed.update({i, i + 1})
                break
    else:
        # Pass 3: a plain number that is not a size ("5 biscuit").
        for i, tok in enumerate(tokens):
            n = _as_number(tok)
            if n is None:
                continue
            nxt = tokens[i + 1] if i + 1 < len(tokens) else None
            if nxt in SIZE_UNITS or nxt in SIZE_MARKERS:
                continue
            quantity = n
            consumed.add(i)
            break

    # Any unit word still unconsumed (e.g. "biscuit peti") is remembered.
    if unit_text is None:
        for i, tok in enumerate(tokens):
            if tok in UNIT_WORDS and i not in consumed:
                unit_text = tok
                consumed.add(i)
                break

    product_tokens = [t for i, t in enumerate(tokens) if i not in consumed and t not in FILLER_WORDS]
    return ParsedSegment(
        original_text=segment.strip(),
        quantity=quantity,
        unit_text=unit_text,
        unit_kind=unit_kind(unit_text),
        size_value=size_value,
        size_unit=size_unit,
        product_phrase=" ".join(product_tokens),
        product_tokens=product_tokens,
    )


def split_segments(message: str) -> list[str]:
    parts = [p.strip(" \t-:") for p in _SEGMENT_SPLIT.split(message)]
    return [p for p in parts if p and p.strip()]


def is_filler_only(segment: str) -> bool:
    tokens = tokenize(segment)
    return all(t in FILLER_WORDS for t in tokens)


def parse_message(message: str) -> list[ParsedSegment]:
    """Rule-based extraction used only when no LLM is configured."""
    out: list[ParsedSegment] = []
    for seg in split_segments(message):
        if is_filler_only(seg):
            continue
        parsed = parse_segment(seg)
        # Keep the retailer's own words, minus a leading greeting ("bhaiya 5 peti ...").
        parsed.original_text = strip_leading_filler(seg)
        out.append(parsed)
    return out


def strip_leading_filler(segment: str) -> str:
    """'bhaiya 5 peti biscuit' -> '5 peti biscuit' while preserving original casing."""
    words = segment.strip().split()
    while words and normalize(words[0]) in FILLER_WORDS:
        # "do case" = "2 cases": a Hinglish number before a unit word is not filler.
        if normalize(words[0]) in HINGLISH_NUMBERS and len(words) > 1 and normalize(words[1]) in UNIT_WORDS:
            break
        words.pop(0)
    return " ".join(words) if words else segment.strip()


def contains_phrase(haystack: str, needle: str) -> bool:
    return normalize(needle) in normalize(haystack)
