# calories.jp

A Japanese food calorie and nutrition site built on official composition data.
Every number shown to a reader carries where it came from, and the site would
rather show nothing than show a figure it cannot stand behind. No LLM ever
produces a nutrition value.

## What is on the site

| Surface | Count | What it is |
|---|---|---|
| `/food/{slug}` | 2,633 | MEXT Standard Tables of Food Composition (2023), 173 component codes, 257,235 measured values |
| `/dish/{slug}` | 1,364 | MAFF うちの郷土料理 — ingredients, method, provenance |
| `/menu/{slug}` | 193 | Chain restaurant menus, 17,876 items with prices |
| `/nutrient/{slug}` | 42 | Foods ranked by one component, and the top food in each food group |
| `/category/{slug}` | 65 | MEXT food groups |
| `/atlas` | — | Every food plotted by the share of its energy from protein, fat and carbohydrate |
| `/cooking-yield` | 497 | MEXT's 重量変化率, with a two-way raw ⇄ cooked converter |
| `/analyzer` | — | Photograph → dishes → ingredients → composition-table rows |
| `/foods`, `/search` | — | Paginated browse and FTS5 trigram search (needed for Japanese substring matching) |
| `/meal-calculator`, `/goals` | — | Deterministic arithmetic, mirrored from tested Python |
| `/column` | — | Posts written in a headless WordPress, fetched and sanitised |
| `/api` | 6 endpoints | JSON, with provenance per value |

## Where a number comes from

This is the whole design. Every figure on the site sits somewhere on a ladder,
and the page says which rung.

**Food pages** carry MEXT's own measurements. `nutrients.quality` distinguishes
`measured` (172,101 values) from MEXT's own `estimated` (76,436) and `trace`
(8,698), because parentheses in the source mean something and stripping them
turns an estimate into a measurement. Percentile ranks (`/nutrient/*` and the
「上位に入る成分」 block) are computed over **measured values only**, against at
least 20 peers in the same food group — 69,980 ranks over 784 group/nutrient
pairs, precomputed by `build-ranks`.

**Menu pages** prefer, in order:

| Rung | Rows | Shown as |
|---|---|---|
| The chain's own published figure | 1,567 | 店舗公式公表値 |
| A direct composition-table match | 231 | 成分表の値 |
| Our own calculation from the tables | 7,647 | 推計値（成分表による計算） |
| Nothing | 8,431 | 未公表 |

The label is not decorative. It used to say 店舗公式公表値 over any stored
figure, on 6,252 of 9,594 rows; a test now asserts the label maps only to
`chain`. A dish whose macros the chain does not publish shows `—` rather than
borrowing the analyzer's guess.

**Twelve chains publish figures** we import: ガスト, ジョナサン, 夢庵, バーミヤン,
ステーキガスト, から好し, chawan, はま寿司, くら寿司, モスバーガー, リンガーハット,
ビッグボーイ. The すかいらーく brands render their menus from a JSON file the site
fetches; the rest are PDF disclosures. `docs/chain-nutrition-urls.csv` tracks the
33 still wanted.

## The analyzer, and how well it works

A photograph is split into dishes, each dish into ingredients, and each
ingredient matched to a composition-table row that the page links to. The
model never supplies a nutrition value — only a name and a weight, both
labelled as estimates.

It is **measured**, not asserted. 64 photographs of chain meals whose calories
those chains publish live in `data/raw/analyzer_examples/`; `tools/score_analyzer.py`
replays the saved model output through the current matcher and scores it:

```
n=63   median -2%   |error| p50 22%   p90 53%   within ±25%: 36/63
```

That number is on the page. The headline rounds to the nearest 50 and prints
the band beside it — 「約400 kcal / おおよそ300〜500 kcalの範囲です。公表値のある
チェーン店メニュー63件で検証したところ、この推定値の誤差は中央値22%でした」. An
ingredient the tables do not carry contributes nothing, so a total missing one
is shown as `≥` with a count of what is absent.

Three rules the matcher learned the hard way, each with a regression test:

- The tables spell food in kana and a model writes kanji. 牛かた肉, 豚ヒレ肉,
  辛子明太子 all matched nothing while sitting in the corpus as うし, ぶた,
  めんたいこ — a 150 g steak contributing zero took a plate from 290 kcal to 34.
- The model names the state it can see and the search returned the plainest row:
  175 kcal of 赤肉 for a 322 kcal 脂身つき cut, raw cabbage for 油いため.
