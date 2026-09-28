"""Public HTML site: pages at the root, robots.txt, sitemaps."""
import hashlib
import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from . import (cards, embeds, faq, groups, media, menuterms, nutrient_groups,
               nutrient_pages, queries, seo)
from .i18n import LANGS, MACRO_DV, MEXT_GROUPS_EN, NUTRIENT_LABELS_EN, SITE_NAME, t
from ..blog import store as blog_store
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


# --- cache-busted asset URLs -------------------------------------------------
# Cloudflare caches /static/site.css for four hours, and the URL never changed,
# so a deployed CSS fix reached nobody until that expired: the mobile menu
# layout shipped and the live site kept serving a 26-minute-old stylesheet.
#
# Appending a hash of the file's own bytes gives each build a new URL, so the
# cache is never asked for a stale one and never has to be purged by hand.
# Read once per process: the files are baked into the image and cannot change
# under a running server.
_ASSET_ROOT = Path("static")
_asset_versions = {}


def asset(path):
    """/static/site.css -> /static/site.css?v=<hash of its bytes>."""
    if path not in _asset_versions:
        try:
            data = (_ASSET_ROOT / path.split("/static/", 1)[-1]).read_bytes()
            _asset_versions[path] = hashlib.sha256(data).hexdigest()[:10]
        except OSError:
            _asset_versions[path] = ""
    v = _asset_versions[path]
    return f"{path}?v={v}" if v else path


# A Jinja global rather than a key in _render's context: base.html is also
# reached by templates that do not come through _render, and a missing `asset`
# there is not a wrong URL, it is a 500 on the whole page.
templates.env.globals["asset"] = asset

SITEMAP_DIR = Path("data/sitemaps")

