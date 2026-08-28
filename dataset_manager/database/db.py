import sqlite3
import os
from pathlib import Path
from typing import Dict, Any, List

from ..api.database import DB_PATH as _DB_PATH

DB_PATH = Path(_DB_PATH)

def get_db_connection() -> sqlite3.Connection:
    os.makedirs(DB_PATH.parent, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Datasets
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS datasets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        dataset_id TEXT NOT NULL,
        source TEXT NOT NULL,
        downloader TEXT NOT NULL,
        license TEXT NOT NULL,
        enabled BOOLEAN NOT NULL DEFAULT 0,
        priority INTEGER NOT NULL DEFAULT 0,
        extraction_type TEXT
    )
    """)
    
    # Files
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dataset_id INTEGER NOT NULL,
        filename TEXT NOT NULL,
        original_url TEXT,
        local_path TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        size INTEGER,
        FOREIGN KEY(dataset_id) REFERENCES datasets(id)
    )
    """)
    
    # Downloads
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS downloads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id INTEGER NOT NULL,
        start_time DATETIME DEFAULT CURRENT_TIMESTAMP,
        end_time DATETIME,
        status TEXT NOT NULL DEFAULT 'started',
        bytes_downloaded INTEGER DEFAULT 0,
        FOREIGN KEY(file_id) REFERENCES files(id)
    )
    """)
    
    # Checksums
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS checksums (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id INTEGER NOT NULL,
        sha256 TEXT,
        md5 TEXT,
        FOREIGN KEY(file_id) REFERENCES files(id)
    )
    """)
    
    # Versions
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS versions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dataset_id INTEGER NOT NULL,
        version TEXT NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(dataset_id) REFERENCES datasets(id)
    )
    """)
    # Phase 2: Transformed Normalized Schema
    # Items
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        category TEXT,
        source TEXT NOT NULL,
        source_url TEXT
    )
    """)
    
    # Shelf Life Rules
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS shelf_life (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER,
        storage_method TEXT,
        min_days INTEGER,
        max_days INTEGER,
        tips TEXT,
        FOREIGN KEY(item_id) REFERENCES items(id)
    )
    """)
    
    # Nutrition
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS nutrition (
            item_id INTEGER PRIMARY KEY,
            energy_kcal REAL,
            protein_g REAL,
            fat_g REAL,
            carbohydrate_g REAL,
            FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
        )
    """)
    
    # Ingredients
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ingredients (
            item_id INTEGER PRIMARY KEY,
            ingredients_text TEXT,
            FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
        )
    """)
    
    # Phase 3 tables
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS barcodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER,
            upc TEXT UNIQUE,
            FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS unified_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mext_item_id INTEGER,
            usda_item_id INTEGER,
            confidence_score REAL,
            FOREIGN KEY (mext_item_id) REFERENCES items(id) ON DELETE CASCADE,
            FOREIGN KEY (usda_item_id) REFERENCES items(id) ON DELETE CASCADE
        )
    ''')
    
    # Phase 4 tables
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS item_ingredients (
            item_id INTEGER PRIMARY KEY,
            ingredients_text TEXT,
            additives_tags TEXT,
            allergens TEXT,
            FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS provenance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset_id INTEGER,
            license TEXT,
            attribution_url TEXT,
            robots_txt_checked_at DATETIME,
            robots_txt_allowed BOOLEAN,
            FOREIGN KEY (dataset_id) REFERENCES datasets(id) ON DELETE CASCADE
        )
    ''')

    # AI Estimations
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ai_estimations (
            item_id INTEGER PRIMARY KEY,
            energy_kcal REAL,
            protein_g REAL,
            fat_g REAL,
            carbohydrate_g REAL,
            ingredients_text TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(item_id) REFERENCES items(id) ON DELETE CASCADE
        )
    ''')
    
    # AI Recipes
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ai_recipes (
            item_id INTEGER PRIMARY KEY,
            recipe_text TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(item_id) REFERENCES items(id) ON DELETE CASCADE
        )
    ''')

    # Full nutrient breakdown (key-value, so we don't hardcode ~54 columns).
    # The 4-macro `nutrition` table is kept and still populated for the API/merge.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS nutrients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            name TEXT,
            unit TEXT,
            amount REAL,
            FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
        )
    ''')
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_nutrients_item ON nutrients(item_id)")

    # MAFF regional dishes: prose detail per dish (text only, no embedded media).
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS regional_dishes (
            item_id INTEGER PRIMARY KEY,
            region TEXT,
            main_ingredients TEXT,
            history TEXT,
            occasion TEXT,
            how_to_eat TEXT,
            preservation TEXT,
            recipe_ingredients TEXT,
            recipe_steps TEXT,
            FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
        )
    ''')

    # JDI8 scores table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS jdi8_scores (
            item_id INTEGER PRIMARY KEY,
            score INTEGER NOT NULL,
            rice BOOLEAN NOT NULL,
            miso BOOLEAN NOT NULL,
            seaweed BOOLEAN NOT NULL,
            pickles BOOLEAN NOT NULL,
            green_yellow_veg BOOLEAN NOT NULL,
            fish BOOLEAN NOT NULL,
            green_tea BOOLEAN NOT NULL,
            low_meat BOOLEAN NOT NULL,
            details TEXT,
            FOREIGN KEY(item_id) REFERENCES items(id) ON DELETE CASCADE
        )
    ''')

    conn.commit()
    conn.close()

def get_dataset_by_name(name: str) -> sqlite3.Row:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM datasets WHERE name = ?", (name,))
    row = cursor.fetchone()
    conn.close()
    return row

def register_dataset(name: str, config: Dict[str, Any]) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO datasets (name, dataset_id, source, downloader, license, enabled, priority, extraction_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            dataset_id=excluded.dataset_id,
            source=excluded.source,
            downloader=excluded.downloader,
            license=excluded.license,
            enabled=excluded.enabled,
            priority=excluded.priority,
            extraction_type=excluded.extraction_type
    """, (
        name,
        config.get('dataset_id', ''),
        config.get('source', ''),
        config.get('downloader', ''),
        config.get('license', ''),
        config.get('enabled', False),
        config.get('priority', 0),
        config.get('extraction_type', '')
    ))
    conn.commit()
    
    cursor.execute("SELECT id FROM datasets WHERE name = ?", (name,))
    dataset_id = cursor.fetchone()['id']
    conn.close()
    return dataset_id

def log_file(dataset_id: int, filename: str, local_path: str, original_url: str = None, status: str = 'pending', size: int = 0) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO files (dataset_id, filename, original_url, local_path, status, size)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (dataset_id, filename, original_url, local_path, status, size))
    conn.commit()
    file_id = cursor.lastrowid
    conn.close()
    return file_id

def update_file_status(file_id: int, status: str, size: int = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    if size is not None:
        cursor.execute("UPDATE files SET status = ?, size = ? WHERE id = ?", (status, size, file_id))
    else:
        cursor.execute("UPDATE files SET status = ? WHERE id = ?", (status, file_id))
    conn.commit()
    conn.close()

def save_checksums(file_id: int, sha256: str, md5: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO checksums (file_id, sha256, md5)
        VALUES (?, ?, ?)
    """, (file_id, sha256, md5))
    conn.commit()
    conn.close()

def log_provenance(dataset_id: int, license: str, attribution_url: str, robots_txt_allowed: bool):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO provenance (dataset_id, license, attribution_url, robots_txt_checked_at, robots_txt_allowed)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?)
    """, (dataset_id, license, attribution_url, robots_txt_allowed))
    conn.commit()
    conn.close()

