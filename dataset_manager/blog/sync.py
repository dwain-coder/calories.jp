"""Pull posts from WordPress's REST API and store them.

No plugin needed: /wp-json/wp/v2/posts is core, and `_embed` brings the author
and the featured image along in the same request.

Post HTML is SANITISED before it is stored. WordPress is an authenticated editor
run by the site's own author, so this is not about distrusting the writer — it
is that a compromised WordPress would otherwise be able to put a <script> tag on
calories.jp, and the whole reason WP is kept off the domain is to make that
impossible. An allowlist is the only version of this that holds.
"""
import datetime
import os

import httpx
import nh3

from . import store

WP_URL = os.environ.get("WP_URL", "").rstrip("/")
TIMEOUT = float(os.environ.get("WP_TIMEOUT", "20"))

# When WordPress runs on the same host, WP_URL can point straight at it —
# http://127.0.0.1 — and WP_HOST carries the name its vhost answers to. That
# combination means WordPress needs no public DNS record, no certificate and no
# password wall, because nothing outside the machine can reach it at all. On a
# split deployment leave WP_HOST unset and WP_URL is used as written.
WP_HOST = os.environ.get("WP_HOST", "").strip()


def _headers():
    return {"Host": WP_HOST} if WP_HOST else None

# What a blog post may contain. No <script>, no <style>, no <iframe>, no event
# handlers — nh3 strips attributes it does not know, so this is a floor and not
# a filter that can be walked past.
TAGS = {
    "p", "br", "hr", "strong", "b", "em", "i", "u", "s", "mark", "small", "sub", "sup",
    "h2", "h3", "h4", "h5", "h6", "blockquote", "q", "cite",
    "ul", "ol", "li", "dl", "dt", "dd",
    "a", "img", "figure", "figcaption", "picture", "source",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption", "colgroup", "col",
    "code", "pre", "kbd", "samp", "abbr", "span", "div",
}
ATTRS = {
    # No "rel" here: nh3 sets it itself from link_rel, and refuses the
    # allowlist entry if both are given.
    "a": {"href", "title"},
    "img": {"src", "srcset", "alt", "width", "height", "loading", "decoding"},
    "source": {"srcset", "type", "media"},
    "th": {"scope", "colspan", "rowspan"},
    "td": {"colspan", "rowspan"},
    "abbr": {"title"},
    "span": {"class"},
    "div": {"class"},
    "figure": {"class"},
    "code": {"class"},
}


def clean(html):
    """Post HTML reduced to what a post may legitimately contain."""
    return nh3.clean(html or "", tags=TAGS, attributes=ATTRS,
                     url_schemes={"http", "https", "mailto"},
                     link_rel="noopener noreferrer")


def _text(node):
    return (node or {}).get("rendered", "") if isinstance(node, dict) else (node or "")


def _featured(post):
    """(url, alt) of the featured image, from the _embed payload."""
    for media in (post.get("_embedded") or {}).get("wp:featuredmedia") or []:
        if media.get("source_url"):
            return media["source_url"], media.get("alt_text") or ""
    return None, None


def _author(post):
    for a in (post.get("_embedded") or {}).get("author") or []:
        if a.get("name"):
            return a["name"]
    return None


def to_row(post, now):
    """One WordPress post as a row for the store."""
    url, alt = _featured(post)
    return {
        "wp_id": post["id"],
        "slug": post.get("slug") or str(post["id"]),
        "title": nh3.clean(_text(post.get("title")), tags=set()).strip(),
        "excerpt": nh3.clean(_text(post.get("excerpt")), tags=set()).strip() or None,
        "content_html": clean(_text(post.get("content"))),
        "author": _author(post),
        "image_url": url,
        "image_alt": alt,
        "published_at": post.get("date_gmt"),
        "modified_at": post.get("modified_gmt"),
        "synced_at": now,
    }


def fetch(base_url=None, per_page=100, client=None):
    """Every published post WordPress will hand over, as raw payloads."""
    base = (base_url or WP_URL).rstrip("/")
    if not base:
        raise RuntimeError("WP_URL is not set")
    owns = client is None
    client = client or httpx.Client(timeout=TIMEOUT, follow_redirects=True)
    try:
        out, page = [], 1
        while True:
            r = client.get(f"{base}/wp-json/wp/v2/posts",
                           params={"per_page": per_page, "page": page,
                                   "status": "publish", "_embed": "1"},
                           headers=_headers())
            # WordPress answers 400 for a page past the end rather than an empty
            # list, so that is the stop condition, not an error.
            if r.status_code == 400 and page > 1:
                break
            r.raise_for_status()
            batch = r.json()
            if not batch:
                break
            out.extend(batch)
            if len(batch) < per_page:
                break
            page += 1
        return out
    finally:
        if owns:
            client.close()


def sync(base_url=None, client=None):
    """Pull, sanitise, store, and drop anything WordPress no longer publishes."""
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    posts = fetch(base_url, client=client)
    rows = [to_row(p, now) for p in posts if p.get("id") and p.get("slug")]
    written = store.upsert(rows) if rows else 0
    removed = store.drop_missing([r["wp_id"] for r in rows]) if rows else 0
    return {"fetched": len(posts), "stored": written, "removed": removed}
