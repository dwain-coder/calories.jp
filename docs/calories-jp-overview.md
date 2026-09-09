# calories.jp — what it is, what's in it, how it works

A complete description of a live Japanese food-and-nutrition site, written to be
handed to another model for a second opinion. Everything below is measured from
the running database, not recalled. Figures are current as of 2026-09-09.

**The question I want answered at the end: given this data and these
constraints, what is worth building on top of it?**

---

## 1. What the site is

calories.jp is a Japanese-language site that answers "how many calories is this,
and where does that number come from". It covers three things:

1. **Foods** — the Japanese national food composition tables, one page per food
2. **Dishes** — traditional regional recipes, costed from their ingredients
3. **Restaurant menus** — chain menus with prices beside calories

Plus tools: a meal calculator, an AI photo analyzer, nutrient rankings, and a
raw↔cooked weight converter.

**The editorial rule the whole thing is built on:** every number on the site can
be traced to a source, and anything estimated says so. An AI-derived figure is
never presented as a measurement. This has repeatedly cost features, and it is
the site's only real differentiator against the many Japanese calorie sites that
publish unsourced numbers.

**Market:** Japan only, Japanese only. No English pages. The acquisition channel
is organic search.

**Business model:** currently none. No ads, no accounts, no payments. The
question of how it earns is open.

---

## 2. The data

### 2.1 Items — 6,473 foods and dishes

| Source | Rows | What it is | Licence |
|---|---|---|---|
| MEXT Standard Tables 2023 (八訂) | 2,538 | Japan's national food composition tables | Government open data |
| MAFF うちの郷土料理 | 1,364 | Regional traditional dishes, all 47 prefectures | Government open data |
| USDA FoodKeeper | 1,226 | Storage life guidance | US public domain |
| USDA FoodData Central | 1,062 | US composition data | US public domain |
| Wikidata (SPARQL) | 283 | Food entities, identifiers | CC0 |

**Quarantined and never served:** ~2.07M OpenFoodFacts products. ODbL
share-alike, so they are excluded from the public site, every export and the
deployed database. Notably, that corpus contains **zero Japanese barcodes**
(prefixes 45x/49x) — checked directly — so the exclusion costs nothing for this
market. Japanese Wikipedia was dropped for the same reason (CC BY-SA).

### 2.2 Nutrient values — 257,235 across 173 distinct components

Every value carries a provenance flag, taken from how MEXT prints it:

| Quality | Rows | Meaning |
|---|---|---|
| `measured` | 172,101 | A plain number in the source |
| `estimated` | 76,436 | Printed in parentheses — MEXT's own estimate |
| `trace` | 8,698 | `Tr` — present but below the reporting threshold |

This averages **101 values per MEXT food** — the full published record,
including the amino acid, fatty acid and available-carbohydrate companion books,
not the six or seven numbers a typical calorie site carries. The 173 components
span macros, minerals, vitamins, individual fatty acids (including DHA and EPA),
individual amino acids, sugars, fibre fractions and organic acids.

The distinction matters downstream: rankings and legal claim checks use
`measured` only, because an estimate cannot settle whether one food holds more
of something than another.

### 2.3 Derived and auxiliary tables

| Table | Rows | What it holds |
|---|---|---|
| `recipe_ingredient_links` | 10,761 | Dish → ingredient, with grams. 8,354 resolve to a composition row, across 1,350 dishes but only **248 distinct ingredients** |
| `regional_dishes` | 1,364 | Per dish: region, main ingredients, history, occasion, how it's eaten, full recipe text (~1.29M characters of MAFF prose) |
| `jdi8_scores` | 3,902 | Japanese Diet Index, 8 components (rice, miso, seaweed, pickles, green-yellow veg, fish, green tea, low meat) |
| `shelf_life` | 1,994 | Storage method + min/max days, from USDA FoodKeeper (US assumptions) |
| `food_portions` | 1,134 | FDC portion descriptions — English only |
| `cooking_yield` | 497 | MEXT 重量変化率: what a food weighs after cooking |
| `item_names` | 8,205 | Names per language, primary-name flag |
| `search_fts` | 3,997 | FTS5 trigram index (substring matching works for Japanese) |

