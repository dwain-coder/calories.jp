"""Per-dish nutrition published by the restaurant chains themselves.

WHY THIS EXISTS. The composition tables cannot cost a composed restaurant dish.
Matching 「まぐろ醤油ラーメン」 against MEXT resolves it to soy sauce, because MEXT
lists ingredients and standard foods — an audit of that approach produced a
champagne costed as French bread and a cheeseburger costed as cheese. The honest
source for a chain dish's calories is the chain's own published 栄養成分表, which
is a legal disclosure, updated by the operator, and per dish.

WHAT IS TAKEN AND WHAT IS NOT. Only the numbers: dish name and energy. Those are
facts about a product, they are published for the public to read, and every row
carries `source_url` plus the update date printed on the source itself, so any
figure on our pages can be traced back and re-checked. Nothing is inferred, and
no model touches these numbers — a missing value stays missing.

Each chain publishes differently (PDF here, HTML or XLSX elsewhere), so a chain
is a small parser plus a `Chain` record. One is implemented; the registry is how
the next twenty arrive without a framework being invented first.
"""
import datetime
import io
import re
import urllib.request

USER_AGENT = "calories.jp nutrition importer (+https://calories.jp/sources)"


class Chain:
    """One chain's published nutrition source and how to read it."""

    def __init__(self, key, shop_name, url, parser, source_page=None):
        self.key = key
        self.shop_name = shop_name      # must equal shops.name in our corpus
        # One chain can publish in several files — はま寿司 splits in-store and
        # takeout, and a dish only in the takeout list is still a real dish.
        self.urls = [url] if isinstance(url, str) else list(url)
        self.source_page = source_page  # the human page that links it, for attribution
        self.parser = parser

    @property
    def url(self):
        """The first source file, for the `source_url` recorded against a row."""
        return self.urls[0]

    def fetch(self, opener=None):
        """Download every source. `opener` is injectable so tests never hit the network."""
        blobs = []
        for url in self.urls:
            if opener:
                blobs.append(opener(url))
                continue
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=60) as response:
                blobs.append(response.read())
        return blobs

    def rows(self, blobs):
        """Merged rows from every source, plus the OLDEST update date seen.

        Oldest, not newest: the page states one date for the whole table, and
        claiming the fresher of two files would overstate how current the older
        half is.
        """
        merged, dates, seen = [], [], set()
        for blob in blobs:
            rows, updated = self.parser(blob)
            if updated:
                dates.append(updated)
            for row in rows:
                if row["name"] in seen:
                    continue
                seen.add(row["name"])
                merged.append(row)
        return merged, min(dates) if dates else None


# ------------------------------------------------------- published kcal tables

# Every chain that publishes a PDF publishes the same shape: a dish name, its
# energy in kcal, then one symbol per allergen. What differs is the symbol set,
# how many columns are printed (some print a symbol for every allergen, some only
# for the ones that apply), and how the update date is written. So the parser is
# one function parameterised by those three things rather than one file per chain.
_DATE_PATTERNS = (
    re.compile(r"更新日\s*(\d{4})/(\d{1,2})/(\d{1,2})"),          # はま寿司
    re.compile(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日現在"),     # くら寿司
    re.compile(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日"),         # モスバーガー
    re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})\s*更新"),
)

# A published figure outside this range is a parse artefact, not a calorie: menu
# rows are single dishes and party platters, never five digits.
_KCAL_MIN, _KCAL_MAX = 1, 9999


def _find_date(text):
    for pattern in _DATE_PATTERNS:
        found = pattern.search(text)
        if found:
            return "{}-{:02d}-{:02d}".format(
                int(found.group(1)), int(found.group(2)), int(found.group(3)))
    return None


def kcal_table_parser(symbols, exact_columns=None):
    """A parser for one chain's `name kcal <allergen symbols>` PDF.

    `exact_columns` pins the number of trailing symbols when the chain prints one
    per allergen (はま寿司 prints 28). Left None when the chain only prints the
    symbols that apply (くら寿司), where the run is variable and may be empty.
    """
    symbol = f"[{re.escape(symbols)}]"
    run = (rf"(?:\s+{symbol}){{{exact_columns - 1}}}\s+{symbol}"
           if exact_columns else rf"(?:\s+{symbol})*")
    row = re.compile(rf"^(?P<name>.+?)\s+(?P<kcal>\d+){run}\s*$")

    def parse(blob):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(blob))
        rows, updated = [], None
        for page in reader.pages:
            text = page.extract_text() or ""
            if updated is None:
                updated = _find_date(text)
            for line in text.splitlines():
                match = row.match(line.strip())
                if not match:
                    continue
                name = match.group("name").strip()
                kcal = int(match.group("kcal"))
                if len(name) < 2 or not (_KCAL_MIN <= kcal <= _KCAL_MAX):
                    continue
                rows.append({"name": name, "energy_kcal": float(kcal)})
        return rows, updated

    return parse