# Every page is rendered from a database that only changes when a new image is
# deployed, and the site was sending `no-cache` on all 4,000 of them: Cloudflare
# reported cf-cache-status: DYNAMIC and forwarded every hit, so each visitor paid
# for a fresh render of a page identical to the last one.
#
# Caching is opt-in for production and stays off in development, because a
# stale page while editing one is worse than a slow one.
#
# SITE_CACHE_MAX_AGE decides it, and on a host that is not Railway it is the
# only thing that does — set it in the compose env. Railway injects
# RAILWAY_ENVIRONMENT by itself, so a deployment there still tells itself apart
# from a laptop without anyone remembering a variable. Either way an explicit
# SITE_CACHE_MAX_AGE wins, including `0` to switch caching off in production.
_DEPLOYED = bool(os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RAILWAY_SERVICE_ID"))
_MAX_AGE = int(os.environ.get("SITE_CACHE_MAX_AGE") or (3600 if _DEPLOYED else 0))

# stale-while-revalidate lets the edge answer instantly from a slightly old copy
# and refresh behind the reader, so a deploy is never a cliff of slow requests.
# An embed is cached like any other page, but never by a shared proxy under
# someone else's domain — it is the same document wherever it is framed.
EMBED_CACHE = {"Cache-Control": "public, max-age=600"}

CACHE = {"Cache-Control":
         f"public, max-age={_MAX_AGE}, stale-while-revalidate=86400" if _MAX_AGE
         else "no-cache"}

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
    counts = data.get("counts") or {}
    jsonld = [
        seo.website_jsonld(lang),
        seo.dataset_jsonld(lang, {
            "食品ページ": counts.get("food"),
            "料理ページ": counts.get("dish"),
        }),
    ]
    from .analyzer_examples import EXAMPLES
    return _render(request, "home.html", lang, {
        "data": data, "examples": EXAMPLES, "numbers": queries.home_numbers(lang),
        "canonical": seo.base_url(lang) + "/",
        "alternates": {l: seo.base_url(l) + "/" for l in LANGS},
        "jsonld": [seo.jsonld_script(j) for j in jsonld],
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
        serving=data.get("serving"),
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
        "embed_offer": (food_snippets(slug, data, name)
                        if page.get("indexable") and data["nutrition"] else None),
        "embed_compare_url": f"/embed?a={quote(slug)}#compare",
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


@router.get("/shops", include_in_schema=False)
@router.get("/shops/{slug:path}", include_in_schema=False)
def shops_moved(slug: str = ""):
    """/shops served the same 251 chains as /menu — the same rows, the same
    prices, a second URL for one page. Two addresses for one page splits the
    links between them and lets a search engine pick the one we did not mean,
    so /menu is now the only one and this redirects to it permanently.
    """
    target = f"/menu/{quote(slug)}" if slug else "/menu"
    return RedirectResponse(target, status_code=301)


@router.get("/menu", response_class=HTMLResponse)
def menu_index_page(request: Request):
    """Chain menus directory with quick search, side-by-side calories, and AI tools."""
    lang = SITE_LANG
    shops = queries.shops_index(lang)
    url = seo.base_url(lang) + "/menu"
    crumbs = [(t(lang, "home"), seo.base_url(lang) + "/"), (t(lang, "menu"), None)]
    jsonld = [
        seo.breadcrumbs_jsonld(crumbs),
        seo.chain_directory_jsonld(lang, shops),
    ]
    return _render(request, "menus.html", lang, {
        "shops": shops,
        "canonical": url,
        "crumbs": crumbs,
        "jsonld": [seo.jsonld_script(j) for j in jsonld],
        "meta_description": t(lang, "menu_intro"),
    })


@router.get("/menu/{slug}", response_class=HTMLResponse)
def menu_page(request: Request, slug: str):
    """One chain's menu: side-by-side prices & calories, order tray calculator, and AI estimator."""
    lang = SITE_LANG
    page = queries.get_shop_page(lang, slug)
    if not page:
        raise HTTPException(status_code=404, detail="Not found")
    data = queries.get_shop_page_data(page)
    canonical_slug = page.get("slug", slug)
    url = seo.base_url(lang) + f"/menu/{quote(canonical_slug)}"
    name = data["shop"].get("name", slug)
    crumbs = [(t(lang, "home"), seo.base_url(lang) + "/"),
              (t(lang, "menu"), seo.base_url(lang) + "/menu"),
              (name, None)]
    shop_info = data.get("shop", {})
    jsonld = [
        seo.breadcrumbs_jsonld(crumbs),
        seo.restaurant_menu_jsonld(
            lang, name, url, data.get("menu", []),
            description=page.get("meta_description"),
            price_min=shop_info.get("price_min"),
            price_max=shop_info.get("price_max"),
        ),
    ]
    return _render(request, "menu.html", lang, {
        "page": page, "d": data, "name": name,
        "canonical": url,
        "crumbs": crumbs,
        "jsonld": [seo.jsonld_script(j) for j in jsonld],
        "meta_description": page.get("meta_description"),
        "noindex": not page.get("indexable"),
        "embed_offer": menu_snippets(canonical_slug, name, [
            by for by in MENU_LISTS if page.get("indexable") and menu_ranked(data["menu"], by)]),
    })



@router.get("/favicon.ico", include_in_schema=False)
def favicon():
    """Silence 404s for browsers probing default favicon.ico."""
    return Response(status_code=204)




@router.get("/atlas", response_class=HTMLResponse)
def atlas_page(request: Request):
    """The composition table plotted in protein/fat/carbohydrate space.

    It was the second thing on the home page, which is the wrong place for it:
    it is a thing you go and look at, not a thing that explains the site to
    someone who has just arrived.
    """
    lang = SITE_LANG
    data = queries.home_data(lang)
    url = seo.base_url(lang) + "/atlas"
    crumbs = [(t(lang, "home"), seo.base_url(lang) + "/"), (t(lang, "atlas_title"), None)]
    return _render(request, "atlas.html", lang, {
        "data": data,
        "canonical": url,
        "crumbs": crumbs,
        "jsonld": [seo.jsonld_script(seo.breadcrumbs_jsonld(crumbs))],
    })


@router.get("/foods", response_class=HTMLResponse)
def browse_page(request: Request, page: int = 1, sort: str = "name",
                category: str = ""):
    lang = SITE_LANG
    page = max(1, min(page, 500))
    data = queries.browse_foods(lang, page=page, sort=sort, category=category or None)
    base = seo.base_url(lang) + "/foods"
    qs = (f"?sort={sort}" if sort != "name" else "")
    # The category chips, the curated foods and the regional dishes used to sit
    # on the home page. This is where someone looking for a food actually is.
    hub = queries.home_data(lang) if page == 1 and not category else {}
    return _render(request, "browse.html", lang, {
        "d": data, "sort": sort, "hub": hub,
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


def _prefecture_page(request, lang, cslug, prefecture):
    """A prefecture's regional cooking, rather than a table of blank calories.

    MAFF's dishes share items.category with MEXT's food groups, so both were
    rendering through the same comparison template — which lists calories, and a
    dish has none stored. Prefectures get their own page: what is cooked, what
    it is cooked with, and which ingredients are more this prefecture's than
    anyone else's.
    """
    data = queries.prefecture_data(lang, prefecture)
    if not data:
        raise HTTPException(status_code=404, detail="Not found")
    heading = t(lang, "pref_title", pref=prefecture)
    url = seo.base_url(lang) + f"/category/{quote(cslug)}"
    crumbs = [(t(lang, "home"), seo.base_url(lang) + "/"),
              (t(lang, "regional_cuisine"), None), (prefecture, None)]
    siblings = [(p, p) for p in queries.PREFECTURES if p != prefecture and p != "北海道県"]
    jsonld = [
        seo.breadcrumbs_jsonld(crumbs),
        seo.ranking_jsonld(lang, heading, url,
                           [{"slug": d["slug"], "name": d["name"]} for d in data["dishes"]]),
    ]
    return _render(request, "prefecture.html", lang, {
        "d": data, "label": prefecture, "heading": heading,
        "siblings": siblings,
        "canonical": url,
        "crumbs": crumbs,
        "jsonld": [seo.jsonld_script(j) for j in jsonld],
        "meta_description": t(lang, "pref_lede", pref=prefecture, n=data["n"]),
    })


@router.get("/category/{cslug}", response_class=HTMLResponse)
def category_page(request: Request, cslug: str):
    lang = SITE_LANG
    ja_cat = resolve_category(lang, cslug)
    if ja_cat and queries.is_prefecture(ja_cat):
        return _prefecture_page(request, lang, cslug, ja_cat)
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


# /blog was the path for about an hour, with nothing published on it. The
# redirect costs one route and means a link written during that hour still works.
@router.get("/blog", include_in_schema=False)
@router.get("/blog/{slug:path}", include_in_schema=False)
def blog_moved(slug: str = ""):
    target = f"/column/{quote(slug)}" if slug else "/column"
    return RedirectResponse(target, status_code=301)


@router.get("/column", response_class=HTMLResponse)
def column_index(request: Request):
    """Posts written in WordPress, rendered here.

    An empty list is a normal answer, not an error: the store is a volume that
    may not have mounted, or nothing has been published yet.
    """
    lang = SITE_LANG
    posts = blog_store.recent(limit=30)
    url = seo.base_url(lang) + "/column"
    crumbs = [(t(lang, "home"), seo.base_url(lang) + "/"), (t(lang, "blog_title"), None)]
    return _render(request, "column.html", lang, {
        "posts": posts,
        "canonical": url,
        "crumbs": crumbs,
        "jsonld": [seo.jsonld_script(seo.breadcrumbs_jsonld(crumbs))],
        "meta_description": t(lang, "blog_lede"),
    })


@router.get("/column/{slug}", response_class=HTMLResponse)
def column_post(request: Request, slug: str):
    lang = SITE_LANG
    post = blog_store.by_slug(slug)
    if not post:
        raise HTTPException(status_code=404, detail="Not found")
    url = seo.base_url(lang) + f"/column/{quote(slug)}"
    crumbs = [(t(lang, "home"), seo.base_url(lang) + "/"),
              (t(lang, "blog_title"), seo.base_url(lang) + "/column"),
              (post["title"], None)]
    jsonld = [
        seo.breadcrumbs_jsonld(crumbs),
        seo.article_jsonld(lang, post, url),
    ]
    return _render(request, "column_post.html", lang, {
        "post": post,
        "canonical": url,
        "crumbs": crumbs,
        "jsonld": [seo.jsonld_script(j) for j in jsonld],
        "meta_description": post.get("excerpt") or post["title"],
    })


@router.get("/api", response_class=HTMLResponse)
def api_page(request: Request):
    """A written contract for the endpoints meant to be public.

    /docs used to answer 200 to anyone and describe every internal route, which
    is a schema dump rather than a contract. This lists the handful that are
    stable, says what they cost and what may be done with the answers, and
    leaves the rest of the app unadvertised.
    """
    lang = SITE_LANG
    base = seo.base_url(lang)
    endpoints = [
        {
            "method": "GET", "path": "/api/search",
            "summary": t(lang, "api_ep_search"),
            "params": [("q", t(lang, "api_p_q")), ("lang", t(lang, "api_p_lang")),
                       ("limit", t(lang, "api_p_limit"))],
            "example": f"curl '{base}/api/search?q=さば&lang=ja&limit=5'",
            "note": None,
        },
        {
            "method": "GET", "path": "/api/foods/{id}/nutrition",
            "summary": t(lang, "api_ep_nutrition"),
            "params": [("id", t(lang, "api_p_id"))],
            "example": f"curl '{base}/api/foods/1/nutrition'",
            "note": t(lang, "api_ep_nutrition_note"),
        },
        {
            "method": "GET", "path": "/api/cooking-yield",
            "summary": t(lang, "api_ep_yield"),
            "params": [("q", t(lang, "api_p_q")), ("lang", t(lang, "api_p_lang")),
                       ("limit", t(lang, "api_p_limit"))],
            "example": f"curl '{base}/api/cooking-yield?q=もも 皮つき&lang=ja'",
            "note": t(lang, "api_ep_yield_note"),
        },
        {
            "method": "GET", "path": "/api/foods/{id}/cooking-yield",
            "summary": t(lang, "api_ep_yield_item"),
            "params": [("id", t(lang, "api_p_id"))],
            "example": f"curl '{base}/api/foods/1/cooking-yield'",
            "note": None,
        },
        {
            "method": "POST", "path": "/api/analyze-dish",
            "summary": t(lang, "api_ep_dish"),
            "params": [("dish", t(lang, "api_p_dish")), ("shop", t(lang, "api_p_shop")),
                       ("lang", t(lang, "api_p_lang"))],
            "example": f"curl -X POST '{base}/api/analyze-dish?dish=親子丼&lang=ja'",
            "note": t(lang, "api_ep_estimate_note"),
        },
        {
            "method": "POST", "path": "/api/meal-analyzer",
            "summary": t(lang, "api_ep_photo"),
            "params": [("image", t(lang, "api_p_image")), ("lang", t(lang, "api_p_lang"))],
            "example": (f"curl -X POST '{base}/api/meal-analyzer?lang=ja' \
"
                        f"     -F 'image=@lunch.jpg'"),
            "note": t(lang, "api_ep_estimate_note"),
        },
    ]
    url = base + "/api"
    crumbs = [(t(lang, "home"), base + "/"), (t(lang, "api_title"), None)]
    return _render(request, "api.html", lang, {
        "endpoints": endpoints,
        "rate_limit": analyzer_limits()[0],
        "rate_window": analyzer_limits()[1],
        "canonical": url,
        "crumbs": crumbs,
        "jsonld": [seo.jsonld_script(seo.breadcrumbs_jsonld(crumbs))],
        "meta_description": t(lang, "api_lede"),
    })


def analyzer_limits():
    """The live rate limit, read from the analyzer rather than restated here —
    a documented number that drifts from the enforced one is worse than none."""
    from ..api import analyzer
    return analyzer.RATE_LIMIT, analyzer.RATE_WINDOW


@router.get("/cooking-yield", response_class=HTMLResponse)
def cooking_yield_page(request: Request):
    """Every published 重量変化率, and a converter over them.

    A recipe is written in raw weights and a composition table in cooked ones.
    The rate between them is published for 497 foods and was reachable only as
    one column on one food page at a time.
    """
    lang = SITE_LANG
    rows = queries.cooking_yields(lang)
    url = seo.base_url(lang) + "/cooking-yield"
    crumbs = [(t(lang, "home"), seo.base_url(lang) + "/"), (t(lang, "yield_title"), None)]
    return _render(request, "cooking_yield.html", lang, {
        "rows": rows,
        "canonical": url,
        "crumbs": crumbs,
        "jsonld": [seo.jsonld_script(seo.breadcrumbs_jsonld(crumbs))],
        "meta_description": t(lang, "yield_lede"),
        "embed_offer": yield_snippets(),
    })


@router.get("/nutrients", response_class=HTMLResponse)
def nutrients_index(request: Request):
    """Every nutrient that has a ranking page, grouped as the tables group them."""
    lang = SITE_LANG
    summary = queries.nutrient_index(lang, [c for c, *_ in nutrient_pages.NUTRIENTS])
    entries = []
    for code, slug, term, _blurb in nutrient_pages.NUTRIENTS:
        stats = summary.get(code)
        if not stats or not stats.get("n_foods"):
            continue
        entries.append({
            "slug": slug, "term": term, "code": code,
            "n": stats["n_foods"], "top": stats["top"], "unit": stats["unit"],
            "top_name": stats["name"], "top_slug": stats["slug"],
        })

    # Grouped by the same scheme the food pages use, so a reader who has seen
    # one table recognises the shape of the other.
    grouped, seen = [], set()
    for key in nutrient_groups.ORDER:
        label = nutrient_groups.LABELS[key][lang]
        rows = [e for e in entries if nutrient_groups.group_of(e["code"]) == key]
        if rows:
            grouped.append((label, rows))
            seen.update(e["slug"] for e in rows)
    rest = [e for e in entries if e["slug"] not in seen]
    if rest:
        grouped.append((t(lang, "other_nutrients"), rest))

    url = seo.base_url(lang) + "/nutrients"
    crumbs = [(t(lang, "home"), seo.base_url(lang) + "/"), (t(lang, "nutrients_index"), None)]
    return _render(request, "nutrients.html", lang, {
        "groups": grouped,
        "canonical": url,
        "crumbs": crumbs,
        "jsonld": [seo.jsonld_script(seo.breadcrumbs_jsonld(crumbs))],
        "meta_description": t(lang, "nutrients_index_lede"),
    })


@router.get("/nutrient/{slug}", response_class=HTMLResponse)
def nutrient_page(request: Request, slug: str):
    """Foods holding the most of one component, measured values only."""
    lang = SITE_LANG
    spec = nutrient_pages.get(slug)
    if not spec:
        raise HTTPException(status_code=404, detail="Not found")
    code, _slug, term, blurb = spec
    stats = queries.nutrient_corpus_stats(lang, code)
    if not stats or not stats.get("n"):
        raise HTTPException(status_code=404, detail="Not found")
    rows = queries.nutrient_ranking(lang, code, limit=60)
    # The corpus-wide top is usually a seasoning or something dried. Per
    # category answers the question a person planning a meal is asking.
    leaders = queries.nutrient_category_leaders(lang, code)

    heading = nutrient_pages.title(term, lang)
    url = seo.base_url(lang) + f"/nutrient/{slug}"
    crumbs = [(t(lang, "home"), seo.base_url(lang) + "/"),
              (t(lang, "nutrients_index"), seo.base_url(lang) + "/nutrients"),
              (term, None)]
    siblings = [(sl, tm) for _c, sl, tm, _b in nutrient_pages.NUTRIENTS if sl != slug][:14]
    jsonld = [
        seo.breadcrumbs_jsonld(crumbs),
        seo.ranking_jsonld(lang, heading, url, rows),
    ]
    return _render(request, "nutrient.html", lang, {
        "term": term, "heading": heading, "blurb": blurb,
        "rows": rows, "stats": stats, "siblings": siblings, "leaders": leaders,
        "canonical": url,
        "crumbs": crumbs,
        "jsonld": [seo.jsonld_script(j) for j in jsonld],
        "meta_description": blurb,
        "embed_offer": nutrient_snippets(slug, heading),
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


# --- embeds -------------------------------------------------------------------
# Each widget is a duplicate of a page that already exists, so it is noindex and
# canonical to that page, and it must never compete with it in search. The link
# that earns anything is the one the snippet puts OUTSIDE the frame (embeds.py).
# A widget is only offered for a page that is itself indexable: a citation that
# points at a noindex page is a link to nowhere.

def _embed(request, name, canonical, ctx):
    return _render(request, name, SITE_LANG, dict(
        ctx, canonical=canonical, seo_base=seo.base_url(SITE_LANG)), headers=EMBED_CACHE)


def _food_for_embed(slug):
    page = _page_or_404("food", slug)
    data = queries.get_food_page_data(page)
    if not page.get("indexable") or not data["nutrition"]:
        raise HTTPException(status_code=404, detail="Not found")
    return data, queries.display_name(data["names"], data["item"], SITE_LANG)


# by -> (URL suffix, heading key, the field ranked)
MENU_LISTS = {"kcal": ("", "embed_menu_heading", "kcal"),
              "protein": ("/protein", "embed_protein_heading", "protein_g")}


def menu_ranked(menu, by="kcal"):
    """A chain's top ten — lowest calories first, or most protein first —
    ranked only on figures the chain itself published.

    Sorting by an estimate floats its worst errors to the top: ranked on ours,
    ガスト's チキンのトマト煮込み came out at 30 kcal. And a composition-table
    figure is per 100 g, which cannot be ranked against a whole dish.
    """
    field = MENU_LISTS[by][2]
    return sorted((m for m in menu if m.get(field) is not None and m["kcal_source"] == "chain"
                   and not menuterms.is_extra(menuterms.unqualified(m["name"]))),
                  key=lambda m: m[field], reverse=(by == "protein"))[:10]


def _menu_for_embed(slug, by="kcal"):
    page = queries.get_shop_page(SITE_LANG, slug)
    if not page or not page.get("indexable"):
        raise HTTPException(status_code=404, detail="Not found")
    data = queries.get_shop_page_data(page)
    items = menu_ranked(data["menu"], by)
    if not items:
        raise HTTPException(status_code=404, detail="Not found")
    return page, data["shop"].get("name", slug), items


@lru_cache(maxsize=1)
def embed_chains():
    """(slug, name, lists) for every chain a list can be built for.

    ponytail: computed once per process — about 2 s over the 11 indexable
    chains, and the database only changes with a new image. If it ever changes
    under a running server, drop the cache.
    """
    out = []
    for shop in queries.shops_index(SITE_LANG):
        page = queries.get_shop_page(SITE_LANG, shop["slug"]) if shop.get("indexable") else None
        if not page or not page.get("indexable"):
            continue
        menu = queries.get_shop_page_data(page)["menu"]
        lists = tuple(by for by in MENU_LISTS if menu_ranked(menu, by))
        if lists:
            out.append((page["slug"], shop["name"], lists))
    return tuple(out)


# The height each frame starts at, measured at a 680 px blog column with the
# disclaimer in. The widget corrects it once loaded; starting close keeps the host
# page from jumping, which is also what its own Core Web Vitals score measures.
EMBED_HEIGHT = {"analyzer": 190, "food": 790, "compare": 540, "nutrient": 800,
                "menu_kcal": 760, "menu_protein": 960, "yield": 470}


def _iframe_code(path, height, title, links):
    return (t(SITE_LANG, "embed_kind_iframe"), embeds.iframe(path, height, title, links))


def food_snippets(slug, data, name):
    url = seo.page_url(SITE_LANG, "food", slug)
    return [_iframe_code(f"/embed/food/{quote(slug)}", EMBED_HEIGHT["food"], name, [(url, name)]),
            (t(SITE_LANG, "embed_kind_html"), embeds.food_table(data, name, url))]


def compare_snippets(a, a_name, b, b_name):
    heading = t(SITE_LANG, "embed_compare_heading", a=a_name, b=b_name)
    links = [(seo.page_url(SITE_LANG, "food", a), a_name), (seo.page_url(SITE_LANG, "food", b), b_name)]
    return [_iframe_code(f"/embed/compare/{quote(a)}/{quote(b)}", EMBED_HEIGHT["compare"], heading, links)]


def nutrient_snippets(slug, heading):
    url = seo.base_url(SITE_LANG) + f"/nutrient/{slug}"
    return [_iframe_code(f"/embed/nutrient/{slug}", EMBED_HEIGHT["nutrient"], heading, [(url, heading)])]


def menu_snippets(page_slug, shop_name, lists):
    """One code per list the chain can support, each headed by what it ranks."""
    url = seo.base_url(SITE_LANG) + f"/menu/{quote(page_slug)}"
    out = []
    for by in lists:
        suffix, key, _field = MENU_LISTS[by]
        heading = t(SITE_LANG, key, chain=shop_name)
        out.append((heading, embeds.iframe(f"/embed/menu/{quote(page_slug)}{suffix}",
                                           EMBED_HEIGHT["menu_" + by], heading, [(url, heading)])))
    return out


def yield_snippets():
    title = t(SITE_LANG, "yield_calc_title")
    return [_iframe_code("/embed/cooking-yield", EMBED_HEIGHT["yield"], title,
                         [(seo.base_url(SITE_LANG) + "/cooking-yield", title)])]


@router.get("/embed/analyzer", response_class=HTMLResponse)
def embed_analyzer(request: Request):
    """The analyzer alone, for an iframe on someone else's page."""
    return _embed(request, "embed_analyzer.html", seo.base_url(SITE_LANG) + "/analyzer", {})


@router.get("/embed/food/{slug}", response_class=HTMLResponse)
def embed_food(request: Request, slug: str):
    """One food's calories and macros, per 100 g and per serving."""
    data, name = _food_for_embed(slug)
    return _embed(request, "embed_food.html", seo.page_url(SITE_LANG, "food", slug),
                  {"d": data, "name": name, "rows": embeds.food_rows(data)})


@router.get("/embed/compare/{a}/{b}", response_class=HTMLResponse)
def embed_compare(request: Request, a: str, b: str):
    """Two foods side by side, per 100 g. Canonical to the first; the snippet
    cites both."""
    if a == b:
        raise HTTPException(status_code=404, detail="Not found")
    (da, na), (db, nb) = _food_for_embed(a), _food_for_embed(b)
    return _embed(request, "embed_compare.html", seo.page_url(SITE_LANG, "food", a), {
        "foods": [(da, na), (db, nb)], "rows": embeds.compare_rows(da, db),
        "heading": t(SITE_LANG, "embed_compare_heading", a=na, b=nb)})


@router.get("/embed/nutrient/{slug}", response_class=HTMLResponse)
def embed_nutrient(request: Request, slug: str):
    """The top ten of one nutrient ranking, measured values only."""
    spec = nutrient_pages.get(slug)
    if not spec:
        raise HTTPException(status_code=404, detail="Not found")
    code, _slug, term, _blurb = spec
    rows = queries.nutrient_ranking(SITE_LANG, code, limit=10)
    if not rows:
        raise HTTPException(status_code=404, detail="Not found")
    return _embed(request, "embed_nutrient.html", seo.base_url(SITE_LANG) + f"/nutrient/{slug}",
                  {"rows": rows, "term": term, "heading": nutrient_pages.title(term, SITE_LANG)})


def _embed_menu(request, slug, by):
    page, shop_name, items = _menu_for_embed(slug, by)
    return _embed(request, "embed_menu.html", seo.base_url(SITE_LANG) + f"/menu/{quote(page['slug'])}",
                  {"heading": t(SITE_LANG, MENU_LISTS[by][1], chain=shop_name), "items": items, "by": by})


@router.get("/embed/menu/{slug}", response_class=HTMLResponse)
def embed_menu(request: Request, slug: str):
    """A chain's ten lowest-calorie dishes, on the figures it published."""
    return _embed_menu(request, slug, "kcal")


@router.get("/embed/menu/{slug}/protein", response_class=HTMLResponse)
def embed_menu_protein(request: Request, slug: str):
    """A chain's ten highest-protein dishes, for the chains that publish protein."""
    return _embed_menu(request, slug, "protein")


@router.get("/embed/cooking-yield", response_class=HTMLResponse)
def embed_cooking_yield(request: Request):
    """The raw ⇄ cooked converter, without the 497-row table under it."""
    return _embed(request, "embed_cooking_yield.html", seo.base_url(SITE_LANG) + "/cooking-yield",
                  {"rows": queries.cooking_yields(SITE_LANG)})


# What /embed shows before anyone picks anything. Real pages, so each preview
# is the actual widget.
EXAMPLE_FOOD, EXAMPLE_COMPARE = "にわとり-若どり-むね-皮なし-生", "にわとり-若どり-もも-皮なし-生"
EXAMPLE_NUTRIENT, EXAMPLE_CHAIN = "protein", "モスバーガー"


def _pick_food(slug, q, default):
    """(slug, data, name) for a picker: the food chosen, else the first food the
    typed text finds, else the default. Text typed over a chosen food without
    JavaScript — the hidden slug still holds the old one — goes by the text."""
    q = (q or "").strip()
    found = [r["slug"] for r in queries.search(q, SITE_LANG, limit=10)
             if r["page_type"] == "food"] if q else []
    for cand in ([slug] if slug else []) + found + [default]:
        try:
            data, name = _food_for_embed(cand)
        except HTTPException:
            continue
        if cand == slug and q and q != name and found:
            continue
        return cand, data, name
    raise HTTPException(status_code=404, detail="Not found")


def _section(key, title, note, codes, previews=(), **extra):
    return dict(key=key, title=title, note=note, codes=codes, previews=list(previews), **extra)


@router.get("/embed", response_class=HTMLResponse)
def embed_index(request: Request, food: str = "", food_q: str = "", a: str = "", a_q: str = "",
                b: str = "", b_q: str = "", nutrient: str = "", chain: str = "", rank: str = ""):
    """Every widget, its code and a live preview — and for the ones that are not
    tied to a single page, a picker that builds the code for any food, pair of
    foods, nutrient or chain."""
    lang = SITE_LANG
    base = seo.base_url(lang)
    analyzer = t(lang, "ai_analyzer")
    sections = [_section("analyzer", t(lang, "embed_analyzer_title"), t(lang, "embed_analyzer_note"),
                         [_iframe_code("/embed/analyzer", EMBED_HEIGHT["analyzer"], analyzer,
                                       [(base + "/analyzer", analyzer)])],
                         [("/embed/analyzer", EMBED_HEIGHT["analyzer"], analyzer)])]
    try:
        fs, fd, fn = _pick_food(food, food_q, EXAMPLE_FOOD)
        sections.append(_section(
            "food", t(lang, "embed_food_title"), t(lang, "embed_food_note"), food_snippets(fs, fd, fn),
            [(f"/embed/food/{quote(fs)}", EMBED_HEIGHT["food"], fn)],
            builder="food", picks={"food": (fs, fn)}))
        as_, _ad, an = _pick_food(a, a_q, EXAMPLE_FOOD)
        bs, _bd, bn = _pick_food(b, b_q, EXAMPLE_COMPARE if as_ != EXAMPLE_COMPARE else EXAMPLE_FOOD)
        if bs == as_:
            bs, _bd, bn = _pick_food("", "", EXAMPLE_COMPARE if as_ != EXAMPLE_COMPARE else EXAMPLE_FOOD)
        heading = t(lang, "embed_compare_heading", a=an, b=bn)
        sections.append(_section(
            "compare", t(lang, "embed_compare_title"), t(lang, "embed_compare_note"),
            compare_snippets(as_, an, bs, bn),
            [(f"/embed/compare/{quote(as_)}/{quote(bs)}", EMBED_HEIGHT["compare"], heading)],
            builder="compare", picks={"a": (as_, an), "b": (bs, bn)}))
    except HTTPException:
        pass    # the example foods left the tables; their sections go with them

    summary = queries.nutrient_index(lang, [c for c, *_ in nutrient_pages.NUTRIENTS])
    nutrients = [(sl, tm) for c, sl, tm, _b in nutrient_pages.NUTRIENTS
                 if (summary.get(c) or {}).get("n_foods")]
    ns = nutrient if nutrient in dict(nutrients) else EXAMPLE_NUTRIENT
    if ns in dict(nutrients):
        heading = nutrient_pages.title(dict(nutrients)[ns], lang)
        sections.append(_section(
            "nutrient", t(lang, "embed_nutrient_title"), t(lang, "embed_nutrient_note"),
            nutrient_snippets(ns, heading), [(f"/embed/nutrient/{ns}", EMBED_HEIGHT["nutrient"], heading)],
            builder="nutrient", options=nutrients, chosen=ns))

    chains = {slug: (name, lists) for slug, name, lists in embed_chains()}
    cs = chain if chain in chains else EXAMPLE_CHAIN if EXAMPLE_CHAIN in chains else next(iter(chains), None)
    if cs:
        name, lists = chains[cs]
        wanted = rank if rank in MENU_LISTS else "kcal"
        # Before anyone chooses, show every list the example supports; after,
        # just the one chosen (or what the chain can support instead).
        shown = ((wanted,) if wanted in lists else lists[:1]) if (chain or rank) else lists
        codes = menu_snippets(cs, name, shown)
        suffix = {by: MENU_LISTS[by][0] for by in shown}
        sections.append(_section(
            "menu", t(lang, "embed_menu_title"), t(lang, "embed_menu_note_index"), codes,
            [(f"/embed/menu/{quote(cs)}{suffix[by]}", EMBED_HEIGHT["menu_" + by], heading)
             for by, (heading, _code) in zip(shown, codes)],
            builder="menu", options=[(s, n, ls) for s, (n, ls) in chains.items()], chosen=cs,
            chosen_list=wanted,
            notice=t(lang, "embed_protein_missing", chain=name) if wanted not in lists else None))

    sections.append(_section("yield", t(lang, "yield_calc_title"), t(lang, "embed_yield_note"),
                             yield_snippets(),
                             [("/embed/cooking-yield", EMBED_HEIGHT["yield"], t(lang, "yield_calc_title"))]))
    sections.append(_section("search", t(lang, "embed_search_title"), t(lang, "embed_search_note"),
                             [(t(lang, "embed_kind_html"), embeds.search_box())], live_html=True))
    crumbs = [(t(lang, "home"), base + "/"), (t(lang, "embed_title"), None)]
    chose = any((food, food_q, a, a_q, b, b_q, nutrient, chain, rank))
    return _render(request, "embed.html", lang, {
        "seo_base": base,
        "sections": sections,
        "rate_limit": analyzer_limits()[0],
        "canonical": base + "/embed",
        # Every picked combination is the same page with other examples in it.
        "noindex": chose,
        "crumbs": crumbs,
        "jsonld": [seo.jsonld_script(seo.breadcrumbs_jsonld(crumbs))],
        "meta_description": t(lang, "embed_lede"),
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
# The site operates under its own name. Defaulted here rather than left to an
# environment variable nobody set: the about page read 運営者: 未掲載, which on a
# Japanese site publishing nutrition information reads as an omission rather
# than a choice. SITE_OPERATOR still overrides it if a company is ever named.
SITE_OPERATOR = os.environ.get("SITE_OPERATOR", "").strip() or SITE_NAME[SITE_LANG]
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "").strip()
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


@router.get("/terms", response_class=HTMLResponse)
def terms_page(request: Request):
    """What the figures are, and whose the names and marks are.

    A site that lists other companies' menus uses their names to say whose menu
    it is. That is what this page states plainly, along with the standing offer
    to remove a mark on request — which costs nothing and is the difference
    between a dispute and an email.
    """
    lang = SITE_LANG
    return _standing_page(request, lang, "terms", {"updated": POLICY_UPDATED})


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
    for lang in LANGS:
        for section in queries.SITEMAP_SECTIONS:
            body.append(
                f"<sitemap><loc>{seo.base_url(lang)}/sitemap-{section}-{lang}.xml</loc></sitemap>")
    body.append("</sitemapindex>")
    return Response("\n".join(body), media_type="application/xml", headers=CACHE)


@router.get("/sitemap-{section}-{lang}.xml")
def sitemap_section(section: str, lang: str):
    """Generated from the database on request.

    These used to be files written by build-sitemaps into data/sitemaps/, and
    data/ is not in the repository — so the deployed site advertised an empty
    sitemap index while holding 4,072 indexable pages.
    """
    if lang not in LANGS or section not in queries.SITEMAP_SECTIONS:
        raise HTTPException(status_code=404, detail="Not found")
    paths = queries.sitemap_slugs(lang, section)
    body = ['<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    base = seo.base_url(lang)
    for path in paths:
        body.append(f"<url><loc>{base}{quote(path)}</loc></url>")
    body.append("</urlset>")
    return Response("\n".join(body), media_type="application/xml", headers=CACHE)
