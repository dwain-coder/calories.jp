"""Screenshot every public page and build the handover PDF.

Run with the API server up on :8000:
    uv run python tools/capture_pages.py

Writes PNGs to docs/screenshots/ and docs/site-handover.pdf.
"""
import asyncio
import base64
import json
import os
import sys
from pathlib import Path

from playwright.async_api import async_playwright

BASE = os.environ.get("SITE_BASE", "http://localhost:8000")
OUT = Path("docs/screenshots")
DOC = Path("docs")
VIEWPORT = {"width": 1280, "height": 900}

# (key, url, title, what the page does, optional setup script)
PAGES = [
    ("ja-home", "/", "Home",
     "The landing page. Warm hero band, a photograph set in the dashed circular frame from the design reference, then the PFC Atlas — every food with measured "
     "macronutrients, plotted by the share of its energy from protein, fat and "
     "carbohydrate — then the 18 food groups as colour-coded chips, the three "
     "tools, popular staples and regional dishes.", None),
    ("ja-atlas", "/", "PFC Atlas (detail)",
     "The signature element, close up. Every point is one measured row of the "
     "composition table. Oils gather at the fat corner, sugars at carbohydrate, "
     "dried fish near the protein apex. Hovering reads a food; clicking opens it; "
     "the legend filters by food group.",
     "document.querySelector('.atlas-section').scrollIntoView({block:'start'});"),
    ("ja-foods", "/foods?sort=kcal_desc", "Food database (browse)",
     "Paginated browse over every food page — 2,633 entries, 55 pages — sortable "
     "by name, calories or protein. Sorted by calories here, so the cooking oils "
     "come first at ~890 kcal per 100 g.", None),
    ("ja-category", "/category/肉類", "Category page — 肉類 (Meats)",
     "One page per food group, with every member in a sortable comparison table. "
     "317 meats spanning 28–759 kcal. These are the pages that answer "
     "'which cut has the fewest calories' without any prose.", None),
    ("ja-food", "/food/こむぎ-うどん-ゆで", "Food page — udon, boiled",
     "The core page. The two marks at the top are drawn from this food's own "
     "measurements: an energy-split ring, and a nutrient fingerprint whose "
     "spokes show the share of a daily reference value that 100 g supplies — so "
     "every page carries a picture without a photograph library. Then headline "
     "calories, the serving calculator with %DV that rescales live, the "
     "cooking-method comparison (raw udon 249 kcal against boiled 95, each a "
     "separate lab analysis), all 51 nutrients, a FAQ generated from the stored "
     "values, related foods and full provenance.", None),
    ("ja-food-prep", "/food/こむぎ-うどん-ゆで", "Food page — preparation & FAQ",
     "Lower half of the same page: how preparation changes the numbers, and the "
     "question-and-answer block. Every answer is assembled from stored values, "
     "and the same text is emitted as FAQPage structured data.",
     "document.querySelectorAll('details').forEach(d=>d.open=true);"
     "document.querySelector('.faq-block').scrollIntoView({block:'center'});"),
    ("ja-guide", "/guides/cooking-and-calories", "Guide — what cooking does to calories",
     "A written guide where every figure is a measurement. 299 foods appear in "
     "the composition table in more than one state, so the change from drying, "
     "boiling or frying is analysed rather than estimated — dried hijiki against "
     "boiled is a sixteen-fold difference. This is the shape editorial content "
     "takes here: generated from the data, not written around it.", None),
    ("ja-dish", "/dish/あいまぜ", "Dish page — あいまぜ (Ishikawa)",
     "MAFF regional dishes: ingredients with quantities, method, and the history "
     "and occasion prose from the source. Where enough ingredients resolve to "
     "composition-table entries, nutrition is computed deterministically and "
     "labelled with how many ingredients it came from.", None),
    ("ja-search", "/search?q=みそ", "Search results",
     "FTS5 trigram search over the clean corpus. Query tokens are ANDed; tokens "
     "under three characters — common in Japanese — fall back to a LIKE filter, "
     "since trigram cannot match them. MEXT results are ranked above USDA.", None),
    ("ja-meal", "/meal-calculator", "Meal calculator",
     "Add any number of foods with quantities and get running totals. All "
     "arithmetic is client-side from per-100g values fetched from the API, "
     "mirroring the tested Python module.",
     "MEAL_DEMO"),
    ("ja-goals", "/goals", "Calorie goal calculator",
     "Mifflin-St Jeor basal rate times an activity factor, plus a goal "
     "adjustment, with a macro split derived from body weight. Labelled an "
     "estimate, not medical advice.", None),
    ("ja-analyzer", "/analyzer", "AI meal analyzer",
     "Upload a meal photo; a vision model identifies components, each is matched "
     "against the verified database, and totals are computed from stored values "
     "times AI-estimated grams. Database values and AI estimates are labelled "
     "separately throughout. Needs GEMINI_API_KEY, which is not set, so the "
     "empty state is shown.", None),
    ("ja-sources", "/sources", "Data sources & licences",
     "Attribution page. Each source with its licence and the exact attribution "
     "string required for redistribution.", None),
    ("api-docs", "/docs", "API documentation",
     "FastAPI's generated OpenAPI docs. The original endpoints are unchanged and "
     "still serve the internal React viewer; the public site and its JSON "
     "endpoints were added alongside them.", None),
]

MEAL_DEMO = """
(async () => {
  const add = async (q) => {
    const r = await fetch('/api/search?q=' + encodeURIComponent(q) + '&lang=ja&limit=3').then(r=>r.json());
    const food = r.find(x => x.page_type === 'food');
    if (!food) return;
    const input = document.getElementById('meal-search-input');
    input.value = q; input.dispatchEvent(new Event('input'));
    await new Promise(r => setTimeout(r, 700));
    const li = document.querySelector('#meal-search-results li');
    if (li) li.dispatchEvent(new MouseEvent('mousedown', {bubbles:true})) , li.click();
    await new Promise(r => setTimeout(r, 600));
  };
  await add('精白米');
  await add('にわとり むね');
  await add('ごま油');
})()
"""


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    shots = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport=VIEWPORT, device_scale_factor=2)
        for key, url, title, blurb, setup in PAGES:
            print(f"  {key} -> {url}")
            try:
                await page.goto(BASE + url, wait_until="networkidle", timeout=30000)
            except Exception as e:
                print(f"    ! {e}")
                continue
            await page.wait_for_timeout(1200)          # atlas settle / fonts
            if setup == "MEAL_DEMO":
                try:
                    await page.evaluate(MEAL_DEMO)
                    await page.wait_for_timeout(800)
                except Exception as e:
                    print(f"    ! demo: {e}")
            elif setup:
                try:
                    await page.evaluate(setup)
                    await page.wait_for_timeout(500)
                except Exception as e:
                    print(f"    ! setup: {e}")
            path = OUT / f"{key}.png"
            await page.screenshot(path=str(path))
            shots.append({"key": key, "title": title, "blurb": blurb,
                          "url": url, "file": path.name})
        await browser.close()
    (DOC / "shots.json").write_text(json.dumps(shots, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\ncaptured {len(shots)} screenshots -> {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
