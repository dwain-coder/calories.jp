"""Load MEXT's 調理による重量変化率 out of the explanatory book.

    uv run python tools/ingest_cooking_yield.py [--dry-run]

100 g of raw food becomes this many grams once cooked — boiled udon 180,
dried soba 260, most vegetables under 100 because they lose water. It is the
one figure that makes the raw-versus-cooked comparison on a food page mean
anything: without it, 100 g of dry pasta and 100 g of boiled pasta look like
the same amount of food, and they are not.

Published only inside the PDF of 第3章 資料, so it is read out of the text
layer rather than a spreadsheet. Each row begins with a 食品番号 and ends with
the rate, which is regular enough to parse and cheap enough to check: 01039
うどん ゆで must come out as 180.
"""
import argparse
import os
import re
import sqlite3
import sys
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dataset_manager.database.site_schema import create_site_tables  # noqa: E402

DB_PATH = os.environ.get("DATABASE_PATH", "data/metadata/dataset_manager.db")
PDF = Path("data/raw/mext_food_composition_2023/book.pdf")
ROW = re.compile(r"^(\d{5})\s+(.+?)\s+(\d{1,4})$")
PLAUSIBLE = (5, 900)          # % — outside this it is not a weight-change rate
KNOWN = {"01039": 180, "01128": 190, "01130": 260}   # checked against the book


def extract():
    out = {}
    with pdfplumber.open(PDF) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if "重量変化率" not in text and not out:
                continue
            for line in text.splitlines():
                m = ROW.match(line.strip())
                if not m:
                    continue
                code, desc, rate = m.group(1), m.group(2), int(m.group(3))
                if PLAUSIBLE[0] <= rate <= PLAUSIBLE[1]:
                    out.setdefault(code, (rate, desc.split()[0] if desc else None))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not PDF.is_file():
        sys.exit(f"{PDF} not found — download the 電子書籍 PDF first")

    rates = extract()
    print(f"parsed {len(rates)} rates from {PDF.name}")
    wrong = {c: rates.get(c, (None,))[0] for c, want in KNOWN.items()
             if rates.get(c, (None,))[0] != want}
    if wrong:
        sys.exit(f"known values did not come out right ({wrong}) — the PDF layout moved")

    conn = sqlite3.connect(DB_PATH, timeout=60)
    create_site_tables(conn)
    rows = []
    for code, (rate, method) in rates.items():
        item = conn.execute(
            "SELECT id FROM items WHERE source='MEXT Standard Tables' AND source_url = ?",
            (f"mext_{code}",)).fetchone()
        if item:
            rows.append((item[0], float(rate), method))
    print(f"matched {len(rows)} to foods in the corpus")
    if not args.dry_run:
        conn.execute("DELETE FROM cooking_yield")
        conn.executemany(
            "INSERT INTO cooking_yield (item_id, rate_percent, method) VALUES (?, ?, ?)", rows)
        conn.commit()
    conn.close()
    print("would store" if args.dry_run else "stored", len(rows), "rates")


if __name__ == "__main__":
    main()