### 2.4 Restaurant menus

| Table | Rows |
|---|---|
| `shops` | 251 menus → **193 businesses** after deduplication |
| `shop_menu_items` | 17,876 dishes with prices |
| `chain_nutrition` | 1,341 figures the chains themselves publish |
| `menu_item_nutrition` | 9,035 figures shown on pages |

The provenance split on what's displayed is the important part:

| Provenance | Rows | What it is |
|---|---|---|
| `chain` | 453 | The chain's own published disclosure — authoritative |
| `table` | 253 | A composition-table row that IS the dish |
| `mext_calc` | 8,329 | Estimated: dish name → standard recipe → composition tables |

**Only 3 of 193 menu pages are indexable.** The gate requires enough dishes
carrying a chain-published or composition-table figure; the tier-3 estimates
don't count toward it. That is deliberate — see §5.

### 2.5 Scale

- 4,121 URLs in the sitemaps: 2,633 food + 1,364 dish + 65 category + 42
  nutrient + 3 shop + 14 static
- 34 MB deployable SQLite extract (from a 623 MB working corpus)
- 13,695 lines of Python, 261 tests

---

## 3. What's built

### Pages
- `/food/{slug}` — 2,633 pages. Serving-size hero, nutrients grouped into
  panels, percentile rank within food group, legal claim callouts, cooked-weight
  conversion, shelf life, FAQ blocks. `NutritionInformation` + `FAQPage` markup.
- `/dish/{slug}` — 1,364 regional dishes. Ingredients costed to composition
  rows, method steps, MAFF's history/occasion/how-it's-eaten prose, per-100 g
  column. `Recipe` + `HowToStep` markup.
- `/category/{prefecture}` — 47 prefecture pages: dishes, sub-regions, and
  **characteristic ingredients** (which ingredients that prefecture's recipes
  use more than the national average — 沖縄県 uses 泡盛 in 2 of the 2 dishes
  nationwide that use it at all).
- `/category/{food-group}` — 18 MEXT groups as comparison tables.
- `/menu` + `/menu/{chain}` — 193 chains, prices beside calories, per-row
  provenance badges, an order tray that totals a meal.
- `/nutrient/{slug}` — 42 curated components ranked over the corpus
  (「DHAが多い食品ランキング」). Measured values only, scope stated on the page.
- `/cooking-yield` — all 497 weight-change rates with a converter.
- `/blog` — posts written in WordPress, rendered by this app (WP is admin-only,
  never publicly served; post HTML is sanitised against an allowlist on ingest).

### Tools
- **Meal calculator** — build a meal from corpus foods, get totals
- **AI photo analyzer** — Gemini vision breaks a meal photo into dishes and
  ingredients, each matched to a composition row; grams are AI-estimated and
  labelled as such, calories are arithmetic on measured values. Implausible
  quantities are flagged rather than silently multiplied in.
- **Public API** — `/api/search`, `/api/foods/{id}/nutrition`,
  `/api/analyze-dish`, `/api/meal-analyzer`. Free, no key, rate-limited on the
  AI endpoints.

### Stack
FastAPI + Jinja2, server-rendered. SQLite (WAL, FTS5 trigram). Deployed on
Railway from a Dockerfile with the 34 MB extract baked into the image; posts live
on a mounted volume. Cloudflare in front. Gemini via litellm for the vision
work. No frontend framework; ~2,400 lines of templates and one hand-written CSS
file.

---

## 4. How the data was built

Each source has a downloader → transformer → loader path, all idempotent.

The parts that took real work and are worth knowing about:

- **Value provenance.** MEXT prints estimates in parentheses and traces as `Tr`.
  The original ingest stripped both, so 22,414 estimated values were being
  displayed as measurements. A backfill tool re-read the source and updated in
  place, refusing to write unless all 2,538 foods matched.
- **Errata.** MEXT's 正誤表 lists each correction twice — the wrong value (誤)
  then the right one (正). Reading every row would have written the withdrawn
  values back in.
