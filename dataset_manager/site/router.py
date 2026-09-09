"""Public HTML site: pages at the root, robots.txt, sitemaps."""
import hashlib
import os
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from . import (cards, faq, groups, media, nutrient_groups, nutrient_pages,
               queries, seo)
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
# stale page while editing one is worse than a slow one. Railway always injects
# RAILWAY_ENVIRONMENT, so a deployment can tell itself apart from a laptop
# without anyone having to remember a variable; SITE_CACHE_MAX_AGE still wins
# when it is set, including `0` to switch caching off in production.
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
    return _render(request, "home.html", lang, {
        "data": data,
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
    })



@router.get("/favicon.ico", include_in_schema=False)
def favicon():
    """Silence 404s for browsers probing default favicon.ico."""
    return Response(status_code=204)




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
        "rows": rows, "stats": stats, "siblings": siblings,
        "canonical": url,
        "crumbs": crumbs,
        "jsonld": [seo.jsonld_script(j) for j in jsonld],
        "meta_description": blurb,
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


@router.get("/embed/analyzer", response_class=HTMLResponse)
def embed_analyzer(request: Request):
    """The analyzer alone, for an iframe on someone else's page.

    noindex and canonical to /analyzer: an embed is a duplicate of a page that
    already exists, and it must not compete with it in search.
    """
    lang = SITE_LANG
    return _render(request, "embed_analyzer.html", lang, {
        "seo_base": seo.base_url(lang),
    }, headers=EMBED_CACHE)


@router.get("/embed", response_class=HTMLResponse)
def embed_index(request: Request):
    """The snippet to copy, and what it does."""
    lang = SITE_LANG
    base = seo.base_url(lang)
    url = base + "/embed"
    crumbs = [(t(lang, "home"), base + "/"), (t(lang, "embed_title"), None)]
    return _render(request, "embed.html", lang, {
        "seo_base": base,
        "rate_limit": analyzer_limits()[0],
        "canonical": url,
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
