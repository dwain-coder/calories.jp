"""Public HTML site: pages at the root, robots.txt, sitemaps."""
import os
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from . import cards, faq, groups, media, nutrient_groups, queries, seo
from .i18n import LANGS, MACRO_DV, MEXT_GROUPS_EN, NUTRIENT_LABELS_EN, SITE_NAME, t
from ..scripts.build_site import slugify_en

# Category URL slugs. ja pages use the Japanese category itself as the slug;
# en pages use the slugified English group label (meats, grains, ...).
EN_CAT_SLUGS = {slugify_en(en): ja for ja, en in MEXT_GROUPS_EN.items()}
JA_CAT_TO_EN_SLUG = {ja: slugify_en(en) for ja, en in MEXT_GROUPS_EN.items()}


def category_slug(lang, ja_category):
    if lang == "ja":
        return ja_category
    return JA_CAT_TO_EN_SLUG.get(ja_category)


def resolve_category(lang, slug):
    """URL slug -> Japanese category name, or None."""
    if lang == "ja":
        return slug
    return EN_CAT_SLUGS.get(slug)

router = APIRouter()
templates = Jinja2Templates(directory="templates")
SITEMAP_DIR = Path("data/sitemaps")
# Page caching is opt-in for production (set SITE_CACHE_MAX_AGE=3600 there);
# default revalidates every request so development is never stale.
_MAX_AGE = int(os.environ.get("SITE_CACHE_MAX_AGE", "0"))
CACHE = {"Cache-Control": f"public, max-age={_MAX_AGE}" if _MAX_AGE else "no-cache"}

# Set SITE_NOINDEX=1 while the site is on a temporary hostname. A staging URL
# that gets crawled becomes a duplicate of the real one, and the cleanup after
# is worse than the wait: robots.txt refuses everything and every page carries
# a noindex tag until this is switched off.
SITE_NOINDEX = os.environ.get("SITE_NOINDEX", "").lower() in ("1", "true", "yes")


# One language, so the URLs carry no language segment: calories.jp/food/… is
# the page, not calories.jp/ja/food/…. The lang value still exists because the
# strings, reference values and name rows are keyed by it, and re-adding a
# second locale should not mean re-deriving every URL by hand.
SITE_LANG = LANGS[0]


def _render(request, name, lang, ctx, headers=CACHE):
    base = {
        "request": request,
        "lang": lang,
        "other_lang": "ja" if lang == "en" else "en",
        "t": lambda key, **fmt: t(lang, key, **fmt),
        "site_name": SITE_NAME[lang],
        "seo": seo,
        "nutrient_labels_en": NUTRIENT_LABELS_EN,
        "mext_groups_en": MEXT_GROUPS_EN,
        "cat_slug": category_slug,
        "macro_dv": MACRO_DV[lang],
        "group_color": groups.color,
        "group_emoji": groups.emoji,
        "fingerprint": cards.fingerprint_svg,
        "pfc_donut": cards.pfc_donut_svg,
        "media_get": media.get,
        "media_video": media.video,
        "nutrient_groups": lambda rows: nutrient_groups.grouped(rows, lang),
        "media_slot": None,          # pages that use imagery override this
        "noindex": False,            # paginated pages override this
    }
    base.update(ctx)
    if SITE_NOINDEX:
        base["noindex"] = True
    return templates.TemplateResponse(request, name, base, headers=headers)


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    lang = SITE_LANG
    data = queries.home_data(lang)
    return _render(request, "home.html", lang, {
        "data": data,
        "canonical": seo.base_url(lang) + "/",
        "alternates": {l: seo.base_url(l) + "/" for l in LANGS},
    })


def _page_or_404(page_type, slug):
    page = queries.get_page(SITE_LANG, slug)
    if not page or page["page_type"] != page_type:
        raise HTTPException(status_code=404, detail="Not found")
    return page


