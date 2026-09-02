"""Compose the handover PDF from the captured screenshots.

    uv run python tools/capture_pages.py
    uv run python tools/build_handover.py
"""
import asyncio
import base64
import io
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

from playwright.async_api import async_playwright

DOC = Path("docs")
SHOTS = DOC / "screenshots"
DB = "data/metadata/dataset_manager.db"


def _test_count():
    """Read the real number out of the suite rather than hardcoding it."""
    try:
        # sys.executable, not "python": a bare python is a different
        # interpreter without the project's dependencies, and its partial run
        # reported a lower count than the suite actually has.
        out = subprocess.run([sys.executable, "-m", "unittest", "discover", "tests"],
                             capture_output=True, text=True, timeout=300)
        m = re.search(r"Ran (\d+) tests", out.stderr or out.stdout)
        return m.group(1) if m else "?"
    except Exception:
        return "?"


def stats():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    q = lambda s, *p: c.execute(s, p).fetchone()[0]
    out = {
        "pages": q("SELECT COUNT(*) FROM site_pages"),
        "pages_ja": q("SELECT COUNT(*) FROM site_pages WHERE lang='ja'"),
        "pages_en": q("SELECT COUNT(*) FROM site_pages WHERE lang='en'"),
        "foods": q("SELECT COUNT(*) FROM site_pages WHERE page_type='food'"),
        "dishes": q("SELECT COUNT(*) FROM site_pages WHERE page_type='dish'"),
        "nutrients": q("SELECT COUNT(*) FROM nutrients"),
        "items_total": q("SELECT COUNT(*) FROM items"),
        "off": q("SELECT COUNT(*) FROM items WHERE source='OpenFoodFacts'"),
        "tests": _test_count(),
        "sources": [dict(r) for r in c.execute(
            "SELECT source, COUNT(*) n FROM items GROUP BY source ORDER BY n DESC")],
    }
    c.close()
    return out


def img(name, max_w=1500):
    """Embed a screenshot, downscaled and JPEG-encoded.

    Captures are 2x device-scale PNGs; embedding them raw pushed the document
    past 19 MB once photographs were on the pages. At print width this is
    indistinguishable and roughly a tenth the size.
    """
    p = SHOTS / name
    if not p.exists():
        return ""
    try:
        from PIL import Image
    except ImportError:
        return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()
    im = Image.open(p).convert("RGB")
    if im.width > max_w:
        im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82, optimize=True, progressive=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


CSS = """
@page { size: A4; margin: 14mm 12mm; }
* { box-sizing: border-box; }
body { font-family: "Segoe UI", "Hiragino Kaku Gothic ProN", "Yu Gothic", sans-serif;
  color: #191D1A; font-size: 10.5pt; line-height: 1.55; margin: 0; }
h1 { font-size: 26pt; line-height: 1.15; margin: 0 0 6pt; letter-spacing: -0.02em; }
h2 { font-size: 14pt; margin: 0 0 6pt; border-bottom: 2px solid #191D1A; padding-bottom: 4pt; }
h3 { font-size: 11.5pt; margin: 0 0 3pt; }
p { margin: 0 0 7pt; }
code, .mono { font-family: "Consolas", monospace; font-size: 9.5pt; }
a { color: #C1521A; }
.cover { page-break-after: always; padding-top: 30mm; }
.cover .seal { width: 16pt; height: 16pt; background: #F26722; border-radius: 2pt; display: inline-block; }
.cover .sub { font-size: 12pt; color: #4A524C; max-width: 130mm; }
.meta { margin-top: 14mm; font-size: 9.5pt; color: #5C6660; }
.meta b { color: #191D1A; }
section { page-break-before: always; }
section.first { page-break-before: avoid; }
.shot { width: 100%; border: 1px solid #191D1A; border-radius: 2pt; margin: 5pt 0 3pt; }
.cap { font-size: 8.5pt; color: #8B938D; margin: 0 0 10pt; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4mm; }
table { width: 100%; border-collapse: collapse; font-size: 9.5pt; margin-bottom: 8pt; }
td, th { text-align: left; padding: 3pt 4pt; border-bottom: 1px solid #E4E6E0; }
th { border-bottom: 1.5px solid #191D1A; }
td:last-child, th:last-child { text-align: right; font-family: Consolas, monospace; }
.note { background: #FFF4EC; border-left: 3px solid #F26722; padding: 6pt 9pt; margin: 8pt 0; }
.warn { background: #FBF2E4; border-left: 3px solid #A05C17; padding: 6pt 9pt; margin: 8pt 0; }
ul { margin: 0 0 8pt; padding-left: 16pt; }
li { margin-bottom: 3pt; }
.url { font-family: Consolas, monospace; font-size: 9pt; color: #5C6660; }
"""


