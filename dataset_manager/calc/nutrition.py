"""Deterministic nutrition arithmetic. Pure functions, no I/O, full precision.

Formatting/rounding happens only at presentation (templates / client JS).
"""

MACROS = ("energy_kcal", "protein_g", "fat_g", "carbohydrate_g")

# Exact mass conversion factors to grams.
UNIT_TO_GRAMS = {
    "g": 1.0,
    "kg": 1000.0,
    "mg": 0.001,
    "oz": 28.349523125,
    "lb": 453.59237,
}


def to_grams(amount, unit):
    """Convert a mass amount to grams. Raises ValueError for unknown units —
    non-mass units (cup, piece, serving) must be resolved to grams upstream
    via food-specific portion data, never guessed here."""
    if amount is None or amount < 0:
        raise ValueError(f"invalid amount: {amount!r}")
    try:
        return amount * UNIT_TO_GRAMS[unit]
    except KeyError:
        raise ValueError(f"unknown mass unit: {unit!r}") from None


def scale(per_100g, grams):
    """Scale a per-100g nutrient dict to the given gram weight.
    None values pass through as None (missing, not zero)."""
    factor = grams / 100.0
    return {k: (v * factor if v is not None else None) for k, v in per_100g.items()}


def sum_components(parts):
    """Sum a list of nutrient dicts. A None value marks the field missing for
    that part: it is skipped from the total and the field is reported in
    `missing` so callers can label incomplete totals instead of silently
    under-counting.

    Returns (totals: dict, missing: dict[field -> count of parts missing it]).
    """
    totals = {}
    missing = {}
    for part in parts:
        for k, v in part.items():
            if v is None:
                missing[k] = missing.get(k, 0) + 1
            else:
                totals[k] = totals.get(k, 0.0) + v
    return totals, missing


def meal_insights(totals, salt_g=None, fiber_g=None, dv=None):
    """Deterministic meal notes from computed totals. Returns a list of
    (level, key, params) for i18n rendering — thresholds are visible in the
    rendered text, never health advice beyond the arithmetic.

    dv: {'energy_kcal': ..., 'salt_g': ...} daily reference values.
    """
    out = []
    dv = dv or {}
    kcal = totals.get("energy_kcal") or 0
    p = (totals.get("protein_g") or 0) * 4
    f = (totals.get("fat_g") or 0) * 9
    c = (totals.get("carbohydrate_g") or 0) * 4
    energy = p + f + c
    if salt_g is not None and dv.get("salt_g") and salt_g > dv["salt_g"] / 3:
        out.append(("warn", "ins_salt_high", {"v": round(salt_g, 1), "dv": dv["salt_g"]}))
    if dv.get("energy_kcal") and kcal > dv["energy_kcal"] * 0.4:
        out.append(("warn", "ins_kcal_high", {"v": round(kcal), "dv": dv["energy_kcal"]}))
    if energy > 0 and p / energy >= 0.25:
        out.append(("good", "ins_protein_good", {"v": round(p / energy * 100)}))
    if energy > 0 and f / energy >= 0.40:
        out.append(("warn", "ins_fat_high", {"v": round(f / energy * 100)}))
    if fiber_g is not None and fiber_g >= 6:
        out.append(("good", "ins_fiber_good", {"v": round(fiber_g, 1)}))
    return out


def dish_nutrition(links, nutrition_by_item):
    """Compute a dish total from resolved recipe ingredient links.

    links: iterable of dicts with keys grams, mext_item_id (either may be None).
    nutrition_by_item: {item_id: per-100g dict}.

    Returns dict with totals, missing, n_total, n_resolved (has grams AND a
    matched item with nutrition), grams_resolved.
    """
    links = list(links)
    parts = []
    grams_resolved = 0.0
    for ln in links:
        g, mid = ln.get("grams"), ln.get("mext_item_id")
        if g is None or mid is None or mid not in nutrition_by_item:
            continue
        parts.append(scale(nutrition_by_item[mid], g))
        grams_resolved += g
    totals, missing = sum_components(parts)
    return {
        "totals": totals,
        "missing": missing,
        "n_total": len(links),
        "n_resolved": len(parts),
        "grams_resolved": grams_resolved,
    }
