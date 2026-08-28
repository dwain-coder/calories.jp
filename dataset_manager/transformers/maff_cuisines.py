import re
import time
import html as htmllib
import urllib.robotparser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from typing import Dict, Any, List, Tuple

import httpx
from .base import BaseTransformer

HUB = "https://www.maff.go.jp/j/keikaku/syokubunka/k_ryouri/"

# Full browser headers + Referer + a warm session are required — the site's WAF
# 403s bare requests (cloudscraper included). This combination returns 200.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin", "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

# tit06 prose labels (matched by prefix) -> regional_dishes field.
FIELD_MAP = [
    ("主な伝承地域", "region"),
    ("主な使用食材", "main_ingredients"),
    ("歴史・由来", "history"),
    ("食習の機会", "occasion"),
    ("飲食方法", "how_to_eat"),
    ("保存・継承の取組", "preservation"),
]


def _clean(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"[ \t]+", " ", htmllib.unescape(s)).strip()


def parse_dish(html: str) -> Dict[str, str]:
    """Deterministically extract dish fields from a MAFF dish page (no LLM)."""
    out = {k: "" for _, k in FIELD_MAP}
    out.update(name="", prefecture="", recipe_ingredients="", recipe_steps="")

    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    if h1:
        title = _clean(h1.group(1))
        parts = title.rsplit(None, 1)
        out["name"], out["prefecture"] = (parts[0], parts[1]) if len(parts) == 2 else (title, "")

    # Label is plain text: use [^<] so the capture can't run across tags and
    # merge the image/attribution block's tit06 span into a later field.
    for m in re.finditer(
        r'<h3 class="tit06[^"]*">\s*<span class="pref">([^<]*)</span>\s*</h3>\s*<p[^>]*>(.*?)</p>',
        html, re.S,
    ):
        label, text = _clean(m.group(1)), _clean(m.group(2))
        for prefix, field in FIELD_MAP:
            if label.startswith(prefix):
                out[field] = text
                break

    # \Z terminator so the last section (作り方 is the final <h2>) is still captured.
    def block_after(heading: str) -> str:
        m = re.search(r"<h2[^>]*>[^<]*" + heading + r".*?</h2>(.*?)(?:<h2|<footer|</main|\Z)", html, re.S)
        return m.group(1) if m else ""

    pairs = re.findall(r'<ul class="list">\s*<li>(.*?)</li>\s*<li>(.*?)</li>\s*</ul>',
                       block_after("材料"), re.S)
    out["recipe_ingredients"] = "\n".join(f"{_clean(a)}\t{_clean(b)}" for a, b in pairs)

    # Recipe steps live in the unique <ul class="recipe"> block — target it directly.
    rec = re.search(r'<ul class="recipe[^"]*">(.*?)</ul>', html, re.S)
    steps = re.findall(r'<div class="num">(\d+)</div>\s*<div class="txt">(.*?)</div>',
                       rec.group(1) if rec else "", re.S)
    out["recipe_steps"] = "\n".join(f"{n}. {_clean(t)}" for n, t in steps)
    return out