def page_section(s, first=False):
    return f"""
<section class="{'first' if first else ''}">
  <h2>{s['title']}</h2>
  <p class="url">{s['url']}</p>
  <p>{s['blurb']}</p>
  <img class="shot" src="{img(s['file'])}" alt="{s['title']}">
</section>"""


def build_html():
    shots = json.loads((DOC / "shots.json").read_text(encoding="utf-8"))
    st = stats()
    tests = st["tests"]
    src_rows = "".join(
        f"<tr><td>{r['source']}</td><td>{r['n']:,}</td></tr>" for r in st["sources"])

    cover = f"""
<div class="cover">
  <p><span class="seal"></span></p>
  <h1>calories.jp</h1>
  <p class="sub">A Japanese calorie and nutrition reference built on the
  official food composition tables, with a deterministic calculator, regional
  recipe data and an AI meal analyser.</p>
  <div class="meta">
    <p><b>Build handover</b> · 28 August 2026</p>
    <p>{st['pages']:,} public pages · {st['foods']:,} food pages ·
       {st['dishes']:,} dish pages · {st['nutrients']:,} nutrient measurements</p>
    <p>FastAPI · SQLite · Jinja2 · vanilla JS · WebGL · {tests} tests</p>
  </div>
</div>"""

    what = f"""
<section class="first">
  <h2>What this is</h2>
  <p>A public Japanese nutrition reference built on top of an existing dataset
  pipeline. The database was already there; this work turned it into a product —
  a searchable site with a calculator, comparison pages, regional recipe data and
  an AI meal analyser.</p>

  <h3>What makes it different</h3>
  <p>Competing calculators publish prose with hand-typed numbers. Every figure
  here is read live from a laboratory composition table, and the pages are
  generated from that data rather than written around it. Where a number is
  estimated rather than measured, the interface says so.</p>

  <div class="note">
    <b>The integrity rule.</b> A language model never produces a nutrition
    figure. It is used to translate names, read a photograph and match text to
    database rows. All arithmetic is deterministic Python or its JavaScript
    mirror, and both are unit-tested.
  </div>

  <h3>Where the data comes from</h3>
  <table>
    <tr><th>Source</th><th>Items</th></tr>{src_rows}
  </table>
  <div class="warn">
    <b>OpenFoodFacts is quarantined.</b> It is {st['off']:,} of
    {st['items_total']:,} rows and carries a share-alike database licence, so it
    is excluded from every public surface. The exclusion is structural rather
    than a filter: public pages are reachable only through the
    <span class="mono">site_pages</span> table, which is never populated for it.
    Japanese Wikipedia is excluded the same way for its share-alike terms.
  </div>

  <h3>How the site is built</h3>
  <p>The public site is server-rendered with Jinja2 inside the same FastAPI
  application that already served the JSON API, so the original endpoints and
  the internal React viewer still work unchanged. Interactivity — the serving
  calculator, meal totals, search suggestions, the atlas — is plain JavaScript
  with no framework and no build step. Pages render from indexed SQLite lookups
  on request.</p>
  <p>Offline commands prepare everything the site reads:
  <span class="mono">build-names</span> for display and English names,
  <span class="mono">build-pages</span> for URLs and metadata,
  <span class="mono">build-links</span> for recipe ingredient resolution,
  <span class="mono">build-search</span> for the full-text index and
  <span class="mono">build-sitemaps</span>. All are idempotent.</p>

  <h3>Language</h3>
  <p>The site is Japanese only. Pages live under <span class="mono">/</span>
  and a browser hitting the root is redirected there; anything under
  <span class="mono">/en/</span> now returns 404. The English interface strings,
  reference values and the official English names from FoodData Central are all
  still in the codebase and database — the second locale is one entry in
  <span class="mono">LANGS</span> away — but nothing routes to it, and the
  English names continue to serve as search aliases.</p>

  <h3>Look</h3>
  <p>The interface follows the Food Dash reference: a warm cream ground, orange
  accent, pill-shaped controls, and photographs set inside dashed circular
  frames. Measurements keep a tabular monospaced voice so data still reads as
  instrumentation rather than marketing.</p>
</section>"""

    pages = "".join(page_section(s) for s in shots)

    todo = """
<section>
  <h2>Imagery, and why it looks like this</h2>
  <p>There is no photograph library behind this project, and there is no honest
  way to conjure one: hotlinking someone else's food photography, or matching
  stock images to 2,600 composition-table entries by name, would put a picture
  of the wrong food above a set of exact numbers. So the pictures are made from
  the measurements instead.</p>
  <p>Every food page carries two generated marks. An <b>energy ring</b> splits
  the calories by protein, fat and carbohydrate. Beside it, a <b>nutrient
  fingerprint</b> draws one spoke per nutrient, each to the share of a daily
  reference value that 100 g supplies. Because it is computed, it discriminates:
  boiled udon averages a spoke length of 3.5, chicken liver 13.7, and dried
  hijiki is four times the mark of its own boiled state. Two foods with
  different compositions cannot produce the same image.</p>
  <p>The home page opens with the whole database as one picture — the PFC Atlas,
  every food positioned by its energy split, drawn in WebGL as a single call.
  Food groups carry their own colour and glyph throughout, drawn from the foods
  themselves rather than assigned arbitrarily.</p>
  <p>Stock photographs from Pexels appear on the six pages that hold no
  measurements — home, the three tools, the guide and the sources page — each in
  a dashed circular frame. No credits are shown; the Pexels licence does not
  require attribution. Alt text is written against the photograph that actually
  shipped, because search results match the query loosely.</p>
  <div class="note">
    <b>On video.</b> Embedding third-party video across thousands of pages means
    shipping content nobody here has watched, plus the tracking that comes with
    it. The place it would genuinely earn its keep is regional dish pages, where
    the ministry publishes its own material — worth doing per-dish against
    verified URLs, not as a blanket embed.
  </div>
</section>

<section>
  <h2>Built in this phase</h2>
  <ul>
    <li><b>Generated imagery.</b> Nutrient fingerprints and energy rings on
    every food page, food-group colour and glyph across the site.</li>
    <li><b>Editorial that is generated, not written.</b> The first guide —
    <i>what cooking does to calories</i> — ranks the 299 foods the table lists
    in more than one state by how much preparation shifts them. Every figure in
    it is a separate laboratory analysis rather than an estimate, which is
    exactly what the competing written guides cannot say. The same pattern
    extends to further guides from the same data.</li>
    <li><b>Rate limiting on the analyser.</b> A per-address hourly cap on calls
    that reach the vision model, configurable through
    <span class="mono">ANALYZER_RATE_LIMIT</span>. Cache hits are free and are
    not counted against it.</li>
  </ul>
</section>

<section>
  <h2>What is left</h2>

  <h3>Blocked on one key</h3>
  <p><span class="mono">GEMINI_API_KEY</span> is empty in
  <span class="mono">.env</span>. Setting it and re-running the builders
  unlocks three things at once: English pages for the 2,538 Japanese
  composition entries and 1,364 regional dishes, recipe-ingredient resolution
  so dish pages show computed nutrition, and the meal photo analyser. The
  English atlas also appears automatically once there are enough English food
  pages.</p>
  <p class="mono">uv run python main.py build-names &amp;&amp; build-pages &amp;&amp; build-links &amp;&amp; build-search &amp;&amp; build-sitemaps</p>

  <h3>Deliberate omissions</h3>
  <ul>
    <li><b>Accounts, saved meals, affiliate placements.</b> A product decision
    rather than a technical gap.</li>
    <li><b>Photographs.</b> Available honestly only through a properly licensed
    source with per-image attribution — Wikimedia Commons via the Wikidata
    entities already in the database is the realistic route, and it covers a
    fraction of the corpus.</li>
  </ul>

  <h3>Known data issues, deliberately untouched</h3>
  <ul>
    <li>FoodData Central rows are duplicated threefold from repeated import
    runs; page generation de-duplicates rather than deleting data.</li>
    <li>FoodKeeper categories are still numeric identifiers.</li>
    <li>Regional dish region values are free text rather than normalised
    prefectures; the item category is reliable and is what the site uses.</li>
  </ul>
</section>"""

    return f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{cover}{what}{pages}{todo}</body></html>"


async def main():
    html = build_html()
    src = DOC / "handover.html"
    src.write_text(html, encoding="utf-8")
    out = DOC / "calories-jp-handover.pdf"
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        await page.goto(src.resolve().as_uri(), wait_until="networkidle")
        await page.pdf(path=str(out), format="A4", print_background=True)
        await browser.close()
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    asyncio.run(main())