- 「ソース」 alone means Worcestershire, but as a substring alias it answered
  チーズソース and タルタルソース with Worcestershire too. Named sauces are aliased;
  the rest now miss, which is the honest answer.

Where the menu states a weight — 「ラウンドステーキ(約120g)」 — that weight replaces
the model's guess, upward as well as down. A stated *count* is parsed and
deliberately not applied: the 3 in 「…焼餃子3個・半チャーハン」 belongs to the gyoza.

`tools/collect_benchmark.py` widens the set (1,052 photographs carry a published
figure). Each widening has moved the number and been worth more than any tuning
done against the narrower one.

## Stack

FastAPI serves both the JSON API and the server-rendered site (Jinja2). SQLite
holds the corpus. The public frontend is vanilla JS — the calculators are
deterministic arithmetic mirrored from tested Python in `dataset_manager/calc/`.
`frontend/` is a separate React app for browsing the raw corpus internally; it is
not the public site.

```
dataset_manager/
  downloaders/ transformers/   ingest pipeline, one module per source
  extractors/chains.py         per-chain nutrition importers (PDF, table, JSON)
  site/                        router, queries, SEO, i18n, display names,
                               foodterms (the matcher's vocabulary), brand assets
  calc/                        deterministic nutrition + quantity parsing
  api/                         JSON API, search, meal analyzer
  scripts/                     offline builders: pages, search, ranks, sitemaps,
                               precomputed menu nutrition
templates/  static/  tests/  tools/  docs/
```

## Running it

```bash
uv sync
cp .env.example .env          # GEMINI_API_KEY is only needed by the analyzer
uv run python main.py serve   # http://localhost:8000/
uv run python -m unittest discover tests    # 413 tests
```

The database is not in the repo (see below). Build it with the pipeline
(`main.py --help` lists the ingest commands), then:

```bash
uv run python main.py build-site      # names, pages, links, ranks, search, sitemaps
uv run python main.py precompute-nutrition
```

## Deploying

The repo carries `data/metadata/site.db` (40 MB): the rows the site actually
serves, with OpenFoodFacts and Wikipedia removed. Rebuild it with
`uv run python tools/export_site_db.py`. The Dockerfile ships it and defaults
`DATABASE_PATH` to it, so a container host needs no volume.

```bash
sudo /opt/apps/calories/src/tools/contabo-deploy.sh --apply
```

The deploy script is dry-run by default and checks the two failures this project
has already had: a volume mounted over `/app/data` hiding the database, and a
container that could not import its own modules replacing a working one.

**Purge Cloudflare afterwards.** Pages are served `max-age=3600,
stale-while-revalidate=86400`, so the edge will happily serve an 85-minute-old
copy while fetching the new one behind your back — `cf-cache-status: UPDATING`.
The origin being right is not the same as the site being right.

Environment:

| Variable | Purpose |
|---|---|
| `PORT` | Injected by most hosts; `serve` binds it, falling back to 8000 |
| `DATABASE_PATH` | Defaults to the extract in the image; point it at a volume for the full corpus |
| `SITE_DOMAIN_JA` | The public hostname. Canonical URLs, hreflang, robots and sitemaps all derive from it, and default to localhost when unset — set it before letting a crawler in |
| `GEMINI_API_KEY` | Only the meal analyzer needs it; the rest of the site works without |
| `ANALYZER_RATE_LIMIT` | Analyses per hour per IP, default 12. The only thing between `/api/meal-analyzer` and someone draining the key |
| `SITE_CACHE_MAX_AGE` | Page cache seconds; unset means no-cache, which suits development |
| `SITE_NOINDEX` | `1` while the site sits on a temporary hostname: robots.txt refuses everything and every page carries a noindex tag |
| `WP_URL` | Headless WordPress the column is fetched from |

Sitemaps hold absolute URLs, so re-run `build-sitemaps` after the domain changes.

## Chain menus

`/menu/{slug}` puts a chain's menu price and its calorie side by side — the one
thing the calorie aggregators do not show. Prices come from a dated menu
snapshot; a calorie comes from the ladder above, labelled with its rung.

A composition table cannot cost a composed restaurant dish: matching a menu name
against MEXT resolves it to an ingredient of the dish, which in an audit produced
a cheeseburger costed as cheese and a champagne as French bread. So MEXT links a
dish to its food page (`match_method = 'name-equal'`, exact names only) and the
headline figure comes from the chain wherever the chain publishes one.

