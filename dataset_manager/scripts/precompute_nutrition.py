"""Precompute and store verified nutritional values for menu items across the corpus.

Tier 1: Official chain disclosures (chain_nutrition) -> 100% lab/recipe figures
Tier 2: Government composition tables (items/nutrition) -> Direct MEXT matches
Tier 3: MEXT Standard Culinary Decomposition (analyzer) -> Culinary recipe totals
"""
import sqlite3
import datetime
from pathlib import Path
from ..database.db import get_db_connection
from ..database.site_schema import create_site_tables
from ..api.analyzer import decompose_dish_text, calculate_nutrition_for_dishes


def precompute_menu_nutrition(conn: sqlite3.Connection, shop_id: int = None, limit: int = None):
    create_site_tables(conn)
    cur = conn.cursor()

    query = """
        SELECT smi.id, smi.shop_id, smi.name, s.name AS shop_name,
               smi.chain_nutrition_id, smi.item_id,
               cn.energy_kcal AS chain_kcal, cn.protein_g AS chain_p,
               cn.fat_g AS chain_f, cn.carbohydrate_g AS chain_c, cn.salt_g AS chain_salt,
               n.energy_kcal AS table_kcal, n.protein_g AS table_p,
               n.fat_g AS table_f, n.carbohydrate_g AS table_c
        FROM shop_menu_items smi
        JOIN shops s ON s.id = smi.shop_id
        LEFT JOIN chain_nutrition cn ON cn.id = smi.chain_nutrition_id
        LEFT JOIN nutrition n ON n.item_id = smi.item_id
        WHERE 1=1
    """
    params = []
    if shop_id:
        query += " AND smi.shop_id = ?"
        params.append(shop_id)
    query += " ORDER BY smi.shop_id, smi.position"
    if limit:
        query += f" LIMIT {int(limit)}"

    rows = cur.execute(query, params).fetchall()
    total = len(rows)
    stats = {"total": total, "chain": 0, "table": 0, "mext_calc": 0, "unresolved": 0}

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    inserts = []

    for r in rows:
        item_id = r["id"]
        shop_name = r["shop_name"]
        dish_name = r["name"]

        # Tier 1: Official chain disclosure
        if r["chain_kcal"] is not None:
            inserts.append((
                item_id, float(r["chain_kcal"]),
                r["chain_p"], r["chain_f"], r["chain_c"], r["chain_salt"],
                "chain", 1.0, now
            ))
            stats["chain"] += 1
            continue

        # Tier 2: Direct government composition match
        if r["table_kcal"] is not None:
            inserts.append((
                item_id, float(r["table_kcal"]),
                r["table_p"], r["table_f"], r["table_c"], None,
                "table", 0.9, now
            ))
            stats["table"] += 1
            continue

        # Tier 3: Culinary recipe decomposition
        try:
            decomps = decompose_dish_text(dish_name, shop_name)
            res = calculate_nutrition_for_dishes(decomps, lang="ja")
            totals = res.get("totals") or {}
            kcal = totals.get("energy_kcal")
            if kcal and kcal > 0:
                p = totals.get("protein_g")
                f = totals.get("fat_g")
                c = totals.get("carbohydrate_g")
                salt = res.get("salt_g")
                inserts.append((
                    item_id, round(float(kcal), 1),
                    round(float(p), 1) if p is not None else None,
                    round(float(f), 1) if f is not None else None,
                    round(float(c), 1) if c is not None else None,
                    round(float(salt), 2) if salt is not None else None,
                    "mext_calc", 0.8, now
                ))
                stats["mext_calc"] += 1
            else:
                stats["unresolved"] += 1
        except Exception:
            stats["unresolved"] += 1

        # Batch insert every 500 rows
        if len(inserts) >= 500:
            cur.executemany("""
                INSERT OR REPLACE INTO menu_item_nutrition
                (shop_menu_item_id, energy_kcal, protein_g, fat_g, carbohydrate_g, salt_g, provenance, confidence, calculated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, inserts)
            conn.commit()
            inserts.clear()

    if inserts:
        cur.executemany("""
            INSERT OR REPLACE INTO menu_item_nutrition
            (shop_menu_item_id, energy_kcal, protein_g, fat_g, carbohydrate_g, salt_g, provenance, confidence, calculated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, inserts)
        conn.commit()

    return stats
