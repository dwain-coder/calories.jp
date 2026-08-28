# Dataset Manager — Corpus & System Brief

Handoff document. Snapshot date: 2026-08-27. Scope: everything in the system, with the
**non-ODbL (redistributable) corpus** as the focus. OpenFoodFacts is documented only as a
quarantined side-channel — see [ODbL quarantine](#3-odbl-quarantine).

---

## 1. What this project is

A Python pipeline that downloads, extracts, transforms, and unifies public food datasets into
one SQLite database, with a FastAPI read/query layer and a small React frontend. The domain
focus is **Japanese food**: nutrition, shelf life, regional dishes, and a Japanese Diet Index
(JDI8) score.

Everything lands in a single DB: `data/metadata/dataset_manager.db`.

## 2. Non-ODbL corpus (the redistributable part)

7 sources in `items`. Excluding OpenFoodFacts, the corpus is **9,195 items**.

| Source (`items.source`) | Items | License | Obligation |
|---|---:|---|---|
| Wikipedia (JA) | 2,722 | CC BY-SA 4.0 | Attribution + share-alike |
| MEXT Standard Tables | 2,538 | JP Gov Standard Terms of Use | Attribution |
| MAFF Our Regional Cuisines | 1,364 | JP Gov Standard Terms of Use | Attribution |
| USDA FoodKeeper | 1,226 | CC0 / Public Domain | None |
| USDA FoodData Central | 1,062 | CC0 / Public Domain | None |
| Wikidata (SPARQL) | 283 | CC0 / Public Domain | None |
| **Total (non-ODbL)** | **9,195** | | |

Fully unencumbered (CC0/PD) subset: **2,571 items** (FoodKeeper + FDC + Wikidata).

### 2.1 MEXT Standard Tables (2,538 items)

Japanese Standard Tables of Food Composition 2023 (文部科学省), from
`mext_00001_011.xlsx` (1.9 MB, in `data/raw/mext_food_composition_2023/`).

- Every item has a row in `nutrition` (kcal / protein / fat / carbs).
- Every item has detailed rows in `nutrients` — **118,396 rows total**, ~47 nutrient codes per item:
  `WATER`, `REFUSE`, `ENERC`, `ENERC_KCAL`, `PROT-`, `FAT-`, `CHOCDF-`, `CHOAVLDF-`, `ASH`,
  `NA`, `K`, `CA`, `MG`, `P`, `FE`, `NIA`, `NE`, `NACL_EQ`, `THIA`, `RIBF`, plus vitamins/minerals.
  Names and units are Japanese (`エネルギー`/`kcal`, `食塩相当量`/`g`).
- `items.category` = MEXT food group in Japanese: 魚介類 (471), 野菜類 (413), 肉類 (317),
  穀類 (208), 菓子類 (187), 果実類 (185), 調味料及び香辛料類 (148), 豆類 (113), and 10 more.
- All 2,538 have a JDI8 score.
- Highest-quality, densest source in the DB. Backbone for anything nutrition-related on the
  clean corpus.

### 2.2 MAFF Our Regional Cuisines (1,364 items)

うちの郷土料理 — regional dishes scraped from maff.go.jp HTML (text only, no media).
Scraper: `run_maff_cuisines.py`. No raw files on disk; written straight to DB.

- `items.category` = prefecture (47 prefectures, 23–30 dishes each).
- Table `regional_dishes` (1,364 rows) holds the rich content:
  `region`, `main_ingredients`, `history`, `occasion`, `how_to_eat`, `preservation`,
  `recipe_ingredients`, `recipe_steps`.
- All 1,364 have a JDI8 score.
- **Known data quality issue:** `regional_dishes.region` has 771 distinct values — free text
  scraped from the page, not a normalized prefecture code. Use `items.category` for reliable
  prefecture grouping; treat `region` as prose.
- No nutrition data — these are recipes, not composition entries.

### 2.3 USDA FoodKeeper (1,226 items)

FSIS FoodKeeper shelf-life data. Raw: `data/raw/usda_foodkeeper/` (`.xls`/`.xlsx`, 373 KB).

- The **only** source of shelf-life data. Table `shelf_life`: 1,994 rows
  (`storage_method`, `min_days`, `max_days`, `tips`).
- Storage methods: Refrigerate 728, Freeze 678, Pantry 588. Items may have multiple rows.
- `items.category` is an unresolved **numeric category ID as text** ("23", "19", "10"…) —
  the FoodKeeper category lookup table was never joined in. Fixable from the source file.
- Item names are **Japanese** — machine-translated from English via LLM
  (`dataset_manager/utils/translate.py`, batched through LiteLLM). English originals are not
  retained in the DB.
- No nutrition data.

### 2.4 USDA FoodData Central (1,062 items)

Foundation Foods JSON, 2026-04-30 release. Raw zip in `data/raw/usda_fooddata_central/`,
extracted JSON (6.5 MB) in `data/extracted/usda_fooddata_central/`.

- All 1,062 have `nutrition` rows (macro-level only — the detailed FDC nutrient array was not
  expanded into `nutrients`; that table is MEXT-only).
- `items.category` = "foundation" for all rows (flat, not useful for filtering).
- `items.source_url` is an internal ref (`fdc_321358`), not a resolvable URL.
- Names are LLM-translated to Japanese, same as FoodKeeper.
- No JDI8 scores.

### 2.5 Wikipedia (JA) (2,722 items)

Japanese food-culture category members via the MediaWiki API
(`Category:日本の食文化`, `list=categorymembers`).

- All 2,722 have a row in `ingredients` (free-text `ingredients_text`).
- No nutrition, no shelf life, no JDI8.
- Real `source_url` per item (ja.wikipedia.org article URL) — attribution is straightforward.
- **CC BY-SA 4.0**: the one non-ODbL source with a share-alike obligation. Extracted facts are
  fine; verbatim prose carries the license forward. Keep it separable from the CC0/gov corpus
  if you need a permissive export.

### 2.6 Wikidata (SPARQL) (283 items)

SPARQL query against query.wikidata.org for food instances with country of origin = Japan.

- All 283 have `ingredients` rows.
- `source_url` = Wikidata entity URI (`http://www.wikidata.org/entity/Q...`) — good join key to
  anything else Wikidata-linked.
- CC0, zero obligations. Smallest but legally cleanest source.

### 2.7 Derived layer: JDI8 scores (3,902 rows)

Japanese Diet Index, 8 components, implemented in `dataset_manager/utils/jdi8.py`.
Pure keyword matching over item name + category + ingredients + recipe text — **no LLM**,
deterministic, testable (`test_jdi8.py`).

Components (booleans in `jdi8_scores`): `rice`, `miso`, `seaweed`, `pickles`,
`green_yellow_veg`, `fish`, `green_tea`, `low_meat`. `details` holds matched-keyword evidence.

Coverage: MEXT 2,538 + MAFF 1,364 = 3,902. Nothing else is scored.

Score distribution: 0→155, 1→1,627, 2→1,247, 3→462, 4→301, 5→99, 6→10, 7→1, 8→0.
Skews low because most MEXT rows are single ingredients, not composed meals.

### 2.8 Regulatory / guideline text corpus (documents, not rows)

Scraped to Markdown via Firecrawl, stored as files in `data/raw/`, **not loaded into `items`**.
Used as prompt context by the compliance rules engine.

| Path | Source | License |
|---|---|---|
| `data/raw/caa_food_labeling_standards/food_labeling_standards.md` | Consumer Affairs Agency (消費者庁) | JP Gov Standard Terms |
| `data/raw/fda_food_code/fda_food_code.md` | US FDA Food Code 2022 | Public Domain |
| `data/raw/maff_refrigerator_guide/maff_refrigerator_guide.md` | MAFF | JP Gov Standard Terms |
| `data/raw/tokyo_nerima_food_labeling/nerima_kigenhyoji.md` | Tokyo Nerima Ward | Public guidelines |

All small (2–29 KB). Each raw dir also has a `manifest.json`.

## 3. ODbL quarantine

**OpenFoodFacts — 2,069,355 items, ODbL, 6.0 GB CSV.** 99.5% of the `items` table.

It dominates: `barcodes` (2,069,261 rows), `nutrition` (2,069,355 of 2,072,999),
`ingredients` (724,969 of 727,974). Any query over `items` without a `source` filter is
effectively an OpenFoodFacts query.

ODbL is share-alike at the database level: a redistributed derived database must also be ODbL.

The system already handles this — `GET /export/clean` hard-filters to
`source IN ('MEXT Standard Tables', 'MAFF Our Regional Cuisines')` and its docstring names the
quarantine explicitly. **Note the gap:** that whitelist excludes FoodKeeper, FoodData Central,
and Wikidata, which are CC0 and safe to include. To get the full permissive export, widen that
`IN` clause to the 5 non-Wikipedia sources (and decide separately on CC BY-SA Wikipedia).

## 4. System architecture

```
main.py                     Typer CLI entrypoint (loads .env, delegates to scripts/cli.py)
config/datasets.yaml        Single source of truth: 11 dataset definitions
data/raw/<name>/            Downloaded originals + manifest.json
data/extracted/<name>/      Unpacked archives
data/metadata/*.db          SQLite (WAL mode)
frontend/                   React 19 + Vite 8
```

### 4.1 Package layout (`dataset_manager/`)

- `downloaders/` — `http`, `stream` (chunked, for the 6 GB CSV), `firecrawl` (JS-rendered pages
  to Markdown), `huggingface`, `base`. Selected per dataset by the `downloader:` key.
- `extractors/archive.py` — zip/7z unpacking.
- `transformers/` — one per source: `mext`, `maff_cuisines`, `usda`, `usda_fdc`,
  `openfoodfacts`, `wikidata`, `wikipedia`, plus `llm.py` (`LLMMarkdownTransformer`:
  Pydantic-schema-constrained extraction of shelf-life rules out of Markdown).
- `utils/` — `jdi8.py` (scoring), `translate.py` (LLM EN→JA batch translation),
  `manifest.py`, `disk.py`.
- `database/db.py` — schema creation + dataset/file/checksum bookkeeping.
- `api/` — `server.py` (FastAPI), `database.py` (queries), `models.py` (Pydantic response models).
- `scripts/` — `cli.py` (commands), `merge.py` (LLM entity matching MEXT↔USDA),
  `rules_engine.py` (LLM compliance check against scraped labeling rules).

### 4.2 CLI (`python main.py <cmd>`)

| Command | Does |
|---|---|
| `init` | Create DB, seed `datasets` from `config/datasets.yaml` |
| `list-datasets [--all]` | Show datasets and status |
| `download-next` | Download the highest-priority pending dataset |
| `transform` | Run the transformer for downloaded datasets |
| `serve [--port 8000]` | Run the FastAPI server |

### 4.3 API endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/` | Health + `total_items` + per-source counts |
| GET | `/items` | Paginated search: `query`, `source`, `category`, `page`, `size` |
| GET | `/items/{id}` | Full detail: nutrition, nutrients, shelf life, ingredients, regional dish, JDI8, license |
| GET | `/items/{id}/jdi8` | JDI8 score + component flags |
| POST | `/items/{id}/estimate` | **LLM** — estimate missing nutrition, cached in `ai_estimations` |
| POST | `/items/{id}/recipe` | **LLM** — generate recipe, cached in `ai_recipes` |
| GET | `/export/clean?format=csv\|json` | ODbL-quarantined export (see §3) |

`api/database.py::get_license_info(source)` maps each source to its license + attribution URL,
so per-item license is returned with detail responses.

### 4.4 Frontend

React 19 + Vite 8, `lucide-react` icons, `oxlint`. Dev server on :5173.
API base URL is **hardcoded** to `http://localhost:8000` in `frontend/src/App.jsx` and
`frontend/src/components/ItemModal.jsx` — no env var, no Vite proxy. Backend must be on 8000.

### 4.5 LLM usage

Via **LiteLLM**, model from `HELM_LLM_MODEL`, key from `GEMINI_API_KEY` (`.env`).
`api/server.py` also imports `google-genai` directly.

Six LLM touchpoints: name translation (`utils/translate.py`), Markdown→structured shelf-life
(`transformers/llm.py`), MEXT↔USDA entity merge (`scripts/merge.py`), compliance check
(`scripts/rules_engine.py`), and the `/estimate` and `/recipe` endpoints.

## 5. Database schema

18 tables. `items` (id, name, category, source, source_url) is the hub; everything else joins
on `item_id`.

| Table | Rows | Populated from |
|---|---:|---|
| `items` | 2,078,550 | all sources |
| `nutrition` | 2,072,999 | OFF, MEXT, FDC |
| `barcodes` | 2,069,355 | OFF only |
| `ingredients` | 727,974 | OFF, Wikipedia, Wikidata |
| `nutrients` | 118,396 | MEXT only (~47 codes × 2,538) |
| `jdi8_scores` | 3,902 | MEXT, MAFF |
| `shelf_life` | 1,994 | FoodKeeper only |
| `regional_dishes` | 1,364 | MAFF only |
| `provenance` | 16 | license + robots.txt audit per dataset |
| `files` | 17 | download bookkeeping |
| `datasets` | 11 | seeded from YAML |
| `checksums` | 7 | sha256/md5 per file |
| `item_ingredients` | 44 | OFF subset w/ additives + allergens (rules engine input) |
| `unified_items` | 0 | MEXT↔USDA merge — **never run at scale** |
| `ai_estimations` | 0 | empty cache |
| `ai_recipes` | 0 | empty cache |
| `downloads` | 0 | unused |
| `versions` | 0 | unused |

## 6. Running it

```powershell
uv sync
uv run python main.py serve             # backend  http://localhost:8000  (docs at /docs)
cd frontend; npm install; npm run dev   # frontend http://localhost:5173
```

Docker: `docker compose up --build` (backend :8000, frontend :80, `.env` loaded via `env_file`).

`.env` needs `GEMINI_API_KEY` and `HELM_LLM_MODEL`.

## 7. Known gaps / open items

1. `google-genai` is imported by `api/server.py:76` but was missing from `pyproject.toml`;
   added via `uv add google-genai`. Without it the server fails at import.
2. `README.md` is empty (0 bytes).
3. `unified_items` is empty — cross-source entity resolution (MEXT↔USDA) is written but unrun;
   `merge.py` still has a `LIMIT 50 -- for testing`.
4. `/export/clean` omits the three CC0 sources (see §3).
5. FoodKeeper `items.category` holds raw numeric IDs; category names never joined.
6. `regional_dishes.region` is unnormalized free text (771 distinct for 47 prefectures).
7. FoodData Central detailed nutrients never expanded into `nutrients`.
8. Item names for USDA sources are LLM translations; English originals not retained.
9. Root directory holds ~15 ad-hoc one-off scripts (`run_*.py`, `fix.py`, `count_off.py`,
   `populate_jdi8.py`, `transform_off.py`, `generate_*.py`) outside the package — these are how
   most data actually got loaded, not the `main.py transform` path.
10. `data/raw/openfoodfacts/` is 6.0 GB and appears in git status.

## 8. Attribution strings for redistribution

- **MEXT**: 文部科学省「日本食品標準成分表2023年版（八訂）」
- **MAFF**: 農林水産省「うちの郷土料理」
- **USDA FoodKeeper / FoodData Central**: public domain, no attribution required (credit courteous)
- **Wikidata**: CC0, no attribution required
- **Wikipedia (JA)**: CC BY-SA 4.0 — per-article attribution + share-alike on derived text
- **OpenFoodFacts**: ODbL — attribution + share-alike at database level (quarantined)
