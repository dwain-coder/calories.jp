"""Find a photograph of a dish, from Wikidata first and Commons second.

Two sources, in that order, because they fail differently.

**Wikidata P18** is a statement that a particular image depicts a particular
thing, made by an editor. It is right about 10% of these dishes and essentially
never wrong.

**A Commons text search** covers far more, and is wrong in ways that matter: the
third result for 「ジンギスカン」 is a portrait of Genghis Khan, and the first for
「けの汁」 is a different soup entirely. So a search hit is only accepted when the
dish's own Japanese name appears in the file's title, its description or its
categories. That is deliberately strict — it also rejects correct images titled
in romaji (「Jingisukan japanese mutton barbecue.jpg」) — because a page with no
photograph is fine and a page with the wrong photograph is not.

Only free licences are stored. Anything whose licence string this module does
not recognise is skipped rather than guessed at.
"""
import html
import re
import time

import httpx

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
JA_WIKIPEDIA_API = "https://ja.wikipedia.org/w/api.php"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"

# Wikimedia asks that automated clients identify themselves and say where to
# complain. Anonymous bulk requests get blocked, and fairly.
USER_AGENT = "calories.jp/1.0 (https://calories.jp; nutrition reference site)"

# Licences we may republish with attribution. Everything else — "Fair use",
# non-commercial variants, anything unparsed — is skipped.
FREE_LICENCES = (
    "cc0", "cc-zero", "public domain", "pd-", "cc by", "cc-by",
)
NON_FREE_MARKERS = ("non-commercial", "noncommercial", "-nc", "fair use", "nd")

# Wikimedia's own guidance: no more than one request at a time from a client.
REQUEST_PAUSE = 0.4


