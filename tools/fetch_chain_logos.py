"""A real logo for each chain, where one is freely licensed.

    uv run python tools/fetch_chain_logos.py            # dry run, prints what it found
    uv run python tools/fetch_chain_logos.py --apply

The coloured tile with a kana mark says 「ス」 where a reader expects the Sushiro
logo. A drawn approximation of the arches is worse than either: it is neither
the mark nor honestly not-the-mark.

Wikidata's P154 is "logo image" — an editor's assertion that this file is that
organisation's logo — and ja.wikipedia hosts no fair-use files at all, so
anything reachable this way is already free to republish. Most Japanese chain
logos are on Commons as PD-textlogo: a wordmark in a plain typeface is below the
threshold of originality and carries no copyright. The TRADE MARK still belongs
to the company, which is what /terms says and why the takedown offer is there.

Nothing is guessed. A chain with no P154 keeps its tile.
"""
import argparse
import datetime
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from dataset_manager.images import wikimedia  # noqa: E402

DB = "data/metadata/dataset_manager.db"
OUT = Path("static/media/logos")

DDL = """CREATE TABLE IF NOT EXISTS chain_logos (
    chain TEXT PRIMARY KEY,
    file TEXT NOT NULL,
    page_url TEXT,
    licence TEXT NOT NULL,
    credit TEXT,
    fetched_at TEXT NOT NULL
)"""

# A logo is wider than it is tall far more often than not, and these are shown
# at 38px in a header badge. 320 keeps them crisp on a 2x display without
# pulling a 4MB SVG rasterisation for every chain.
WIDTH = 320


def logo_files(names, client, chunk=60):
    """{chain name: Commons file title} for chains with a P154 statement."""
    found = {}
    names = [n for n in names if n and '"' not in n and "\\" not in n]
    for i in range(0, len(names), chunk):
        batch = names[i:i + chunk]
        values = " ".join(f'"{n}"@ja' for n in batch)
        query = ("SELECT ?label ?logo WHERE { VALUES ?label { %s } "
                 "?item rdfs:label ?label ; wdt:P154 ?logo . }" % values)
        try:
            r = client.get(wikimedia.WIKIDATA_SPARQL,
                           params={"query": query, "format": "json"},
                           headers={"Accept": "application/sparql-results+json"})
            r.raise_for_status()
            for row in r.json()["results"]["bindings"]:
                found.setdefault(row["label"]["value"],
                                 row["logo"]["value"].rsplit("/", 1)[-1])
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            print(f"  ! wikidata batch failed: {exc}")
        time.sleep(wikimedia.REQUEST_PAUSE)
    return found


def download(hit, chain, apply):
    """Save the rendered logo next to the bundled dish photographs."""
    # Commons renders an SVG thumbnail as PNG and leaves a JPG a JPG, so take
    # the extension from what it actually served rather than assuming.
    suffix = Path(hit["url"].split("?")[0]).suffix.lower()
    if suffix not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        suffix = ".png"
    dest = OUT / f"{chain}{suffix}"
    if not apply:
        return f"/static/media/logos/{dest.name}"
    OUT.mkdir(parents=True, exist_ok=True)
    r = httpx.get(hit["url"], follow_redirects=True,
                  headers={"User-Agent": wikimedia.USER_AGENT}, timeout=60)
    r.raise_for_status()
    dest.write_bytes(r.content)
    return f"/static/media/logos/{dest.name}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute(DDL)
    chains = [r[0] for r in conn.execute(
        "SELECT DISTINCT name FROM shops WHERE name IS NOT NULL ORDER BY name")]
    print(f"{len(chains)} chains")

    client = wikimedia._client()
    try:
        files = logo_files(chains, client)
        print(f"{len(files)} have a Wikidata logo statement\n")
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        kept = skipped = 0
        for chain, filename in sorted(files.items()):
            hit = wikimedia.commons_file(filename, client=client, width=WIDTH,
                                         matched_on="wikidata-p154")
            time.sleep(wikimedia.REQUEST_PAUSE)
            if not hit:
                print(f"  {chain:16} SKIP  not freely licensed: {filename[:44]}")
                skipped += 1
                continue
            path = download(hit, chain, args.apply)
            if args.apply:
                conn.execute(
                    """INSERT OR REPLACE INTO chain_logos
                       (chain, file, page_url, licence, credit, fetched_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (chain, path, hit.get("page_url"), hit["licence"],
                     hit.get("credit"), now))
            print(f"  {chain:16} {hit['licence'][:28]:30} {filename[:40]}")
            kept += 1
        conn.commit()
        print(f"\n{kept} logos, {skipped} skipped as non-free, "
              f"{len(chains) - len(files)} chains keep their tile")
        if not args.apply:
            print("\nDry run. Nothing written. Re-run with --apply.")
    finally:
        client.close()
        conn.close()


if __name__ == "__main__":
    main()
