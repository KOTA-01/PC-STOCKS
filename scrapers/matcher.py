"""
Product matching — scores how well a ProductListing matches a wanted part.

Matching priority:
  1. Exact model number match
  2. Brand match
  3. Category/type match
  4. Normalised token overlap (Jaccard-style)

Returns a float score 0.0–1.0.  Higher = better match.
"""

from __future__ import annotations

import re
import logging

log = logging.getLogger("scrapers.matcher")

# ─── Token normalisation ────────────────────────────────────────────────────

# Words that add noise and should be dropped for matching
_STOP_WORDS = frozenset({
    "the", "a", "an", "and", "or", "for", "with", "in", "of",
    "gen", "new", "latest", "edition", "version",
    "-", "/", "|", ",", ".", "(", ")", "[", "]",
})

# Common brand aliases
_BRAND_ALIASES: dict[str, str] = {
    "wd": "western digital",
    "amd": "amd",
    "nvidia": "nvidia",
    "evga": "evga",
    "msi": "msi",
    "asus": "asus",
    "asrock": "asrock",
    "gigabyte": "gigabyte",
    "corsair": "corsair",
    "gskill": "g.skill",
    "g.skill": "g.skill",
    "crucial": "crucial",
    "kingston": "kingston",
    "samsung": "samsung",
    "seagate": "seagate",
    "noctua": "noctua",
    "be quiet": "be quiet!",
    "cooler master": "cooler master",
    "nzxt": "nzxt",
    "lian li": "lian li",
    "fractal": "fractal design",
    "fractal design": "fractal design",
    "arctic": "arctic",
    "phanteks": "phanteks",
    "thermaltake": "thermaltake",
    "deepcool": "deepcool",
    "seasonic": "seasonic",
    "super flower": "super flower",
    "intel": "intel",
}


