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

    # Search index. trigram tokenizer: substring matching works for Japanese.
    """CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
        item_id UNINDEXED, lang UNINDEXED, name, category,
        tokenize = 'trigram'
    )""",

    "CREATE INDEX IF NOT EXISTS idx_items_source ON items(source)",
]


# Columns added after the tables first shipped. CREATE TABLE IF NOT EXISTS
# leaves an existing table alone, so a new column needs saying so explicitly.
MIGRATIONS = (
    ("recipe_ingredient_links", "grams_source", "TEXT"),
    # 'measured' | 'estimated' | 'trace' — MEXT marks estimates in parentheses
    # and traces as Tr, and both were being stored as plain numbers.
    ("nutrients", "quality", "TEXT"),
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