def _plain(value):
    """extmetadata fields arrive as HTML fragments."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"(?s)<[^>]+>", " ", value or ""))).strip()


def is_free(licence):
    """Whether a Commons licence string is one we may republish under."""
    if not licence:
        return False
    low = licence.lower()
    if any(bad in low for bad in NON_FREE_MARKERS):
        return False
    return any(good in low for good in FREE_LICENCES)


def _client(client=None):
    return client or httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT},
                                  follow_redirects=True)


def _describe(page):
    """One Commons search result, flattened, or None if it is not usable."""
    info = (page.get("imageinfo") or [{}])[0]
    meta = info.get("extmetadata") or {}
    licence = _plain((meta.get("LicenseShortName") or {}).get("value"))
    if not is_free(licence):
        return None
    thumb = info.get("thumburl") or info.get("url")
    if not thumb:
        return None
    title = page.get("title", "")
    haystack = " ".join([
        title,
        _plain((meta.get("ObjectName") or {}).get("value")),
        _plain((meta.get("ImageDescription") or {}).get("value")),
        _plain((meta.get("Categories") or {}).get("value")),
    ])
    credit = (_plain((meta.get("Artist") or {}).get("value"))
              or _plain((meta.get("Credit") or {}).get("value")) or "")
    if not credit:
        # CC BY and CC BY-SA require naming the author. A file that does not say
        # who took it cannot be published under them, so it is skipped rather
        # than shown uncredited. CC0 and public-domain files ask for nothing, so
        # the source alone is an honest caption.
        low = licence.lower()
        if any(k in low for k in ("cc0", "cc-zero", "public domain", "pd-")):
            credit = "Wikimedia Commons"
        else:
            return None

    return {
        "title": title,
        "url": thumb,
        "page_url": info.get("descriptionurl"),
        "width": info.get("thumbwidth") or info.get("width"),
        "height": info.get("thumbheight") or info.get("height"),
        "licence": licence,
        "licence_url": _plain((meta.get("LicenseUrl") or {}).get("value")) or None,
        "credit": credit,
        "haystack": haystack,
    }


# Kana and kanji. Japanese has no spaces, so a name found inside a longer run of
# them is usually a different word: 「あずま」 inside 「あずまや」 is a garden gazebo,
# not the dish.
# U+30FB (・) sits inside the katakana block but separates words rather than
# joining them, so it is excluded; U+30FC (ー) is kept, because ラーメン needs it.
_JA_CHAR = re.compile(r"[぀-ヺー-ヿ一-鿿々]")

# Below this, a name matches too much to mean anything: 「もち」 appears inside
# every mochi ever uploaded. Short names are left to the two sources that do not
# guess — the Wikipedia article and the Wikidata statement.
MIN_SEARCH_NAME = 3

# At or below this length, a name must also be preceded by something that is
# not Japanese — see names_the_dish.
SHORT_NAME = 3


def names_the_dish(name, title):
    """Whether `title` names this dish rather than merely containing its letters.

    Checked against the file TITLE only. A match in a description or a category
    was too loose in practice — it put a photograph of a bento box on 「いもたこ」 —
    and a title is what an uploader chose to call the thing in the picture.
    """
    # A two-character name is a word fragment in a text search, not a dish.
    if not name or not title or len(name) < MIN_SEARCH_NAME:
        return False
    start = 0
    while True:
        at = title.find(name, start)
        if at < 0:
            return False
        after = title[at + len(name):at + len(name) + 1]
        before = title[at - 1] if at > 0 else ""
        # What FOLLOWS always matters. A Japanese compound is headed by its last
        # element, so a qualifier in front leaves the dish itself: 「醤油ラーメン」
        # is ramen. Characters after it change the head into something else:
        # 「あずまや」 is a garden gazebo, not the dish 「あずま」.
        ends_cleanly = not _JA_CHAR.match(after or " ")
        # For a SHORT name, what precedes matters too. Three characters of kana
        # land inside unrelated compounds often enough to matter: 「あずま」 inside
        # 「紅あずま」 is a sweet-potato cultivar, 「ならえ」 inside 「右へならえ」 was a
        # photograph of military equipment. Long names do not need this, and it
        # would cost them real matches like 「信州木島平笹ずし」.
        starts_cleanly = (len(name) > SHORT_NAME
                          or not _JA_CHAR.match(before or " "))
        if ends_cleanly and starts_cleanly:
            return True
        start = at + 1


def search_commons(name, client=None, limit=6, width=800):
    """Free-licensed Commons images whose own text mentions this dish by name."""
    owns = client is None
    client = _client(client)
    try:
        r = client.get(COMMONS_API, params={
            "action": "query", "generator": "search",
            "gsrsearch": f"filetype:bitmap {name}", "gsrnamespace": 6,
            "gsrlimit": limit, "prop": "imageinfo",
            "iiprop": "url|extmetadata|size", "iiurlwidth": width, "format": "json",
        })
        r.raise_for_status()
        pages = (r.json().get("query") or {}).get("pages") or {}
    except (httpx.HTTPError, ValueError):
        return []
    finally:
        if owns:
            client.close()

    out = []
    for page in pages.values():
        hit = _describe(page)
        # The guard. Without it the site publishes a portrait of a 13th-century
        # emperor as a photograph of grilled lamb, and a garden gazebo as 「あずま」.
        if hit and names_the_dish(name, hit["title"]):
            hit["matched_on"] = "commons-name"
            out.append(hit)
    return out


def wikidata_images(names, client=None, chunk=80):
    """{dish name: Commons file title} for dishes that have a P18 statement."""
    owns = client is None
    client = _client(client)
    found = {}
    try:
        names = [n for n in names if n and '"' not in n and "\\" not in n]
        for i in range(0, len(names), chunk):
            batch = names[i:i + chunk]
            values = " ".join(f'"{n}"@ja' for n in batch)
            query = ("SELECT ?label ?image WHERE { VALUES ?label { %s } "
                     "?item rdfs:label ?label ; wdt:P18 ?image . }" % values)
            try:
                r = client.get(WIKIDATA_SPARQL, params={"query": query, "format": "json"},
                               headers={"Accept": "application/sparql-results+json"})
                r.raise_for_status()
                for row in r.json()["results"]["bindings"]:
                    found.setdefault(row["label"]["value"],
                                     row["image"]["value"].rsplit("/", 1)[-1])
            except (httpx.HTTPError, ValueError, KeyError):
                continue
            time.sleep(REQUEST_PAUSE)
    finally:
        if owns:
            client.close()
    return found


def wikipedia_lead_images(names, client=None, chunk=20):
    """{dish name: Commons file title} from the Japanese Wikipedia article.

    An article titled 「けの汁」 is about that dish, and its lead image was chosen
    by an editor to show it — the same kind of assertion as a Wikidata P18
    statement, and twice as well covered. Only the image is taken; the article
    text is CC BY-SA and is not used.

    Redirects are followed, so 「ちゃんぽん」 landing on a canonical title still
    resolves, and the ORIGINAL name is kept as the key.
    """
    owns = client is None
    client = _client(client)
    found = {}
    try:
        names = [n for n in names if n]
        for i in range(0, len(names), chunk):
            batch = names[i:i + chunk]
            try:
                r = client.get(JA_WIKIPEDIA_API, params={
                    "action": "query", "prop": "pageimages", "titles": "|".join(batch),
                    "piprop": "name", "format": "json", "redirects": 1,
                })
                r.raise_for_status()
                payload = r.json().get("query") or {}
            except (httpx.HTTPError, ValueError):
                continue
            # A redirect changes the title, so map the canonical title back to
            # the name we asked about before recording the hit — but only when
            # the redirect is about spelling.
            #
            # 「たこ飯」 redirects to 「たこめし」: the same dish written differently,
            # so the article's photograph is a photograph of it.
            #
            # 「静岡おでん」 redirects to 「おでん」 because Wikipedia has no separate
            # article, not because they are the same thing. Taking the general
            # article's picture put one generic bowl of oden on 静岡おでん, 姫路おでん
            # and 味噌おでん alike — and the regional difference is the whole
            # reason those pages exist. A target contained in the name it came
            # from is a broader subject, and is dropped.
            asked = set(batch)
            # A title can serve several of the names we asked about: 「たこめし」 is
            # both a name in this batch and where 「たこ飯」 redirects to, so both
            # earn the image and a single title->name mapping would drop one.
            serves = {}
            for r in payload.get("normalized", []):
                serves.setdefault(r["to"], []).append(r["from"])
            for r in payload.get("redirects", []):
                if r["to"] in r["from"]:
                    continue
                serves.setdefault(r["to"], []).append(r["from"])
            for page in (payload.get("pages") or {}).values():
                image = page.get("pageimage")
                if not image:
                    continue
                title = page.get("title")
                for name in [title, *serves.get(title, [])]:
                    if name in asked:
                        found.setdefault(name, image)
            time.sleep(REQUEST_PAUSE)
    finally:
        if owns:
            client.close()
    return found


def commons_file(filename, client=None, width=800, matched_on="wikidata-p18"):
    """One Commons file by name, with its licence.

    Used for the two sources that name a file directly, so there is no name
    guard here — something has already asserted that this image is of this
    dish. The licence check still applies.
    """
    from urllib.parse import unquote
    owns = client is None
    client = _client(client)
    try:
        r = client.get(COMMONS_API, params={
            "action": "query", "titles": f"File:{unquote(filename)}",
            "prop": "imageinfo", "iiprop": "url|extmetadata|size",
            "iiurlwidth": width, "format": "json",
        })
        r.raise_for_status()
        pages = (r.json().get("query") or {}).get("pages") or {}
    except (httpx.HTTPError, ValueError):
        return None
    finally:
        if owns:
            client.close()
    for page in pages.values():
        hit = _describe(page)
        if hit:
            # Wikidata asserts this image depicts this dish, so no name guard.
            hit["matched_on"] = matched_on
            return hit
    return None