# はま寿司 prints a symbol for all 28 allergens on every row.
parse_hamazushi = kcal_table_parser("●-△ー", exact_columns=28)
# くら寿司 prints only the allergens that apply, so the run is variable — and a
# plain dish with none at all is a bare `name kcal` line.
parse_kurasushi = kcal_table_parser("●▲△")


def parse_mosburger(blob):
    """Parse Mos Burger's official laboratory nutrition table.

    Contains dish name, weight, energy (kcal), protein (g), fat (g),
    carbohydrates (g), and salt equivalent (g).
    """
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(blob))
    rows, updated = [], None
    pattern = re.compile(
        r"^([^\d【]+?)\s+([\d\.]+)\s+(\d+)\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+).*?\s+([\d\.]+)$"
    )
    for page in reader.pages:
        text = page.extract_text() or ""
        if updated is None:
            updated = _find_date(text)
        for line in text.splitlines():
            m = pattern.match(line.strip())
            if not m:
                continue
            name = m.group(1).strip()
            kcal = float(m.group(3))
            protein = float(m.group(4))
            fat = float(m.group(5))
            carbs = float(m.group(6))
            salt = float(m.group(7))
            if len(name) < 2 or not (_KCAL_MIN <= kcal <= _KCAL_MAX):
                continue
            rows.append({
                "name": name,
                "energy_kcal": kcal,
                "protein_g": protein,
                "fat_g": fat,
                "carbohydrate_g": carbs,
                "salt_g": salt,
            })
    return rows, updated


CHAINS = {
    "hamazushi": Chain(
        key="hamazushi",
        shop_name="はま寿司",
        url=["https://images.zensho.co.jp/materials/hama-sushi/allergen/allergen.pdf",
             "https://images.zensho.co.jp/materials/hama-sushi/allergen/allergen_to.pdf"],
        source_page="https://www.hamazushi.com/menu/allergen/",
        parser=parse_hamazushi,
    ),
    "kurasushi": Chain(
        key="kurasushi",
        shop_name="くら寿司",
        url="https://www.kurasushi.co.jp/common/pdf/kura_allergen.pdf",
        source_page="https://www.kurasushi.co.jp/app/app_allergen.html",
        parser=parse_kurasushi,
    ),
    "mosburger": Chain(
        key="mosburger",
        shop_name="モスバーガー",
        url="https://www.mos.jp/menu/pdf/nutrition.pdf",
        source_page="https://www.mos.jp/menu/nutrition/",
        parser=parse_mosburger,
    ),
}


# ---------------------------------------------------------------- joining

# Decoration that differs between how a chain writes a dish on its menu and in
# its nutrition table: 「（関西・北陸限定）炙りとろサーモン」 vs 「炙りとろサーモン」.
# Deliberately light — both sides come from the SAME company, so the names are
# already close, and over-normalising is what turns a join into a wrong answer.
_JOIN_STRIP = re.compile(
    r"[（(\[【][^）)\]】]*[）)\]】]"          # bracketed regional/limited notes
    r"|[\s　・、,／/･]"                      # spacing and separators
    r"|[!！?？~〜\-–—]"                      # decorative punctuation
)


def name_key(name):
    """A comparable form of a dish name, for joining a menu row to a table row."""
    import unicodedata
    if not name:
        return ""
    key = unicodedata.normalize("NFKC", name)
    return _JOIN_STRIP.sub("", key).lower()