```bash
uv run python main.py import-menus data/raw/menus/menu-items.ja.csv
uv run python main.py match-menus --no-llm     # interlinks only, spends nothing
uv run python main.py import-chain-nutrition all
uv run python main.py precompute-nutrition
uv run python main.py build-shops              # slugs, titles, index gate
```

**Attribution is structural.** A calorie is only carried out of
`get_shop_page_data` together with the source it came from, so a template cannot
print a number without one.

**Keeping figures honest.** Chains revise monthly. `import-chain-nutrition` is
idempotent and reports what moved — added, withdrawn, and every revised figure
with its old and new value — rather than overwriting in silence.
`chain-status --stale-after 30` shows how stale each chain is.

**A shop page earns its index slot.** `shop_pages.indexable` defaults to 0 and is
set by `build-shops` only when a menu has at least 15 dishes, a real price, and at
least 40% of dishes carrying a sourced calorie — 11 of 193 pass today. The rest
render and link onward but carry `noindex, follow`. A menu reprint with no added
fact is what got a competitor's menu pages deindexed.

Adding a chain is a `Chain` entry in `dataset_manager/extractors/chains.py`.
There are three shapes to copy: a line-based text parser, a real PDF table, and a
JSON menu feed. Check the chain's `robots.txt` first.

## Images

1,424 dish photographs come from the chain's own menu feed, joined on the exact
dish name, with the page it came from recorded per image. A photograph a chain
uses for two different dishes is dropped: at most one of them is a picture of
that dish, and nothing in the data says which. 27 chains have their real logo;
the rest get a two-character tile, sized from the mark's rendered width so it
cannot spill out of its box.

Stock photography is Pexels (commercial use, no attribution required) and appears
only on landing and tool pages — and on the home page's worked examples, which
are the one deliberate exception, because those pages show what the analyzer made
of that exact photograph. A test enforces the rest: a photograph next to an exact
measurement implies it depicts that exact entry, and no stock library can honestly
do that. Data pages carry generated imagery instead — a nutrient fingerprint and
an energy ring drawn from the food's own numbers.

## Data, licences and what is not here

`data/` is gitignored. That is partly size — the OpenFoodFacts export alone is
6 GB — and partly licence. The exceptions are the deployable extract and
`data/raw/analyzer_examples/`, kept so the figures on the home page and in the
benchmark can be checked against what the API actually returned.

| Source | Licence | Obligation |
|---|---|---|
| MEXT Standard Tables of Food Composition | Government Standard Terms of Use | Attribution required; commercial use permitted |
| MAFF うちの郷土料理 | Government Standard Terms of Use | Attribution required; commercial use permitted |
| Chain nutrition disclosures | Facts about a product, published for the public | Source URL and the chain's own update date on every row |
| USDA FoodData Central, FoodKeeper | CC0 | None |
| Wikidata | CC0 | None |
| Wikimedia Commons (dish photographs) | CC BY-SA | Attribution; recorded per image |
| Pexels (landing pages) | Pexels licence | None |
| Wikipedia | CC BY-SA 4.0 | Attribution + ShareAlike |
| OpenFoodFacts | ODbL 1.0 | Share-alike on derivative databases |

**OpenFoodFacts is quarantined.** It is ingested for internal comparison only and
is structurally excluded from every published surface: public pages are reachable
only through the `site_pages` table, which is never populated for those rows, and
a test asserts that an OpenFoodFacts item 404s on the public API. It must not
enter the clean corpus, an export, or the site. Wikipedia text is excluded for the
same reason — CC BY-SA would infect the pages.

## Measuring instead of asserting

Three tools exist because a claim about the site should be checkable:

```bash
uv run python tools/score_analyzer.py --misses    # the analyzer against published calories
uv run python tools/collect_benchmark.py --plan   # widen that set
uv run python main.py chain-status                # how stale each chain's figures are
```

The 35 test modules are mostly written the same way: each one names the defect it
exists to prevent, with the figures it was found at. `test_menu_modal_honesty.py`
begins with a ¥3,256 roast beef that came out as 3.9 g of protein under a
店舗公式公表値 label; `test_analyzer_matching.py` with a 150 g steak that matched
nothing. Rule one is that nothing on the site may be incorrect, and the tests are
where that is enforced rather than remembered.
