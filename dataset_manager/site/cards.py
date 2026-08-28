"""Generated imagery, derived from each food's own measurements.

We have no photograph library and will not hotlink or invent one, so the
pictures on this site are made from the data itself. Every food carries a
nutrient fingerprint: a ring of spokes, one per nutrient, each drawn to the
share of a daily reference value that 100 g supplies. Two foods with different
compositions cannot produce the same mark, which makes it a portrait rather
than a decoration.

Pure string building — no dependencies, no request-time rasterising.
"""
import math

from .groups import color as group_color

# Spokes, clockwise from the top. Codes are MEXT nutrient identifiers; the
# reference values are the Japanese labelling standard (栄養素等表示基準値 2020).
FINGERPRINT = [
    ("PROT-", "protein", 81.0),
    ("FAT-", "fat", 62.0),
    ("CHOCDF-", "carbohydrate", 320.0),
    ("FIB-", "fibre", 19.0),
    ("CA", "calcium", 680.0),
    ("FE", "iron", 6.8),
    ("K", "potassium", 2800.0),
    ("MG", "magnesium", 320.0),
    ("ZN", "zinc", 8.8),
    ("VITC", "vitamin C", 100.0),
    ("VITA_RAE", "vitamin A", 770.0),
    ("THIA", "vitamin B1", 1.2),
]


def _pt(cx, cy, r, ang):
    return cx + r * math.cos(ang), cy + r * math.sin(ang)


def fingerprint_svg(nutrients, category, size=168, label=None):
    """nutrients: [{code, amount}] per 100 g. Returns an inline SVG string.

    Spoke length is the share of the daily reference value, damped with a
    square root so that a food supplying 400% of one nutrient does not flatten
    every other spoke into invisibility. Missing nutrients draw nothing, which
    is itself readable — a food with only macros shows three spokes.
    """
    by_code = {n["code"]: n["amount"] for n in (nutrients or []) if n.get("amount") is not None}
    if not by_code:
        return ""
    accent = group_color(category)
    cx = cy = size / 2
    r_in, r_out = size * 0.17, size * 0.44
    n = len(FINGERPRINT)
    spokes, dots = [], []
    for i, (code, _name, dv) in enumerate(FINGERPRINT):
        ang = -math.pi / 2 + (2 * math.pi * i / n)
        amount = by_code.get(code)
        if amount is None or dv <= 0:
            continue
        share = min(math.sqrt(max(amount, 0) / dv), 1.6) / 1.6
        r = r_in + (r_out - r_in) * share
        x1, y1 = _pt(cx, cy, r_in, ang)
        x2, y2 = _pt(cx, cy, r, ang)
        spokes.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{accent}" stroke-width="{size * 0.035:.1f}" stroke-linecap="round" '
            f'opacity="{0.45 + 0.55 * share:.2f}"/>')
        dots.append(f'<circle cx="{x2:.1f}" cy="{y2:.1f}" r="{size * 0.017:.1f}" fill="{accent}"/>')

    guide = (f'<circle cx="{cx}" cy="{cy}" r="{r_out:.1f}" fill="none" '
             f'stroke="currentColor" stroke-width="1" opacity="0.13"/>'
             f'<circle cx="{cx}" cy="{cy}" r="{r_in:.1f}" fill="none" '
             f'stroke="currentColor" stroke-width="1" opacity="0.2"/>')
    centre = (f'<circle cx="{cx}" cy="{cy}" r="{size * 0.055:.1f}" fill="{accent}"/>')
    aria = f' role="img" aria-label="{label}"' if label else ' aria-hidden="true"'
    return (f'<svg class="fingerprint" viewBox="0 0 {size} {size}" width="{size}" '
            f'height="{size}" xmlns="http://www.w3.org/2000/svg"{aria}>'
            f'{guide}{"".join(spokes)}{"".join(dots)}{centre}</svg>')


def pfc_donut_svg(pfc, size=132, kcal=None):
    """A ring split by the protein / fat / carbohydrate energy shares."""
    if not pfc:
        return ""
    cx = cy = size / 2
    r = size * 0.38
    stroke = size * 0.13
    circ = 2 * math.pi * r
    parts = [("p", pfc["p"], "#3D6B8E"), ("f", pfc["f"], "#C9972E"), ("c", pfc["c"], "#7A8B3D")]
    segs, offset = [], 0.0
    for _k, pct, colour in parts:
        if pct <= 0:
            continue
        length = circ * pct / 100
        segs.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r:.1f}" fill="none" stroke="{colour}" '
            f'stroke-width="{stroke:.1f}" stroke-dasharray="{length:.2f} {circ - length:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}" transform="rotate(-90 {cx} {cy})"/>')
        offset += length
    middle = ""
    if kcal is not None:
        middle = (f'<text x="{cx}" y="{cy - 1}" text-anchor="middle" dominant-baseline="middle" '
                  f'font-size="{size * 0.22:.0f}" font-weight="600" fill="currentColor" '
                  f'font-family="monospace">{round(kcal)}</text>'
                  f'<text x="{cx}" y="{cy + size * 0.17:.0f}" text-anchor="middle" '
                  f'font-size="{size * 0.10:.0f}" fill="currentColor" opacity="0.55">kcal</text>')
    return (f'<svg class="pfc-donut" viewBox="0 0 {size} {size}" width="{size}" height="{size}" '
            f'xmlns="http://www.w3.org/2000/svg" aria-hidden="true">{"".join(segs)}{middle}</svg>')


def sparkbars_svg(values, colour, width=120, height=28):
    """Tiny comparison bars for ranking rows. values: [0..1]."""
    if not values:
        return ""
    n = len(values)
    bw = width / n
    bars = []
    for i, v in enumerate(values):
        h = max(1.5, height * min(max(v, 0), 1))
        bars.append(f'<rect x="{i * bw:.1f}" y="{height - h:.1f}" width="{bw * 0.72:.1f}" '
                    f'height="{h:.1f}" fill="{colour}" rx="1"/>')
    return (f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
            f'xmlns="http://www.w3.org/2000/svg" aria-hidden="true">{"".join(bars)}</svg>')
