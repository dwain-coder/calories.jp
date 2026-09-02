import re
import pandas as pd
from pathlib import Path
from typing import Dict, Any, Optional
from .base import BaseTransformer

# MEXT food-group codes (食品群) -> Japanese name.
FOOD_GROUPS = {
    "01": "穀類", "02": "いも及びでん粉類", "03": "砂糖及び甘味類", "04": "豆類",
    "05": "種実類", "06": "野菜類", "07": "果実類", "08": "きのこ類",
    "09": "藻類", "10": "魚介類", "11": "肉類", "12": "卵類",
    "13": "乳類", "14": "油脂類", "15": "菓子類", "16": "し好飲料類",
    "17": "調味料及び香辛料類", "18": "調理済み流通食品類",
}

# Canonical column layout of the MEXT Standard Tables main table (八訂 / 増補2023):
# (excel_column_index, component_identifier_code, Japanese name, unit).
# Column indices are stable within an edition; transform() asserts the file's
# 成分識別子 row matches these codes and fails loudly on any layout drift.
# ponytail: hardcoded spec because the xlsx header is multi-row/merged and one
# real nutrient (Na, col 23) ships with a blank code cell — parsing by header
# alone would silently drop it. Regenerate this list if MEXT reorders columns.
NUTRIENT_COLS = [
    (4, "REFUSE", "廃棄率", "%"),
    (5, "ENERC", "エネルギー", "kJ"),
    (6, "ENERC_KCAL", "エネルギー", "kcal"),
    (7, "WATER", "水分", "g"),
    (8, "PROTCAA", "アミノ酸組成によるたんぱく質", "g"),
    (9, "PROT-", "たんぱく質", "g"),
    (10, "FATNLEA", "脂肪酸のトリアシルグリセロール当量", "g"),
    (11, "CHOLE", "コレステロール", "mg"),
    (12, "FAT-", "脂質", "g"),
    (13, "CHOAVLM", "利用可能炭水化物（単糖当量）", "g"),
    (15, "CHOAVL", "利用可能炭水化物（質量計）", "g"),
    (16, "CHOAVLDF-", "差引き法による利用可能炭水化物", "g"),
    (18, "FIB-", "食物繊維総量", "g"),
    (19, "POLYL", "糖アルコール", "g"),
    (20, "CHOCDF-", "炭水化物", "g"),
    (21, "OA", "有機酸", "g"),
    (22, "ASH", "灰分", "g"),
    (23, "NA", "ナトリウム", "mg"),        # blank code cell in the file
    (24, "K", "カリウム", "mg"),
    (25, "CA", "カルシウム", "mg"),
    (26, "MG", "マグネシウム", "mg"),
    (27, "P", "リン", "mg"),
    (28, "FE", "鉄", "mg"),
    (29, "ZN", "亜鉛", "mg"),
    (30, "CU", "銅", "mg"),
    (31, "MN", "マンガン", "mg"),
    (33, "ID", "ヨウ素", "µg"),
    (34, "SE", "セレン", "µg"),
    (35, "CR", "クロム", "µg"),
    (36, "MO", "モリブデン", "µg"),
    (37, "RETOL", "レチノール", "µg"),
    (38, "CARTA", "α-カロテン", "µg"),
    (39, "CARTB", "β-カロテン", "µg"),
    (40, "CRYPXB", "β-クリプトキサンチン", "µg"),
    (41, "CARTBEQ", "β-カロテン当量", "µg"),
    (42, "VITA_RAE", "レチノール活性当量", "µg"),
    (43, "VITD", "ビタミンD", "µg"),
    (44, "TOCPHA", "α-トコフェロール", "mg"),
    (45, "TOCPHB", "β-トコフェロール", "mg"),
    (46, "TOCPHG", "γ-トコフェロール", "mg"),
    (47, "TOCPHD", "δ-トコフェロール", "mg"),
    (48, "VITK", "ビタミンK", "µg"),
    (49, "THIA", "ビタミンB1", "mg"),
    (50, "RIBF", "ビタミンB2", "mg"),
    (51, "NIA", "ナイアシン", "mg"),
    (52, "NE", "ナイアシン当量", "mg"),
    (53, "VITB6A", "ビタミンB6", "mg"),
    (54, "VITB12", "ビタミンB12", "µg"),
    (55, "FOL", "葉酸", "µg"),
    (56, "PANTAC", "パントテン酸", "mg"),
    (57, "BIOT", "ビオチン", "µg"),
    (58, "VITC", "ビタミンC", "mg"),
    (59, "ALC", "アルコール", "g"),
    (60, "NACL_EQ", "食塩相当量", "g"),
]

GROUP_COL, NUMBER_COL, NAME_COL = 0, 1, 3
CODE_ROW_LABEL = "成分識別子"


def clean_amount(v) -> Optional[float]:
    """Just the number. See clean_value for what the number is worth."""
    return clean_value(v)[0]


