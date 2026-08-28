# Stock imagery

Landing and tool pages only — the home page, meal calculator, analyzer, goals,
guides and sources. **Never** food, dish or nutrient pages: a photograph beside
an exact measurement implies it depicts that exact entry, and no stock library
can honestly do that across a composition table of thousands of rows.

Expected files (any that are missing simply do not render):

    home-hero.jpg        meal-calculator.jpg    analyzer.jpg
    goals.jpg            guide-cooking.jpg      sources.jpg

A matching `.webp` beside a `.jpg` is served in preference to it.

## Populating

    set PEXELS_API_KEY=...
    uv run python tools/fetch_stock.py

That downloads one landscape photo per slot and writes the photographer credit
into `dataset_manager/site/media.py`. To use your own or AI-generated images,
drop the files in with these names and fill in `credit` yourself.

Wide crops: the boxes are 21:8 on desktop and 16:9 on mobile, so pick images
that survive a letterbox. `focus` in media.py biases the crop.

## Video

Same rule as photographs: landing and tool pages only, never a data page.

Two kinds, declared in `VIDEO` in `dataset_manager/site/media.py`:

- **`file`** — an MP4 here, served from our own origin. No third-party request,
  no cookies, no consent banner. Best for short ambient loops (under ~20s,
  ≤1280px). Rendered muted and looping, with playback started by `ambient.js`
  only when the viewer has not asked for reduced motion.
  Populate with `tools/fetch_stock_video.py` (needs `PEXELS_API_KEY`).

- **`url`** — a third-party embed, for when the content itself is the point.
  Give the **embed** URL, not the watch page, and prefer the no-cookie host:
  `https://www.youtube-nocookie.com/embed/VIDEO_ID`

A slot with a video shows it instead of the still; the still becomes its poster
frame. A slot whose file is missing falls back to the photograph.