def import_chain(conn, chain, opener=None, fetched_at=None):
    """Load one chain's published nutrition and link it to that shop's menu rows.

    Returns a stats dict. Idempotent: re-running replaces the chain's rows, so a
    refreshed disclosure simply overwrites the old figures.
    """
    from ..database.site_schema import create_site_tables
    create_site_tables(conn)

    shop_rows = conn.execute("SELECT id FROM shops WHERE name = ?", (chain.shop_name,)).fetchall()
    if not shop_rows:
        raise ValueError(f"no shop named {chain.shop_name!r} in the corpus")
    shop_ids = [r[0] for r in shop_rows]
    primary_shop_id = shop_ids[0]

    rows, source_updated = chain.rows(chain.fetch(opener))
    stamp = fetched_at or datetime.date.today().isoformat()

    previous = {
        name: kcal for name, kcal in conn.execute(
            "SELECT name, energy_kcal FROM chain_nutrition WHERE shop_id = ?", (primary_shop_id,))
    }

    total_linked = total_exact = total_ambiguous = 0
    total_menu_items = 0

    for shop_id in shop_ids:
        conn.execute("UPDATE shop_menu_items SET chain_nutrition_id = NULL WHERE shop_id = ?",
                     (shop_id,))
        conn.execute("DELETE FROM chain_nutrition WHERE shop_id = ?", (shop_id,))
        for row in rows:
            conn.execute(
                """INSERT OR IGNORE INTO chain_nutrition
                   (shop_id, name, name_key, energy_kcal, source_url, source_page,
                    source_updated, fetched_at, protein_g, fat_g, carbohydrate_g, salt_g)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (shop_id, row["name"], name_key(row["name"]), row["energy_kcal"],
                 chain.url, chain.source_page, source_updated, stamp,
                 row.get("protein_g"), row.get("fat_g"), row.get("carbohydrate_g"), row.get("salt_g")))

        by_exact, by_key, ambiguous_keys = {}, {}, set()
        for row_id, name, key in conn.execute(
                "SELECT id, name, name_key FROM chain_nutrition WHERE shop_id = ?", (shop_id,)):
            by_exact.setdefault(name, row_id)
            if key in by_key and by_key[key] != row_id:
                ambiguous_keys.add(key)
            by_key[key] = row_id

        linked = exact = ambiguous = 0
        for item_id, name in conn.execute(
                "SELECT id, name FROM shop_menu_items WHERE shop_id = ?", (shop_id,)).fetchall():
            hit = by_exact.get(name)
            if hit:
                exact += 1
            else:
                key = name_key(name)
                if key in ambiguous_keys:
                    ambiguous += 1
                    continue
                hit = by_key.get(key)
            if hit:
                conn.execute("UPDATE shop_menu_items SET chain_nutrition_id = ? WHERE id = ?",
                             (hit, item_id))
                linked += 1

        total_linked += linked
        total_exact += exact
        total_ambiguous += ambiguous
        total_menu_items += conn.execute(
            "SELECT COUNT(*) FROM shop_menu_items WHERE shop_id = ?", (shop_id,)).fetchone()[0]

    conn.commit()

    current = {r["name"]: r["energy_kcal"] for r in rows}
    changed = sorted(
        (name, previous[name], kcal) for name, kcal in current.items()
        if name in previous and previous[name] != kcal)

    return {
        "chain": chain.key,
        "published_rows": len(rows),
        "menu_items": total_menu_items,
        "linked": total_linked,
        "linked_exact": total_exact,
        "ambiguous_skipped": total_ambiguous,
        "source_updated": source_updated,
        "was_empty": not previous,
        "added": sorted(set(current) - set(previous)),
        "removed": sorted(set(previous) - set(current)),
        "changed": changed,
    }


def chain_status(conn):
    """One row per chain we hold figures for: how many, how old, how stale.

    Staleness is measured from OUR fetch, not the chain's printed date: a chain
    that has revised its table since we last looked shows the old date on our
    pages until someone re-runs the import, and that gap is the only way a wrong
    calorie reaches a reader through this design.
    """
    today = datetime.date.today()
    out = []
    for row in conn.execute(
            """SELECT s.name, COUNT(cn.id) AS figures,
                      MIN(cn.fetched_at) AS fetched, MIN(cn.source_updated) AS published
               FROM chain_nutrition cn JOIN shops s ON s.id = cn.shop_id
               GROUP BY cn.shop_id ORDER BY s.name"""):
        age = None
        if row[2]:
            try:
                age = (today - datetime.date.fromisoformat(row[2])).days
            except ValueError:
                age = None
        out.append({"chain": row[0], "figures": row[1], "fetched_at": row[2],
                    "source_updated": row[3], "days_since_fetch": age})
    return out
