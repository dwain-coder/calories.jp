"""Additive schema for the public bilingual site. Never touches existing tables."""

SITE_DDL = [
    # Localized names & aliases.
    # kind: 'official' (from source data), 'translated' (LLM), 'romanized' (LLM romaji),
    #       'alias' (search-only synonym, e.g. cleaned MEXT display name)
    """CREATE TABLE IF NOT EXISTS item_names (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER NOT NULL REFERENCES items(id),
        lang TEXT NOT NULL CHECK (lang IN ('en','ja')),
        name TEXT NOT NULL,
        kind TEXT NOT NULL,
        is_primary INTEGER NOT NULL DEFAULT 0,
        UNIQUE(item_id, lang, name)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_item_names_item ON item_names(item_id)",

    # One row per (item, lang) public page.
    """CREATE TABLE IF NOT EXISTS site_pages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER NOT NULL REFERENCES items(id),
        lang TEXT NOT NULL CHECK (lang IN ('en','ja')),
        slug TEXT NOT NULL,
        page_type TEXT NOT NULL,
        title TEXT,
        meta_description TEXT,
        indexable INTEGER NOT NULL DEFAULT 1,
        updated_at TEXT,
        UNIQUE(lang, slug),
        UNIQUE(item_id, lang)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_site_pages_item ON site_pages(item_id)",

    # MAFF recipe ingredient line -> MEXT item resolution (offline build, runtime read).
    """CREATE TABLE IF NOT EXISTS recipe_ingredient_links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dish_item_id INTEGER NOT NULL REFERENCES items(id),
        line_no INTEGER NOT NULL,
        raw_name TEXT NOT NULL,
        raw_quantity TEXT,
        grams REAL,
        -- 'measure' when the recipe stated a weight or a standard spoon/cup,
        -- 'unit' when it said "2 carrots" and a reference weight was applied.
        grams_source TEXT,
        mext_item_id INTEGER REFERENCES items(id),
        confidence REAL,
        method TEXT,
        verified INTEGER NOT NULL DEFAULT 0,
        UNIQUE(dish_item_id, line_no)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_ril_dish ON recipe_ingredient_links(dish_item_id)",

    # 調理による重量変化率: 100 g of the raw food becomes this many grams once
    # cooked. Boiled udon is 180, dried soba 260. Without it, comparing 100 g
    # of raw against 100 g of cooked compares two different amounts of food.
    """CREATE TABLE IF NOT EXISTS cooking_yield (
        item_id INTEGER PRIMARY KEY REFERENCES items(id),
        rate_percent REAL NOT NULL,
        method TEXT
    )""",

    # FDC serving portions (from raw FoundationFoods JSON).
    """CREATE TABLE IF NOT EXISTS food_portions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER NOT NULL REFERENCES items(id),
        description TEXT NOT NULL,
        gram_weight REAL NOT NULL,
        UNIQUE(item_id, description)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_food_portions_item ON food_portions(item_id)",

    # Meal photo analyzer cache.
    """CREATE TABLE IF NOT EXISTS ai_meal_analyses (
        image_sha256 TEXT PRIMARY KEY,
        lang TEXT NOT NULL,
        result_json TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""",

    # ---- Restaurant menus -------------------------------------------------
    # A dated SNAPSHOT, not a live feed. The extractor that produced the source
    # CSV no longer exists and no licence was recorded with it, so: no scraped
    # descriptions and no store photos are imported, `imported_at` is stamped on
    # every shop, and the page says which month the prices are from.
    #
    # Why a parallel table instead of reusing site_pages: site_pages.item_id is
    # NOT NULL and UNIQUE(item_id, lang) — one page per composition-table entry.
    # A shop is not an entry. Widening that column would mean a full SQLite table
    # rebuild (MIGRATIONS below only knows how to ADD a column) and would loosen
    # the join that keeps OpenFoodFacts and Wikipedia off the public site.
    """CREATE TABLE IF NOT EXISTS shops (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        menu_id TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        item_count INTEGER NOT NULL DEFAULT 0,
        price_min INTEGER,
        price_max INTEGER,
        imported_at TEXT
    )""",

    # One row per (shop, lang) public page.
    #
    # `indexable` DEFAULTS TO 0 here — the inverse of site_pages, and deliberate.
    # A food page is indexable because it carries measured nutrition nobody else
    # has. A menu page carries a menu that the restaurant, Tabelog and Hotpepper
    # all publish too, so it earns its index slot only by clearing the gate in
    # scripts/build_shops.py (enough items, enough of them resolved to real
    # nutrition, a real price). kalori.jp lost exactly these pages.
    """CREATE TABLE IF NOT EXISTS shop_pages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        shop_id INTEGER NOT NULL REFERENCES shops(id),
        lang TEXT NOT NULL CHECK (lang IN ('en','ja')),
        slug TEXT NOT NULL,
        page_type TEXT NOT NULL,
        title TEXT,
        meta_description TEXT,
        indexable INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT,
        UNIQUE(lang, slug),
        UNIQUE(shop_id, lang)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_shop_pages_shop ON shop_pages(shop_id)",

    # A dish on one shop's menu. `item_id` is the whole point of the table: it
    # links the dish to a composition-table entry so the page can state a calorie
    # figure that came from a lab, not a model. It is NULLABLE on purpose — an
    # unmatched dish is a row with a dash in the calorie column, never a guess.
    #
    # price_max_yen is set only when the source disagreed with itself about the
    # price of the same dish (663 rows did). The page then shows the span. A
    # single number picked out of a disagreement would be a fabricated price.
    """CREATE TABLE IF NOT EXISTS shop_menu_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        shop_id INTEGER NOT NULL REFERENCES shops(id),
        source_item_id TEXT,
        name TEXT NOT NULL,
        price_yen INTEGER,
        price_max_yen INTEGER,
        tax_incl INTEGER NOT NULL DEFAULT 0,
        mealtime TEXT,
        position INTEGER NOT NULL DEFAULT 0,
        item_id INTEGER REFERENCES items(id),
        match_confidence REAL,
        match_method TEXT,
        UNIQUE(shop_id, name, mealtime)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_shop_menu_items_shop ON shop_menu_items(shop_id)",
    "CREATE INDEX IF NOT EXISTS idx_shop_menu_items_item ON shop_menu_items(item_id)",

    # Per-dish nutrition as the CHAIN itself publishes it (a legal disclosure).
    # This is the only honest source for a composed restaurant dish: the
    # composition tables list ingredients, so matching a menu name against them
    # returns an ingredient of the dish rather than the dish. Provenance columns
    # are not optional here — a figure a reader cannot trace back is exactly what
    # this site refuses to print.
    """CREATE TABLE IF NOT EXISTS chain_nutrition (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        shop_id INTEGER NOT NULL REFERENCES shops(id),
        name TEXT NOT NULL,
        name_key TEXT NOT NULL,
        energy_kcal REAL,
        source_url TEXT NOT NULL,
        source_page TEXT,
        source_updated TEXT,
        fetched_at TEXT NOT NULL,
        UNIQUE(shop_id, name)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_chain_nutrition_shop ON chain_nutrition(shop_id)",
    "CREATE INDEX IF NOT EXISTS idx_chain_nutrition_key ON chain_nutrition(shop_id, name_key)",

    # A photograph for an item, with the terms it may be shown under.
    #
    # licence and credit are NOT NULL because a free image whose attribution we
    # did not keep is not usable: CC BY and CC BY-SA both require naming the
    # author, and an image we cannot credit has to be dropped rather than shown.
    #
    # `matched_on` records HOW the image was tied to the dish — a Wikidata P18
    # statement is an editor asserting this picture depicts this thing, while a
    # name-matched Commons search hit is our own inference. Worth being able to
    # tell apart later, and worth being able to purge one without the other.
    """CREATE TABLE IF NOT EXISTS item_images (
        item_id INTEGER PRIMARY KEY REFERENCES items(id),
        url TEXT NOT NULL,
        page_url TEXT,
        width INTEGER,
        height INTEGER,
        source TEXT NOT NULL,
        licence TEXT NOT NULL,
        licence_url TEXT,
        credit TEXT NOT NULL,
        matched_on TEXT NOT NULL,
        fetched_at TEXT NOT NULL
    )""",

    # Search index. trigram tokenizer: substring matching works for Japanese.
    """CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
        item_id UNINDEXED, lang UNINDEXED, name, category,
        tokenize = 'trigram'
    )""",

    # Precomputed nutrition cache for menu items (linking Tier 1, 2, or 3)
    """CREATE TABLE IF NOT EXISTS menu_item_nutrition (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        shop_menu_item_id INTEGER NOT NULL UNIQUE REFERENCES shop_menu_items(id),
        energy_kcal REAL,
        protein_g REAL,
        fat_g REAL,
        carbohydrate_g REAL,
        salt_g REAL,
        provenance TEXT NOT NULL CHECK (provenance IN ('chain', 'table', 'mext_calc')),
        confidence REAL,
        calculated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""",
    "CREATE INDEX IF NOT EXISTS idx_min_item ON menu_item_nutrition(shop_menu_item_id)",

    "CREATE INDEX IF NOT EXISTS idx_items_source ON items(source)",
]


# Columns added after the tables first shipped. CREATE TABLE IF NOT EXISTS
# leaves an existing table alone, so a new column needs saying so explicitly.
MIGRATIONS = (
    ("recipe_ingredient_links", "grams_source", "TEXT"),
    # The chain's own published figure for this dish, when it publishes one.
    ("shop_menu_items", "chain_nutrition_id", "INTEGER REFERENCES chain_nutrition(id)"),
    # 'measured' | 'estimated' | 'trace' — MEXT marks estimates in parentheses
    # and traces as Tr, and both were being stored as plain numbers.
    ("nutrients", "quality", "TEXT"),
    # Full macros for official chain nutrition disclosures (PFC + Salt)
    ("chain_nutrition", "protein_g", "REAL"),
    ("chain_nutrition", "fat_g", "REAL"),
    ("chain_nutrition", "carbohydrate_g", "REAL"),
    ("chain_nutrition", "salt_g", "REAL"),
    # What the 重量変化率 is a percentage OF. MEXT's table is against the 調理前
    # food — raw or dry — for 496 of its 497 rows, and against the BOILED weight
    # for マカロニ・スパゲッティ ソテー, which is why that one reads 100%. Null means
    # the ordinary case; a converter that assumed it for all of them would say
    # 100 g of dry spaghetti fries down to 100 g.
    ("cooking_yield", "base", "TEXT"),
)


def create_site_tables(conn):
    cur = conn.cursor()
    for ddl in SITE_DDL:
        cur.execute(ddl)
    for table, column, coltype in MIGRATIONS:
        have = {r[1] for r in cur.execute(f"PRAGMA table_info({table})")}
        if column not in have:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
    conn.commit()