@router.get("/food/{slug}", response_class=HTMLResponse)
def food_page(request: Request, slug: str):
    lang = SITE_LANG
    page = _page_or_404("food", slug)
    data = queries.get_food_page_data(page)
    url = seo.page_url(lang, "food", slug)
    name = queries.display_name(data["names"], data["item"], lang)
    jsonld = [seo.food_jsonld(lang, name, url, data["nutrition"])]
    category = data["item"]["category"]
    if not category or category == "foundation":  # FDC's flat placeholder category
        category, cat_url = t(lang, "foods"), None
    else:
        label = MEXT_GROUPS_EN.get(category, category) if lang == "en" else category
        cslug = category_slug(lang, category)
        cat_url = seo.base_url(lang) + f"/category/{quote(cslug)}" if cslug else None
        category = label
    crumbs = [(t(lang, "home"), seo.base_url(lang) + "/"),
              (category, cat_url),
              (name, None)]
    jsonld.append(seo.breadcrumbs_jsonld(crumbs))
    qa = faq.food_faq(
        lang, name, data["nutrition"], salt_g=data["salt_g"],
        portions=data["portions"], preps=data["preps"], source=data["item"]["source"],
    )
    faq_ld = seo.faq_jsonld(qa)
    if faq_ld:
        jsonld.append(faq_ld)
    return _render(request, "food.html", lang, {
        "page": page, "d": data, "name": name, "faq": qa,
        "canonical": url,
        "alternates": {l: seo.page_url(l, pt, s) for l, (pt, s) in data["alternates"].items()},
        "hreflangs": seo.hreflang_links(data["alternates"]),
        "jsonld": [seo.jsonld_script(j) for j in jsonld],
        "crumbs": crumbs,
    })


@router.get("/dish/{slug}", response_class=HTMLResponse)
def dish_page(request: Request, slug: str):
    lang = SITE_LANG
    page = _page_or_404("dish", slug)
    data = queries.get_dish_page_data(page)
    url = seo.page_url(lang, "dish", slug)
    name = queries.display_name(data["names"], data["item"], lang)
    ing_lines = [l.strip() for l in (data["dish"].get("recipe_ingredients") or "").splitlines() if l.strip()]
    step_lines = [l.strip() for l in (data["dish"].get("recipe_steps") or "").splitlines() if l.strip()]
    jsonld = [seo.recipe_jsonld(
        lang, name, url, ing_lines, step_lines,
        data["computed"]["totals"] if data["show_nutrition"] else None,
    )]
    crumbs = [(t(lang, "home"), seo.base_url(lang) + "/"),
              (data["item"]["category"] or t(lang, "dishes"), None),
              (name, None)]
    jsonld.append(seo.breadcrumbs_jsonld(crumbs))
    return _render(request, "dish.html", lang, {
        "page": page, "d": data, "name": name,
        "canonical": url,
        "alternates": {l: seo.page_url(l, pt, s) for l, (pt, s) in data["alternates"].items()},
        "hreflangs": seo.hreflang_links(data["alternates"]),
        "jsonld": [seo.jsonld_script(j) for j in jsonld],
        "crumbs": crumbs,
    })


@router.get("/foods", response_class=HTMLResponse)
def browse_page(request: Request, page: int = 1, sort: str = "name",
                category: str = ""):
    lang = SITE_LANG
    page = max(1, min(page, 500))
    data = queries.browse_foods(lang, page=page, sort=sort, category=category or None)
    base = seo.base_url(lang) + "/foods"
    qs = (f"?sort={sort}" if sort != "name" else "")
    return _render(request, "browse.html", lang, {
        "d": data, "sort": sort,
        "canonical": base + (f"?page={page}" if page > 1 else "") ,
        "prev_url": (base + f"?page={page - 1}{qs.replace('?', '&')}") if page > 1 else None,
        "next_url": (base + f"?page={page + 1}{qs.replace('?', '&')}") if page < data["pages"] else None,
        "alternates": {l: seo.base_url(l) + "/foods" for l in LANGS},
        "meta_description": (
            f"Browse {data['total']} verified foods with calories, protein, fat and carbohydrates per 100 g."
            if lang == "en" else
            f"検証済み食品{data['total']}件を一覧。100gあたりのカロリー・たんぱく質・脂質・炭水化物。"
        ),
        "noindex": page > 1,
    })


