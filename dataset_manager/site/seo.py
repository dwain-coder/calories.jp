"""SEO helpers: absolute URLs, hreflang, JSON-LD builders, sitemap writer."""
import json
import os
from urllib.parse import quote

from .i18n import SITE_NAME


def base_url(lang):
    dom = os.environ.get(f"SITE_DOMAIN_{lang.upper()}")
    return f"https://{dom}" if dom else "http://localhost:8000"


def page_path(lang, page_type, slug):
    seg = "food" if page_type == "food" else "dish"
    return f"/{lang}/{seg}/{quote(slug)}"


def page_url(lang, page_type, slug):
    return base_url(lang) + page_path(lang, page_type, slug)


def hreflang_links(pages):
    """pages: {lang: (page_type, slug)}. Returns [(hreflang, url)] incl. x-default->en."""
    links = [(lang, page_url(lang, pt, slug)) for lang, (pt, slug) in sorted(pages.items())]
    if "en" in pages:
        pt, slug = pages["en"]
        links.append(("x-default", page_url("en", pt, slug)))
    return links


ATTRIBUTION = {
    "MEXT Standard Tables": {
        "name_ja": "文部科学省 日本食品標準成分表",
        "name_en": "MEXT Standard Tables of Food Composition",
        "ja": "出典：文部科学省「日本食品標準成分表2023年版（八訂）」",
        "en": "Source: Standard Tables of Food Composition in Japan 2023 (8th rev.), MEXT",
        "url": "https://www.mext.go.jp/a_menu/syokuhinseibun/",
    },
    "MAFF Our Regional Cuisines": {
        "name_ja": "農林水産省 うちの郷土料理",
        "name_en": "MAFF Our Regional Cuisines",
        "ja": "出典：農林水産省「うちの郷土料理」",
        "en": "Source: \"Our Regional Cuisines\", Ministry of Agriculture, Forestry and Fisheries (MAFF)",
        "url": "https://www.maff.go.jp/j/keikaku/syokubunka/k_ryouri/",
    },
    "USDA FoodData Central": {
        "name_ja": "米国農務省 FoodData Central",
        "name_en": "USDA FoodData Central",
        "ja": "出典：USDA FoodData Central（パブリックドメイン）",
        "en": "Source: USDA FoodData Central (public domain)",
        "url": "https://fdc.nal.usda.gov/",
    },
    "USDA FoodKeeper": {
        "name_ja": "米国農務省 FoodKeeper",
        "name_en": "USDA FoodKeeper",
        "ja": "出典：USDA FoodKeeper（パブリックドメイン）",
        "en": "Source: USDA FoodKeeper (public domain)",
        "url": "https://www.foodsafety.gov/keep-food-safe/foodkeeper-app",
    },
}


def _fmt(v, suffix):
    if v is None:
        return None
    return f"{round(v, 1):g} {suffix}"


def nutrition_jsonld(nutrition, grams=100):
    """schema.org NutritionInformation for per-`grams` values."""
    if not nutrition:
        return None
    d = {
        "@type": "NutritionInformation",
        "servingSize": f"{grams} g",
        "calories": _fmt(nutrition.get("energy_kcal"), "calories"),
        "proteinContent": _fmt(nutrition.get("protein_g"), "g"),
        "fatContent": _fmt(nutrition.get("fat_g"), "g"),
        "carbohydrateContent": _fmt(nutrition.get("carbohydrate_g"), "g"),
    }
    return {k: v for k, v in d.items() if v is not None}


def breadcrumbs_jsonld(crumbs):
    """crumbs: [(name, url|None)] — last item usually has no url."""
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": name,
             **({"item": url} if url else {})}
            for i, (name, url) in enumerate(crumbs)
        ],
    }


def food_jsonld(lang, name, url, nutrition):
    d = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": name,
        "url": url,
        "inLanguage": lang,
        "publisher": {"@type": "Organization", "name": SITE_NAME[lang]},
    }
    nut = nutrition_jsonld(nutrition)
    if nut:
        d["mainEntity"] = {"@type": "MenuItem", "name": name, "nutrition": nut}
    return d


def recipe_jsonld(lang, name, url, ingredients, steps, nutrition=None):
    d = {
        "@context": "https://schema.org",
        "@type": "Recipe",
        "name": name,
        "url": url,
        "inLanguage": lang,
        "recipeIngredient": ingredients,
        "recipeInstructions": [{"@type": "HowToStep", "text": s} for s in steps],
    }
    nut = nutrition_jsonld(nutrition) if nutrition else None
    if nut:
        d["nutrition"] = nut
    return d


def faq_jsonld(qa):
    """qa: [(question, answer)] -> FAQPage. Only emit when the same Q&A is
    visible on the page."""
    if not qa:
        return None
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": q,
             "acceptedAnswer": {"@type": "Answer", "text": a}}
            for q, a in qa
        ],
    }


def jsonld_script(data):
    return json.dumps(data, ensure_ascii=False)


def sitemap_xml(entries):
    """entries: [{loc, alternates: [(hreflang, url)]}] -> XML str."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:xhtml="http://www.w3.org/1999/xhtml">',
    ]
    for e in entries:
        lines.append("<url>")
        lines.append(f"<loc>{e['loc']}</loc>")
        for hl, url in e.get("alternates") or []:
            lines.append(f'<xhtml:link rel="alternate" hreflang="{hl}" href="{url}"/>')
        lines.append("</url>")
    lines.append("</urlset>")
    return "\n".join(lines)


def source_label(source, lang):
    """The source name as a reader of this language would write it.

    The keys of ATTRIBUTION are internal identifiers and are English; showing
    them raw put "MEXT Standard Tables" at the top of a card on a site that is
    otherwise entirely Japanese.
    """
    entry = ATTRIBUTION.get(source)
    if not entry:
        return source
    return entry.get(f"name_{lang}") or entry.get("name_en") or source
