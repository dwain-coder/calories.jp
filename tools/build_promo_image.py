"""Build static/media/promo-analyzer.webp, the picture on the promo card.

A phone on a tile, like the card it was modelled on, showing the analyzer's
REAL result for the site's own analyzer photograph: the saved response in
data/raw/analyzer_examples/stock-analyzer.json. The figure is printed the way
the analyzer prints it — that total is partial (one ingredient did not match),
so it is a floor, 「≥ 400」, not 「約 400」.

    uv run python tools/build_promo_image.py

Fonts are Windows' Yu Gothic; pass --font-dir to use another copy.
"""
import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SIZE = 320                      # displayed at 160 px, so sharp on a 2x screen
PHOTO = Path("static/media/analyzer.jpg")
RESULT = Path("data/raw/analyzer_examples/stock-analyzer.json")
OUT = Path("static/media/promo-analyzer.webp")

ACCENT = "#F26722"
INK, INK_FAINT = "#2B2118", "#A2938A"
PFC = ("#3D6B8E", "#C9972E", "#7A8B3D")       # the site's own P/F/C colours


def headline(result):
    """What the analyzer's headline says for this result (static/analyzer.js)."""
    kcal = result["totals"]["energy_kcal"]
    rounded = int(round(kcal / 50.0) * 50)
    return f"≥ {rounded}" if result.get("unmatched") else f"約 {rounded}"


def build(font_dir):
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    bold = lambda s: ImageFont.truetype(str(font_dir / "YuGothB.ttc"), s)
    regular = lambda s: ImageFont.truetype(str(font_dir / "YuGothM.ttc"), s)

    # The phone: a white screen, the photograph on top, the result under it.
    pw, ph = 176, 236
    phone = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    d = ImageDraw.Draw(phone)
    d.rounded_rectangle((0, 0, pw - 1, ph - 1), radius=24, fill="#FFFFFF", outline="#E9DDD3", width=2)

    photo = Image.open(PHOTO).convert("RGB")
    w, h = photo.size
    crop = photo.crop((int(w * 0.22), int(h * 0.30), int(w * 0.92), int(h * 0.86)))
    shot_w, shot_h = pw - 16, 104
    crop = crop.resize((shot_w, shot_h), Image.LANCZOS)
    mask = Image.new("L", (shot_w, shot_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, shot_w - 1, shot_h - 1), radius=16, fill=255)
    phone.paste(crop, (8, 8), mask)

    t = result["totals"]
    d.text((14, 120), "幕の内弁当", font=regular(13), fill=INK_FAINT)
    d.text((14, 138), headline(result), font=bold(30), fill=ACCENT)
    after = 14 + d.textlength(headline(result), font=bold(30)) + 6
    d.text((after, 172), "kcal", font=bold(14), fill=INK, anchor="ls")

    # P/F/C as shares of energy, the same split the food pages draw.
    energy = [t["protein_g"] * 4, t["fat_g"] * 9, t["carbohydrate_g"] * 4]
    x, bar_w, y = 14, pw - 28, 180
    for share, colour in zip(energy, PFC):
        seg = bar_w * share / sum(energy)
        d.rounded_rectangle((x, y, x + seg - 2, y + 9), radius=3, fill=colour)
        x += seg
    legend = f"P {t['protein_g']:.0f}g  F {t['fat_g']:.0f}g  C {t['carbohydrate_g']:.0f}g"
    d.text((14, 198), legend, font=regular(12), fill=INK)
    d.rounded_rectangle((14, 218, pw - 60, 224), radius=3, fill="#F1E7DF")

    # The tile, a few sparks, and the phone at a slant.
    tile = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    td = ImageDraw.Draw(tile)
    td.rounded_rectangle((2, 2, SIZE - 3, SIZE - 3), radius=44, fill="#FDECE1", outline="#FBDCC9", width=3)
    for cx, cy, r in ((52, 70, 4), (272, 58, 3), (40, 250, 3), (282, 236, 5), (250, 290, 3)):
        td.ellipse((cx - r, cy - r, cx + r, cy + r), fill=ACCENT)

    shadow = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((0, 0, pw - 1, ph - 1), radius=24, fill=(43, 33, 24, 40))
    for layer, offset in ((shadow, (6, 8)), (phone, (0, 0))):
        rotated = layer.rotate(-8, resample=Image.BICUBIC, expand=True)
        pos = ((SIZE - rotated.width) // 2 + offset[0], (SIZE - rotated.height) // 2 + offset[1])
        tile.alpha_composite(rotated, pos)

    tile.save(OUT, "WEBP", quality=88, method=6)
    print(f"{OUT} {OUT.stat().st_size // 1024} KB — {headline(result)} kcal, {legend}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--font-dir", default="C:/Windows/Fonts", type=Path)
    build(ap.parse_args().font_dir)