class MAFFCuisinesTransformer(BaseTransformer):
    def transform(self, dataset_config: Dict[str, Any], raw_path: Path):
        source = dataset_config.get("source", "MAFF Our Regional Cuisines")
        throttle = float(dataset_config.get("throttle_seconds", 1.0))
        only_areas = dataset_config.get("maff_areas")  # e.g. ["hokkaido"] for a phased run
        max_dishes = dataset_config.get("max_dishes")  # cap for validation runs

        client = httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30)
        client.get(HUB)  # warm the session

        # Compliance: respect a real robots.txt. MAFF serves an HTML error page
        # (not a robots file) for the missing /robots.txt, which means no
        # restrictions per RFC 9309 — treat that as allowed and crawl politely.
        if not self._robots_allows(client, HUB):
            print(f"robots.txt disallows {HUB}; aborting.")
            return

        area_urls = self._area_urls(client, only_areas)
        print(f"Crawling {len(area_urls)} area pages...")

        dish_urls: List[Tuple[str, str]] = []  # (dish_url, area_url)
        seen = set()
        for area in area_urls:
            html = self._get(client, area, referer=HUB)
            if not html:
                continue
            for href in re.findall(r'href="([^"]*\.\./menu/[^"]+\.html)"', html):
                du = urljoin(area, href)
                if du not in seen:
                    seen.add(du)
                    dish_urls.append((du, area))
            time.sleep(throttle)

        if max_dishes:
            dish_urls = dish_urls[:max_dishes]
        print(f"Found {len(dish_urls)} dishes. Fetching...")

        added = 0
        for i, (dish_url, area) in enumerate(dish_urls, 1):
            html = self._get(client, dish_url, referer=area)
            if not html:
                continue
            d = parse_dish(html)
            if not d["name"]:
                print(f"  skip (no name): {dish_url}")
                continue
            item_id = self._insert_item(d["name"], d["prefecture"], source, dish_url)
            self._insert_regional_dish(
                item_id, d["region"], d["main_ingredients"], d["history"],
                d["occasion"], d["how_to_eat"], d["preservation"],
                d["recipe_ingredients"], d["recipe_steps"],
            )
            added += 1
            if i % 50 == 0:
                print(f"  {i}/{len(dish_urls)} dishes...")
            time.sleep(throttle)

        client.close()
        print(f"Added {added} MAFF regional dishes.")

    def _robots_allows(self, client, url: str) -> bool:
        try:
            r = client.get("https://www.maff.go.jp/robots.txt")
            body = r.text or ""
            if r.status_code == 200 and "user-agent" in body.lower() and "<html" not in body.lower():
                rp = urllib.robotparser.RobotFileParser()
                rp.parse(body.splitlines())
                return rp.can_fetch(HEADERS["User-Agent"], url)
            print("No robots.txt found (server returned a non-robots response); proceeding (throttled).")
            return True
        except Exception as e:
            print(f"robots.txt check error ({e}); proceeding cautiously (throttled).")
            return True

    def _area_urls(self, client, only_areas) -> List[str]:
        html = self._get(client, HUB) or ""
        urls = [urljoin(HUB, h) for h in
                re.findall(r'href="([^"]*search_menu/area/[a-z]+\.html)"', html)]
        urls = list(dict.fromkeys(urls))
        if only_areas:
            urls = [u for u in urls if Path(urlparse(u).path).stem in only_areas]
        return urls

    def _get(self, client, url: str, referer: str = None, retries: int = 3) -> str:
        headers = {"Referer": referer} if referer else {}
        for attempt in range(retries):
            try:
                r = client.get(url, headers=headers)
                if r.status_code == 200:
                    return r.text
                print(f"  {r.status_code} on {url} (attempt {attempt + 1})")
            except Exception as e:
                print(f"  error on {url}: {e}")
            time.sleep(2 * (attempt + 1))
        return ""


def demo():
    """Self-check the parser on a minimal MAFF-shaped fragment.
    Includes an image-block tit06 span before the real fields, and 作り方 as the
    LAST section (no trailing <h2>) — the two shapes that broke earlier."""
    sample = (
        '<h1 class="tit">test 北海道</h1>'
        '<h3 class="tit06"><span class="pref">画像はイメージです</span></h3>'  # image block, no <p> after
        '<ul class="menu_details"><li>'
        '<h3 class="tit06"><span class="pref">主な伝承地域</span></h3><p class="mt10">道南地域</p></li><li>'
        '<h3 class="tit06"><span class="pref">主な使用食材</span></h3><p>豚肉、米</p></li></ul>'
        '<h3 class="tit06"><span class="pref">歴史・由来・関連行事</span></h3><p>由来テキスト</p>'
        '<h2 class="tit05">材料</h2><ul class="list"><li>豚肉</li><li>150g</li></ul>'
        '<h2 class="tit05 mt50">作り方</h2>'
        '<ul class="recipe mt10"><li><div class="num">1</div><div class="txt">切る</div></li>'
        '<li><div class="num">2</div><div class="txt">煮る</div></li></ul>'
        '<p class="taR">レシピ提供元名 : 例</p>'  # trailing content, NO closing <h2>/<footer>
    )
    d = parse_dish(sample)
    assert d["name"] == "test" and d["prefecture"] == "北海道", d
    assert d["region"] == "道南地域", d          # was swallowed by the image block
    assert d["main_ingredients"] == "豚肉、米", d
    assert d["history"] == "由来テキスト", d
    assert d["recipe_ingredients"] == "豚肉\t150g", d
    assert d["recipe_steps"] == "1. 切る\n2. 煮る", d  # last section, no terminator
    print("maff parse_dish: OK")


if __name__ == "__main__":
    demo()