def _normalise(text: str) -> str:
    """Lowercase, strip special chars, collapse spaces."""
    text = text.lower()
    text = re.sub(r"[^\w\s.-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokenise(text: str) -> set[str]:
    """Split normalised text into a set of meaningful tokens."""
    tokens = set()
    for tok in _normalise(text).split():
        if tok not in _STOP_WORDS and len(tok) > 1:
            tokens.add(tok)
    return tokens


# ─── Model number extraction ────────────────────────────────────────────────

# Regex patterns for common PC part model numbers
_MODEL_PATTERNS = [
    # CPU: Ryzen 9 9950X, i9-14900K, etc.
    re.compile(r"\b(ryzen\s*[3579]\s*\d{4}x?\d?)\b", re.I),
    re.compile(r"\b(i[3579][-\s]*\d{4,5}[a-z]*)\b", re.I),
    # GPU: RTX 4060, RX 7900 XTX, etc.
    re.compile(r"\b((?:rtx|gtx|rx)\s*\d{3,4}\s*(?:ti|xt|xtx|super)?)\b", re.I),
    # Motherboard chipsets: X870, B650, Z790, etc.
    re.compile(r"\b([xbz]\d{3}[a-z]?)\b", re.I),
    # SSD model numbers: 990 Pro, 980 Pro, T700, etc.
    re.compile(r"\b(\d{3}\s*(?:pro|evo|plus))\b", re.I),
    # RAM: DDR5-6000, DDR4-3600, etc.
    re.compile(r"\b(ddr[45][-\s]*\d{4})\b", re.I),
    # PSU wattage: 850W, 1000W, etc.
    re.compile(r"\b(\d{3,4}\s*w)\b", re.I),
    # Generic alphanumeric model codes (e.g., MZ-V9P2T0BW)
    re.compile(r"\b([A-Z]{2,3}[-]?[A-Z0-9]{4,})\b"),
]


def _extract_models(text: str) -> set[str]:
    """Pull out likely model identifiers from text."""
    models = set()
    for pat in _MODEL_PATTERNS:
        for m in pat.finditer(text):
            models.add(re.sub(r"\s+", "", m.group(1).lower()))
    return models


def _extract_brand(text: str) -> str | None:
    """Try to identify the brand from text."""
    lower = text.lower()
    for alias, canonical in _BRAND_ALIASES.items():
        if re.search(r"\b" + re.escape(alias) + r"\b", lower):
            return canonical
    return None


def _extract_capacity(text: str) -> str | None:
    """Extract storage/RAM capacity like '2TB', '96GB', '32GB'."""
    m = re.search(r"\b(\d+)\s*(tb|gb|mb)\b", text, re.I)
    if m:
        return f"{m.group(1)}{m.group(2).upper()}"
    return None


# ─── Scoring ────────────────────────────────────────────────────────────────

def score(
    listing_title: str,
    wanted_name: str,
    wanted_type: str = "",
    wanted_spec: str = "",
) -> float:
    """
    Score how well *listing_title* matches the wanted part.

    Returns 0.0 .. 1.0.  Generally:
      >= 0.65  — strong match (likely the right product)
      0.40–0.65 — partial match (same brand/category, maybe wrong SKU)
      < 0.40  — weak / wrong product
    """
    if not listing_title or not wanted_name:
        return 0.0

    total = 0.0
    weights_used = 0.0

    # Combine wanted_name + spec for richer matching
    wanted_full = f"{wanted_name} {wanted_spec}"

    # ── 1. Model number match (weight 0.40) ─────────────────────────
    listing_models = _extract_models(listing_title)
    wanted_models = _extract_models(wanted_full)

    if listing_models and wanted_models:
        overlap = listing_models & wanted_models
        if overlap:
            model_score = len(overlap) / max(len(wanted_models), 1)
            total += 0.40 * min(model_score, 1.0)
        # Penalise if listing has a model number that conflicts
        elif listing_models - wanted_models:
            total -= 0.10
    weights_used += 0.40

    # ── 2. Brand match (weight 0.15) ────────────────────────────────
    listing_brand = _extract_brand(listing_title)
    wanted_brand = _extract_brand(wanted_full)

    if wanted_brand and listing_brand:
        if listing_brand == wanted_brand:
            total += 0.15
        else:
            total -= 0.05  # Wrong brand penalty
    weights_used += 0.15

    # ── 3. Capacity match (weight 0.15) ─────────────────────────────
    listing_cap = _extract_capacity(listing_title)
    wanted_cap = _extract_capacity(wanted_full)

    if wanted_cap and listing_cap:
        if listing_cap == wanted_cap:
            total += 0.15
        else:
            total -= 0.10  # Wrong capacity is a strong mismatch
    weights_used += 0.15

    # ── 4. Token overlap — Jaccard similarity (weight 0.30) ─────────
    listing_tokens = _tokenise(listing_title)
    wanted_tokens = _tokenise(wanted_full)

    if listing_tokens and wanted_tokens:
        intersection = listing_tokens & wanted_tokens
        union = listing_tokens | wanted_tokens
        jaccard = len(intersection) / len(union) if union else 0
        total += 0.30 * jaccard
    weights_used += 0.30

    return max(0.0, min(1.0, total))


# ─── Convenience ────────────────────────────────────────────────────────────

MATCH_THRESHOLD = 0.40   # Minimum score to consider a listing relevant
STRONG_THRESHOLD = 0.55  # Score above which we're confident it's the right product


def best_match(
    listings: list,  # list[ProductListing]
    wanted_name: str,
    wanted_type: str = "",
    wanted_spec: str = "",
    threshold: float = MATCH_THRESHOLD,
):
    """
    Pick the **cheapest** well-matched listing from *listings*.
    Returns (listing, score) or (None, 0.0) if nothing exceeds the threshold.

    Strategy — price-comparison first:
      1. Score every listing; keep those above *threshold*
      2. If any strong matches (>= 0.55) exist, restrict to those
         (avoids picking a borderline match just because it's $1 cheaper)
      3. Among the surviving pool, sort by:
            a. In-stock preferred
            b. Lowest price
            c. Highest match score (tie-breaker only)
    """
    scored = []
    for listing in listings:
        s = score(listing.title, wanted_name, wanted_type, wanted_spec)
        if s >= threshold:
            scored.append((listing, s))

    if not scored:
        return None, 0.0

    # Log all candidates for debugging
    scored_by_price = sorted(scored, key=lambda x: x[0].price)
    for listing, s in scored_by_price[:10]:
        log.info(
            "  candidate: score=%.2f  $%7.2f  %-25s  %s",
            s, listing.price, listing.store, listing.title[:55],
        )

    # Prefer strong matches so we don't pick borderline wrong products
    strong = [(l, s) for l, s in scored if s >= STRONG_THRESHOLD]
    pool = strong if strong else scored

    # Sort: in-stock first → cheapest price → highest score tie-breaker
    pool.sort(key=lambda x: (not x[0].in_stock, x[0].price, -x[1]))

    best_listing, best_score = pool[0]
    log.info(
        "✓ PICK for '%s': score=%.2f  $%.2f @ %s  [%s]",
        wanted_name, best_score, best_listing.price,
        best_listing.store, best_listing.title[:60],
    )
    return best_listing, best_score