def clean_value(v):
    """A MEXT cell as (amount, quality).

    The tables say more than a number. Parentheses mark a value MEXT estimated
    rather than analysed — calculated from a related food, or borrowed from a
    similar one — and 'Tr' means present in trace amounts, which is not the
    same claim as zero. Both were being flattened into a plain float, so a
    site whose whole point is showing measured values was showing 22,414
    estimates as measurements and 3,081 traces as hard zeros.

    quality is 'measured', 'estimated' or 'trace'; a value that was not
    determined at all is (None, None) and is stored as nothing, as before.
    """
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None, None
    raw = str(v).strip().replace("*", "").replace("（", "(").replace("）", ")")
    estimated = raw.startswith("(") and raw.endswith(")")
    s = raw.strip("() ").strip()
    if s in ("", "-", "−"):
        return None, None
    if s.lower() == "tr":
        # A parenthesised trace is still a trace: both say "a little, not none".
        return 0.0, "trace"
    try:
        return float(s), ("estimated" if estimated else "measured")
    except ValueError:
        return None, None


class MEXTTransformer(BaseTransformer):
    def transform(self, dataset_config: Dict[str, Any], raw_path: Path):
        print(f"Transforming MEXT data from {raw_path}...")
        df = pd.read_excel(raw_path, header=None)

        # Locate the component-identifier row, data starts on the next row.
        code_row = next(
            (i for i in range(20) if any(str(v).strip() == CODE_ROW_LABEL for v in df.iloc[i])),
            None,
        )
        if code_row is None:
            print(f"Could not find '{CODE_ROW_LABEL}' header row; aborting.")
            return

        # Verify the file layout matches our canonical spec (skip Na, blank in file).
        codes = df.iloc[code_row]
        for col, code, _, _ in NUTRIENT_COLS:
            actual = str(codes[col]).strip()
            if code == "NA":
                continue
            assert actual == code, (
                f"MEXT layout drift at col {col}: expected '{code}', got '{actual}'. "
                f"Regenerate NUTRIENT_COLS in transformers/mext.py."
            )

        source = "MEXT Standard Tables"
        url = dataset_config.get("url", "")
        cur = self.conn.cursor()
        nutrient_rows, macro_rows = [], []
        items_added = 0

        for _, row in df.iloc[code_row + 1:].iterrows():
            name = row[NAME_COL]
            if pd.isna(name) or str(name).strip() == "":
                continue
            group_code = str(row[GROUP_COL]).strip().split(".")[0].zfill(2)
            category = FOOD_GROUPS.get(group_code, group_code)

            # 食品番号 — the key MEXT indexes every other publication by (the
            # amino acid, fatty acid and carbohydrate books, and the errata).
            # Stored the way FDC items already are: "mext_01001".
            food_code = str(row[NUMBER_COL]).strip()
            item_url = f"mext_{food_code}" if food_code and food_code != "nan" else url

            item_id = self._insert_item(str(name).strip(), category, source, item_url)

            by_code = {}
            for col, code, jp_name, unit in NUTRIENT_COLS:
                amount, quality = clean_value(row[col])
                if amount is None:
                    continue
                nutrient_rows.append((item_id, code, jp_name, unit, amount, quality))
                by_code[code] = amount

            macro_rows.append((
                item_id,
                by_code.get("ENERC_KCAL"),
                by_code.get("PROT-"),
                by_code.get("FAT-"),
                by_code.get("CHOCDF-", by_code.get("CHOAVL")),
            ))
            items_added += 1

        cur.executemany(
            "INSERT INTO nutrients (item_id, code, name, unit, amount, quality)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            nutrient_rows,
        )
        cur.executemany(
            "INSERT OR REPLACE INTO nutrition (item_id, energy_kcal, protein_g, fat_g, carbohydrate_g) VALUES (?, ?, ?, ?, ?)",
            macro_rows,
        )
        self.conn.commit()
        print(f"Added {items_added} MEXT foods with {len(nutrient_rows)} nutrient values.")


def demo():
    """Self-check for the value cleaner."""
    assert clean_value("12.3") == (12.3, "measured")
    assert clean_value("(11.3)") == (11.3, "estimated")
    assert clean_value("（0）") == (0.0, "estimated")
    assert clean_value("Tr") == (0.0, "trace")
    assert clean_value("(Tr)") == (0.0, "trace")
    assert clean_value("-") == (None, None)
    assert clean_amount("Tr") == 0.0
    assert clean_amount("(12)") == 12.0
    assert clean_amount("（0）") == 0.0
    assert clean_amount("-") is None
    assert clean_amount("63.5*") == 63.5
    assert clean_amount(float("nan")) is None
    assert clean_amount("13.5") == 13.5
    print("mext clean_amount: OK")


if __name__ == "__main__":
    demo()