@router.get("/category/{cslug}", response_class=HTMLResponse)
def category_page(request: Request, cslug: str):
    lang = SITE_LANG
    ja_cat = resolve_category(lang, cslug)
    data = queries.category_data(lang, ja_cat) if ja_cat else None
    if not data:
        raise HTTPException(status_code=404, detail="Not found")
    label = MEXT_GROUPS_EN.get(ja_cat, ja_cat) if lang == "en" else ja_cat
    url = seo.base_url(lang) + f"/category/{quote(cslug)}"
    alternates = {}
    for l in LANGS:
        s = category_slug(l, ja_cat)
        if s and queries.category_data(l, ja_cat):
            alternates[l] = seo.base_url(l) + f"/category/{quote(s)}"
    crumbs = [(t(lang, "home"), seo.base_url(lang) + "/"), (label, None)]
    return _render(request, "category.html", lang, {
        "d": data, "label": label, "ja_cat": ja_cat,
        "canonical": url, "alternates": alternates,
        "hreflangs": [(l, u) for l, u in sorted(alternates.items())],
        "jsonld": [seo.jsonld_script(seo.breadcrumbs_jsonld(crumbs))],
        "crumbs": crumbs,
        "meta_description": (
            f"{label}: calories, protein, fat and carbohydrates for {data['n']} foods, compared per 100 g."
            if lang == "en" else
            f"{label}のカロリー・たんぱく質・脂質・炭水化物を{data['n']}件で比較。100gあたりの検証済みデータ。"
        ),
    })


@router.get("/guides/cooking-and-calories", response_class=HTMLResponse)
def guide_cooking(request: Request):
    """A written guide whose every figure is a measurement, not an estimate."""
    lang = SITE_LANG
    data = queries.cooking_effect(lang, limit=40)
    if not data["rows"]:
        raise HTTPException(status_code=404, detail="Not built yet")
    url = seo.base_url(lang) + "/guides/cooking-and-calories"
    crumbs = [(t(lang, "home"), seo.base_url(lang) + "/"),
              (t(lang, "guide_cooking_title"), None)]
    return _render(request, "guide_cooking.html", lang, {
        "d": data,
        "canonical": url,
        "alternates": {l: seo.base_url(l) + "/guides/cooking-and-calories" for l in LANGS},
        "hreflangs": seo.hreflang_links({}),
        "jsonld": [seo.jsonld_script(seo.breadcrumbs_jsonld(crumbs))],
        "crumbs": crumbs,
        "meta_description": t(lang, "guide_cooking_meta", n=data["total"]),
    })


@router.get("/goals", response_class=HTMLResponse)
def goals_page(request: Request):
    lang = SITE_LANG
    return _render(request, "goals.html", lang, {
        "canonical": seo.base_url(lang) + "/goals",
        "alternates": {l: seo.base_url(l) + "/goals" for l in LANGS},
        "meta_description": t(lang, "goals_intro"),
    })


@router.get("/search", response_class=HTMLResponse)
def search_page(request: Request, q: str = ""):
    lang = SITE_LANG
    results = queries.search(q, lang, limit=50) if q else []
    return _render(request, "search.html", lang, {
        "q": q, "results": results,
        "canonical": seo.base_url(lang) + "/search",
        "noindex": True,
    }, headers={"Cache-Control": "no-store"})


@router.get("/meal-calculator", response_class=HTMLResponse)
def meal_calculator(request: Request):
    lang = SITE_LANG
    return _render(request, "meal_calc.html", lang, {
        "canonical": seo.base_url(lang) + "/meal-calculator",
        "alternates": {l: seo.base_url(l) + "/meal-calculator" for l in LANGS},
    })


@router.get("/analyzer", response_class=HTMLResponse)
def analyzer_page(request: Request):
    lang = SITE_LANG
    return _render(request, "analyzer.html", lang, {
        "canonical": seo.base_url(lang) + "/analyzer",
        "alternates": {l: seo.base_url(l) + "/analyzer" for l in LANGS},
    })


