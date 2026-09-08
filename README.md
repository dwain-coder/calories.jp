# calories.jp

A Japanese food calorie and nutrition site built on official composition data.
Every number shown to a reader comes from a measured government table and is
labelled with where it came from. Nothing on the site is an LLM's guess at a
nutrition value.

- **2,633 food pages** from the MEXT Standard Tables of Food Composition (2023),
  with all 51 measured nutrients, a serving calculator and %DV that rescale
  together, and a preparation comparison — 299 foods appear in the tables in
  more than one state (生 / ゆで / 焼き / 乾), so the effect of cooking is
  analysed rather than estimated.
- **1,364 regional dish pages** from MAFF's うちの郷土料理, with ingredients,
  method and provenance. Nutrition is computed only where enough ingredients
  resolve to composition-table entries.
- **65 category pages**, a paginated browse, FTS5 trigram search (essential for
  Japanese substring matching), a meal calculator, a goal calculator, and a
  photo analyzer that separates database values from AI-estimated portions.

## Stack

FastAPI serves both a JSON API and the server-rendered public site (Jinja2).
SQLite holds the corpus. The frontend for the public site is vanilla JS — the
calculators are deterministic arithmetic mirrored from tested Python in
`dataset_manager/calc/`. `frontend/` is a separate React app used internally to
browse the raw corpus; it is not the public site.

```
dataset_manager/
  downloaders/ transformers/   ingest pipeline, one module per source
  site/                        public site: router, queries, SEO, i18n, display names
  calc/                        deterministic nutrition + quantity parsing
  api/                         JSON API, search, meal analyzer
  scripts/build_site.py        offline builders (names, pages, search, sitemaps)
templates/  static/  tests/  tools/
```

## Running it

```bash
uv sync
cp .env.example .env          # GEMINI_API_KEY is only needed by the analyzer
uv run python main.py serve   # http://localhost:8000/ja/
uv run python -m unittest discover tests
```

The database is not in the repo (see below). Build it with the pipeline
(`main.py --help` lists the ingest commands), then:

```bash
uv run python main.py build-site
```

## Deploying

The repo carries `data/metadata/site.db` (18 MB): the rows the site actually
serves, with OpenFoodFacts and Wikipedia removed. Rebuild it from a full corpus
with `uv run python tools/export_site_db.py`. The Dockerfile ships it and
defaults `DATABASE_PATH` to it, so a container host needs no volume.

Environment:

| Variable | Purpose |
|---|---|
| `PORT` | Injected by most hosts; `serve` binds it, falling back to 8000 |
| `DATABASE_PATH` | Defaults to the extract in the image; point it at a volume for the full corpus |
| `SITE_DOMAIN_JA` | The public hostname. Canonical URLs, hreflang, robots and sitemaps all derive from it, and default to localhost when it is unset — set it before letting a crawler in |
| `GEMINI_API_KEY` | Only the meal analyzer needs it; the rest of the site works without |
| `SITE_CACHE_MAX_AGE` | Page cache seconds; unset means no-cache, which suits development |
| `SITE_NOINDEX` | `1` while the site sits on a temporary hostname: robots.txt refuses everything and every page carries a noindex tag |

Sitemaps hold absolute URLs, so re-run `build-sitemaps` after the domain
changes. The analyzer caches results in the database, which on an ephemeral
container filesystem means the cache resets on redeploy — correct behaviour,
just slower on the first request for a given photo.

## Chain menus

`/shops/{chain}` puts a chain's menu price and its calorie side by side — the one
thing the calorie aggregators do not show. The prices come from a dated menu
snapshot; **the calories are the chain's own published figures**, never ours and
never a model's.

A composition table cannot cost a composed restaurant dish: matching a menu name
against MEXT resolves it to an ingredient of the dish, which in an audit produced
a cheeseburger costed as cheese and a champagne as French bread. So MEXT is used
only to link a dish to its food page (`match_method = 'name-equal'`, exact names
only), and the figure itself comes from the chain.

```bash
uv run python main.py import-menus data/raw/menus/menu-items.ja.csv
uv run python main.py match-menus --no-llm     # interlinks only, spends nothing
uv run python main.py import-chain-nutrition all
uv run python main.py build-shops              # slugs, titles, index gate
uv run python main.py build-shops --report
```

**Attribution is structural.** A calorie is only carried out of `get_shop_page_data`
together with the source it came from, so a template cannot print a number without
one, and every page shows the chain's own update date and its 「目安」 wording with
a link to the official page. A dish the chain has not published shows 未公表.

**Keeping figures honest.** Chains revise monthly. `import-chain-nutrition` is the
refresh — it is idempotent, and on a re-run it reports what moved (added, withdrawn,
and every revised figure with its old and new value) rather than overwriting in
silence. `chain-status` shows how stale each chain is:

```bash
uv run python main.py chain-status --stale-after 30
```

Refreshing a live site is a full loop, because the database ships inside the image:

```bash
uv run python main.py import-chain-nutrition all && uv run python main.py build-shops
uv run python tools/export_site_db.py       # rebuild the deployable extract
git add data/metadata/site.db && git commit && git push    # host redeploys
```

**A shop page earns its index slot.** `shop_pages.indexable` defaults to 0 and is
set by `build-shops` only when a menu has at least 15 dishes, a real price, and at
least 40% of dishes carrying a sourced calorie. Pages that fail still render and
still link onward, but carry `noindex, follow` and stay out of the sitemap — a menu
reprint with no added fact is what got a competitor's menu pages deindexed.

Adding a chain is a `Chain` entry in `dataset_manager/extractors/chains.py`. Check
the chain's `robots.txt` first: some publishers disallow the paths their nutrition
data sits on, and those chains are off the table until they say otherwise.

## Data, licences and what is not here

`data/` is gitignored. That is partly size — the OpenFoodFacts export alone is
6 GB — and partly licence.

| Source | Licence | Obligation |
|---|---|---|
| MEXT Standard Tables of Food Composition | Government Standard Terms of Use | Attribution required; commercial use permitted |
| MAFF うちの郷土料理 | Government Standard Terms of Use | Attribution required; commercial use permitted |
| USDA FoodData Central, FoodKeeper | CC0 | None |
| Wikidata | CC0 | None |
| Wikipedia | CC BY-SA 4.0 | Attribution + ShareAlike |
| OpenFoodFacts | ODbL 1.0 | Share-alike on derivative databases |

**OpenFoodFacts is quarantined.** It is ingested for internal comparison only
and is structurally excluded from every published surface: public pages are
reachable only through the `site_pages` table, which is never populated for
those rows, and a test asserts that an OpenFoodFacts item 404s on the public
API. It must not enter the clean corpus, an export, or the site. Wikipedia is
excluded from the site for the same reason — CC BY-SA would infect the pages.

Stock photography and video on the landing pages come from Pexels. They never
appear on a food, dish or category page, and a test enforces that: a photograph
next to an exact measurement implies it depicts that exact entry, and no stock
library can honestly do that. Data pages carry generated imagery instead — a
nutrient fingerprint and an energy ring drawn from the food's own numbers.
