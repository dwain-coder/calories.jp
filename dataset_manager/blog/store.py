"""Where posts live, and why it is not the database everything else uses.

The corpus ships inside the Docker image: 34 MB of composition tables that only
change when someone runs an ingest and deploys. Posts do not work that way — a
post is published from a browser and should be live in seconds — so they need a
file that survives a deploy and can be written at runtime.

BLOG_DB_PATH points at it. On Railway that is a mounted volume; locally it is
just a file under data/. If the file cannot be opened at all the site still
serves: /blog renders empty rather than 500ing, because a blog is the least
important thing on a nutrition site and must never be able to take it down.
"""
import os
import sqlite3
from pathlib import Path

DB_PATH = os.environ.get("BLOG_DB_PATH", "data/metadata/blog.db")

DDL = [
    """CREATE TABLE IF NOT EXISTS posts (
        wp_id INTEGER PRIMARY KEY,
        slug TEXT NOT NULL UNIQUE,
        title TEXT NOT NULL,
        excerpt TEXT,
        content_html TEXT NOT NULL,
        author TEXT,
        image_url TEXT,
        image_alt TEXT,
        published_at TEXT,
        modified_at TEXT,
        synced_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_posts_published ON posts(published_at DESC)",
]


def connect(readonly=False):
    """A connection to the post store, creating it on first use.

    Returns None when the file is unreachable — a read-only filesystem, a volume
    that has not mounted — so callers can degrade instead of failing.
    """
    try:
        path = Path(DB_PATH)
        if not readonly:
            path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        if not readonly:
            for stmt in DDL:
                conn.execute(stmt)
            conn.commit()
        return conn
    except (sqlite3.Error, OSError):
        return None


def recent(limit=30):
    """Published posts, newest first."""
    conn = connect(readonly=True)
    if conn is None:
        return []
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM posts ORDER BY published_at DESC LIMIT ?", (limit,))]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def by_slug(slug):
    conn = connect(readonly=True)
    if conn is None:
        return None
    try:
        row = conn.execute("SELECT * FROM posts WHERE slug = ?", (slug,)).fetchone()
        return dict(row) if row else None
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def slugs():
    """Every post slug, for the sitemap."""
    conn = connect(readonly=True)
    if conn is None:
        return []
    try:
        return [r[0] for r in conn.execute(
            "SELECT slug FROM posts ORDER BY published_at DESC")]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def upsert(posts):
    """Replace the stored copy of each post. Returns how many were written."""
    conn = connect()
    if conn is None:
        return 0
    try:
        conn.executemany(
            """INSERT INTO posts (wp_id, slug, title, excerpt, content_html, author,
                                  image_url, image_alt, published_at, modified_at, synced_at)
               VALUES (:wp_id, :slug, :title, :excerpt, :content_html, :author,
                       :image_url, :image_alt, :published_at, :modified_at, :synced_at)
               ON CONFLICT(wp_id) DO UPDATE SET
                   slug = excluded.slug, title = excluded.title,
                   excerpt = excluded.excerpt, content_html = excluded.content_html,
                   author = excluded.author, image_url = excluded.image_url,
                   image_alt = excluded.image_alt,
                   published_at = excluded.published_at,
                   modified_at = excluded.modified_at, synced_at = excluded.synced_at""",
            posts)
        conn.commit()
        return len(posts)
    finally:
        conn.close()


def drop_missing(keep_ids):
    """Remove posts WordPress no longer publishes.

    Unpublishing in WordPress has to unpublish here too, or a deleted post stays
    up forever on a site the author cannot edit.
    """
    conn = connect()
    if conn is None or not keep_ids:
        if conn:
            conn.close()
        return 0
    try:
        marks = ",".join("?" * len(keep_ids))
        n = conn.execute(f"DELETE FROM posts WHERE wp_id NOT IN ({marks})",
                         tuple(keep_ids)).rowcount
        conn.commit()
        return n
    finally:
        conn.close()