@router.get("/sources", response_class=HTMLResponse)
def sources_page(request: Request):
    lang = SITE_LANG
    return _render(request, "sources.html", lang, {
        "attribution": seo.ATTRIBUTION,
        "canonical": seo.base_url(lang) + "/sources",
        "alternates": {l: seo.base_url(l) + "/sources" for l in LANGS},
    })


# Who runs the site, what it does with a visitor's data, and how to be reached.
# Ad and affiliate networks require all three before they approve a site, and a
# site publishing nutrition figures has no business being anonymous. The two
# facts only the owner can supply come from the environment rather than being
# written into the repository.
SITE_OPERATOR = os.environ.get("SITE_OPERATOR", "")
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "")
# Flipped on when those scripts are actually added, so the privacy policy never
# claims a tracker the site does not run, nor stays silent about one it does.
HAS_ADS = os.environ.get("SITE_ADS", "").lower() in ("1", "true", "yes")
HAS_ANALYTICS = os.environ.get("SITE_ANALYTICS", "").lower() in ("1", "true", "yes")
POLICY_UPDATED = os.environ.get("POLICY_UPDATED", "2026-08-30")


def _standing_page(request, lang, name, extra=None):
    """The pages that describe the site rather than the data."""
    ctx = {
        "operator": SITE_OPERATOR or t(lang, "operator_unset"),
        "contact_email": CONTACT_EMAIL,
        "canonical": seo.base_url(lang) + f"/{name}",
        "alternates": {l: seo.base_url(l) + f"/{name}" for l in LANGS},
    }
    ctx.update(extra or {})
    return _render(request, f"{name}.html", lang, ctx)


@router.get("/about", response_class=HTMLResponse)
def about_page(request: Request):
    lang = SITE_LANG
    return _standing_page(request, lang, "about", {"counts": queries.corpus_counts(lang)})


@router.get("/privacy", response_class=HTMLResponse)
def privacy_page(request: Request):
    lang = SITE_LANG
    return _standing_page(request, lang, "privacy", {
        "has_ads": HAS_ADS, "has_analytics": HAS_ANALYTICS, "updated": POLICY_UPDATED,
    })


@router.get("/contact", response_class=HTMLResponse)
def contact_page(request: Request):
    lang = SITE_LANG
    return _standing_page(request, lang, "contact")


@router.get("/ja", include_in_schema=False)
@router.get("/ja/{path:path}", include_in_schema=False)
def drop_language_prefix(path: str = ""):
    """The site was served under /ja/ while a second locale was planned.

    It is one language, so the prefix is gone — but the old URLs were public,
    and a 301 is what tells a browser, a bookmark and a crawler that the page
    moved rather than vanished.
    """
    return RedirectResponse("/" + path.lstrip("/"), status_code=301)


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    if SITE_NOINDEX:
        return PlainTextResponse("User-agent: *\nDisallow: /", headers=CACHE)
    lines = ["User-agent: *", "Disallow: /items", "Disallow: /api/",
             "Disallow: /export/", "Disallow: /docs", "Allow: /"]
    for lang in LANGS:
        lines.append(f"Sitemap: {seo.base_url(lang)}/sitemap.xml")
    return PlainTextResponse("\n".join(dict.fromkeys(lines)), headers=CACHE)


@router.get("/sitemap.xml")
def sitemap_index():
    body = ['<?xml version="1.0" encoding="UTF-8"?>',
            '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for p in sorted(SITEMAP_DIR.glob("sitemap-*.xml")):
        lang = "ja" if p.stem.endswith("-ja") else "en"
        body.append(f"<sitemap><loc>{seo.base_url(lang)}/{p.name}</loc></sitemap>")
    body.append("</sitemapindex>")
    return Response("\n".join(body), media_type="application/xml", headers=CACHE)


@router.get("/sitemap-{name}.xml")
def sitemap_file(name: str):
    if not name.replace("-", "").isalnum():
        raise HTTPException(status_code=404, detail="Not found")
    path = SITEMAP_DIR / f"sitemap-{name}.xml"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Sitemap not built")
    return Response(path.read_text(encoding="utf-8"), media_type="application/xml", headers=CACHE)
