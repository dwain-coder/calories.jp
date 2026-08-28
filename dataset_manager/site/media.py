"""Stock imagery and video for the non-data pages.

Deliberately scoped: photographs appear on the home page, the tool pages and
the guide pages, and never on a food, dish or nutrient page. A photograph
beside an exact measurement implies it depicts that exact entry, and with a
composition table of thousands of rows no stock library can honestly do that.
On a landing page the picture is atmosphere, and atmosphere is allowed to be
generic.

Assets live in static/media/ and are declared here with their credit. Anything
missing simply does not render, so the site never ships a broken image; run
tools/fetch_stock.py to populate.
"""
from pathlib import Path

MEDIA_DIR = Path("static/media")

# slot -> asset. `credit`/`credit_url` are required by most stock licences and
# are rendered with the image. `focus` biases the crop for wide hero boxes.
MEDIA = {
    "home-hero": {
        "file": "home-hero.jpg",
        "alt_en": "A Japanese set meal seen from above: rice, miso soup, tamagoyaki and small dishes on a tray",
        "alt_ja": "真上から見た和定食。ご飯、味噌汁、卵焼き、小鉢が膳に並ぶ",
        "credit": "", "credit_url": "", "focus": "50% 52%",
    },
    "meal-calculator": {
        "file": "meal-calculator.jpg",
        "alt_en": "A digital kitchen scale beside 15 ml and 5 ml measuring spoons on a wooden counter",
        "alt_ja": "木のカウンターに置かれたデジタルスケールと大さじ・小さじの計量スプーン",
        "credit": "", "credit_url": "", "focus": "48% 50%",
    },
    "analyzer": {
        "file": "analyzer.jpg",
        "alt_en": "Lacquered bento boxes holding tempura, sushi rolls, grilled fish and pickles",
        "alt_ja": "天ぷら、巻き寿司、焼き魚、漬物が詰められた漆の弁当箱",
        "credit": "", "credit_url": "", "focus": "50% 55%",
    },
    "goals": {
        "file": "goals.jpg",
        "alt_en": "A gloved hand holding a bowl of dressed greens beside cabbage and cut fruit",
        "alt_ja": "刻んだ野菜と果物のそばで、和えた青菜のボウルを持つ手",
        "credit": "", "credit_url": "", "focus": "50% 45%",
    },
    "guide-cooking": {
        "file": "guide-cooking.jpg",
        "alt_en": "Earthenware pots steaming on a hot plate",
        "alt_ja": "鉄板の上で湯気を立てる土鍋",
        "credit": "", "credit_url": "", "focus": "50% 48%",
    },
    "sources": {
        "file": "sources.jpg",
        "alt_en": "Shelves packed with rows of books",
        "alt_ja": "本がぎっしり並んだ書棚",
        "credit": "", "credit_url": "", "focus": "50% 50%",
    },
}

# Optional video per slot. Nothing plays unless a slot is filled in here, and
# every entry is something a person has actually watched.
#
# Two kinds, and the difference matters:
#
#   file  — an MP4 in static/media/, served from our own origin. No third-party
#           request, no cookies, no consent banner. Use for short ambient loops.
#           Rendered muted, looping and without controls.
#
#   url   — a third-party embed (YouTube/Vimeo). Use only when the content
#           itself is the point, e.g. an official ministry explainer. Give the
#           EMBED url, not the watch page, and prefer youtube-nocookie.com:
#             https://www.youtube-nocookie.com/embed/VIDEO_ID
#           Rendered with controls and no autoplay.
#
# Shape:
#   "analyzer": {
#       "file": "analyzer.mp4",          # or "url": "https://…/embed/ID"
#       "poster": "analyzer.jpg",        # optional; falls back to the slot photo
#       "title_ja": "…", "title_en": "…",
#   }
VIDEO = {
    "home-hero": {
        "file": "home-hero.mp4",
        "title_ja": "IHコンロのフライパンで魚の切り身を焼く様子",
        "title_en": "Fish fillets cooking in a pan on an induction hob",
    },
    "meal-calculator": {
        "file": "meal-calculator.mp4",
        "title_ja": "デジタルスケールに載せたボウルに材料を量り入れる様子",
        "title_en": "Weighing an ingredient into a bowl on a digital scale",
        "focus": "50% 68%",   # the scale's display sits low in the frame
    },
    "analyzer": {
        "file": "analyzer.mp4",
        "title_ja": "食事を撮影して解析する様子",
        "title_en": "Photographing a meal to analyse it",
    },
    "guide-cooking": {
        "file": "guide-cooking.mp4",
        "title_ja": "蓋をした鍋から湯気が立ちのぼる様子",
        "title_en": "Steam rising from a lidded pot",
    },
}


def _exists(name):
    return (MEDIA_DIR / name).is_file()


def get(slot, lang="ja"):
    """Return a render-ready asset dict, or None when the file is absent."""
    m = MEDIA.get(slot)
    if not m or not _exists(m["file"]):
        return None
    stem = Path(m["file"]).stem
    webp = f"{stem}.webp"
    return {
        "src": f"/static/media/{m['file']}",
        "webp": f"/static/media/{webp}" if _exists(webp) else None,
        "alt": m.get(f"alt_{lang}") or m.get("alt_en") or "",
        "credit": m.get("credit") or "",
        "credit_url": m.get("credit_url") or "",
        "focus": m.get("focus", "50% 50%"),
    }


def video(slot, lang="ja"):
    """Vetted video for a slot, or None. Never a blanket embed.

    A self-hosted entry whose file is missing returns None, so a half-finished
    配信 never renders as a broken player.
    """
    v = VIDEO.get(slot)
    if not v:
        return None
    title = v.get(f"title_{lang}") or v.get("title_en") or v.get("title_ja") or ""
    if v.get("file"):
        if not _exists(v["file"]):
            return None
        poster = v.get("poster")
        if not poster or not _exists(poster):
            m = MEDIA.get(slot) or {}
            poster = m.get("file") if m.get("file") and _exists(m["file"]) else None
        return {
            "kind": "file",
            "src": f"/static/media/{v['file']}",
            "poster": f"/static/media/{poster}" if poster else None,
            "title": title,
            # The frame is a circle, so a subject sitting low in a 16:9 clip
            # gets cropped away. Same knob the stills use.
            "focus": v.get("focus") or (MEDIA.get(slot) or {}).get("focus", "50% 50%"),
        }
    if v.get("url"):
        return {"kind": "embed", "url": v["url"], "title": title}
    return None