- **Companion books.** Fatty acids come from 第1表 (per 100 g of food), not
  第3表 (per gram of fat) — the difference put salmon's DHA at 112 instead of
  460.
- **Recipe matching.** MAFF recipes are free text ("ごぼう 1/2本"). Parsing
  counts and fractions into grams, then matching names to composition rows, with
  guards: pork must not resolve to beef, an unqualified cut keeps its fat, rice
  on a cooked plate is cooked rice.
- **Legal thresholds.** 食品表示基準 別表第十二 fetched from the e-Gov law API
  rather than recalled, so a food page can state that it meets the criterion a
  Japanese label must meet to say 「たんぱく質が高い」.

---

## 5. Known limitations — read before proposing anything

**The menu estimator is weak, and knows it.** 8,329 of 9,035 displayed menu
figures come from matching one keyword in a dish name to a standard recipe. It
now reads a stated weight (145g ≠ 110g ≠ ダブル220g), splits ＆-joined dishes,
and refuses to cost a dish it can't cost completely — but it still doesn't know
any specific restaurant's recipe. Two dishes built on the same main item can
still land on the same number. This is why only 3 menu pages are indexable.

**Chain coverage is 3 of 193.** Only はま寿司, くら寿司 and モスバーガー publish
nutrition in the corpus. This is a data-acquisition problem, not a matching
problem — normalised matching was measured and adds 54 links, all of which are
ambiguous variants (「…らーめん」 vs 「…らーめん（味玉無し）」) that would attach the
wrong figure. Expanding coverage means a scraper per chain.

**The recipe graph is shallow.** 248 distinct ingredients across 1,350 recipes,
and the most-used are all seasonings: sugar (690 dishes), soy sauce (594), salt
(586), sake, mirin, dashi. The matcher resolved the pantry and missed the
distinctive ingredients — backwards for anything that wants to answer "what can
I cook with X".

**No packaged-food or barcode data.** 食品表示法 has required nutrition labelling
on Japanese packaged food since 2020, so the data exists on every package, but no
open database publishes it. GS1 Japan's JAN registry is identity, not nutrition.

**Borrowed authority.** `shelf_life` is USDA FoodKeeper — American products and
assumptions applied to Japanese food. `food_portions` is English-only.

**JDI-8 is pointed at the wrong unit.** It scores single foods, where almost
everything gets 1 of 8. The index is designed to score a *diet*.

**No users.** 4 rows in `ai_meal_analyses`. Nothing is accumulating yet.

---

## 6. Constraints any proposal must respect

1. **Nothing fabricates a nutrition value.** An LLM may pick which existing
   composition row a name refers to, or estimate a weight; the nutrition itself
   is always arithmetic over measured values. Anything estimated is labelled on
   the page.
2. **Licence discipline.** OpenFoodFacts (ODbL) and Japanese Wikipedia
   (CC BY-SA) must not enter the corpus, an export, or the public site.
3. **薬機法.** No claim that a food prevents, treats or improves any condition.
   Nutrient-content claims are only made against the statutory thresholds, cited
   as such.
4. **Japanese only.** No English pages ship.
5. **A page must earn its index slot.** Reprinting what a restaurant already
   publishes, with no added fact, is what gets a site deindexed.

---

## 7. The question

Given:

- 257,235 provenance-tagged nutrient values across 173 components, including
  amino acid and fatty acid profiles that few consumer sites carry
- 1,364 regional dishes with recipes, prose and prefecture geography
- 17,876 priced restaurant menu items across 193 chains
- a vision model already wired for food photographs
- an SEO surface of 4,121 pages and no users, no revenue, and no app

**What is worth building on top of this?** I'm interested in:

- Product ideas the data uniquely supports — things a competitor with a
  generic nutrition API could not copy
- Whether any of it supports a business model, and which
- What I'm overvaluing (the amino acid data? the regional dishes?)
- What I'm undervaluing
- What to abandon

Be specific and be willing to say something here is a dead end.
