#!/usr/bin/env python3
"""Splits the bundled catalog into one downloadable package per songbook.

Reads assets/catalog/catalog.json and writes tool/out/books/<id>.json, one
file per distinct `book` value, plus diverse.json with every bookless song
(they land in the Library's "Diverse" tail, so their `book` stays ""). Songs
are copied verbatim, so each package shows up in the app exactly like the
bundled catalog does today.

The manifest books.json mirrors collections.json (same schema, top-level key
"collections", parsed by CollectionsStore.parseManifest unchanged) and lists
the books in the Library's order (lib/utils/book_order.dart: priority books
first by prefix, the rest alphabetically, Diverse last).

Each entry carries `sha256`, the fingerprint of its published file, and a
`generated` that moves only when the book's content does (write_package()).
Both come from the PREVIOUS manifest, read from tool/out/books/books.json:
the weekly workflow downloads the published one there before this runs, and
a manual run must do the same, or every book gets today's date.

Output: tool/out/books/*.json
Upload, the books first and books.json last (it vouches for their sha256),
with -R timi-petre/worship-book-catalog from outside that repo:
  gh release upload books <every tool/out/books/*.json but books.json> --clobber
  gh release upload books tool/out/books/books.json --clobber
"""

import gzip
import json
import pathlib
import sys
import unicodedata

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from import_resursecrestine import write_package  # noqa: E402

ROOT = pathlib.Path(__file__).parent.parent
OUT = ROOT / "tool" / "out" / "books"
RELEASE_URL = (
    "https://github.com/timi-petre/worship-book-catalog"
    "/releases/download/books"
)

# Mirrors _priorityBooks in lib/utils/book_order.dart (prefix match).
PRIORITY = ["Laudele Domnului", "Pe Drumul Credinței", "Cântările Evangheliei"]

# Book ids the app must hide and delete from the phone (ADR 0016, decision
# 8): written into books.json as "withdrawn", read by every app that fetches
# the manifest (welcome, manage books, "Actualizează biblioteca"). Ids only,
# never text. HERE and not in a hand-edited books.json, because the weekly
# workflow rebuilds the manifest from this script and would drop the edit.
# To withdraw the 2024 edition: WITHDRAWN = ["laudele-domnului-2024"].
WITHDRAWN: list[str] = []


def book_rank(book: str) -> int:
    for i, p in enumerate(PRIORITY):
        if book.startswith(p):
            return i
    return len(PRIORITY)


def slug(name: str) -> str:
    ascii_name = (
        unicodedata.normalize("NFKD", name)
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    return "-".join("".join(c if c.isalnum() else " " for c in ascii_name).split())


def main() -> None:
    catalog = json.loads((ROOT / "assets/catalog/catalog.json").read_text())
    songs = catalog["songs"]
    date = catalog["generated"]

    by_book: dict[str, list] = {}
    for s in songs:
        by_book.setdefault(s.get("book", ""), []).append(s)
    diverse = by_book.pop("", [])

    # Library order: priority prefixes, rest alphabetical (Dart compareTo ==
    # code-point order here, every char is BMP), Diverse appended last.
    ordered = sorted(by_book, key=lambda b: (book_rank(b), b))

    OUT.mkdir(parents=True, exist_ok=True)
    manifest_file = OUT / "books.json"
    previous = {}
    if manifest_file.exists():
        previous = {
            c.get("id"): c
            for c in json.loads(manifest_file.read_text()).get("collections", [])
        }
    print(f"previous books.json: {len(previous)} books, "
          f"{sum('sha256' in c for c in previous.values())} with sha256")
    entries = []
    total = 0
    for name in ordered + ["Diverse"]:
        book_songs = diverse if name == "Diverse" else by_book[name]
        cid = slug(name)
        payload = {
            "collection": cid,
            "name": name,
            "description": "",
            # `source` and `license`: write_songs_file(), from the songs.
            "generated": date,
            "count": len(book_songs),
            "songs": book_songs,
        }
        f = OUT / f"{cid}.json"
        generated, sha = write_package(f, payload, previous.get(cid))
        size = f.stat().st_size
        total += len(book_songs)
        entries.append(
            {
                "id": cid,
                "name": name,
                "description": "",
                "count": len(book_songs),
                "bytes": size,
                "url": f"{RELEASE_URL}/{cid}.json",
                "generated": generated,
                "sha256": sha,
            }
        )
        gz = len(gzip.compress(f.read_bytes()))
        print(f"{cid}.json: {len(book_songs)} songs, "
              f"{size / 1e6:.2f} MB ({gz / 1e6:.2f} MB gzip), {generated}")

    assert total == len(songs), f"{total} packaged != {len(songs)} in catalog"
    manifest = {"collections": entries, "generated": date, "withdrawn": WITHDRAWN}
    manifest_file.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    dated = sum(e["generated"] == date for e in entries)
    print(f"books.json: {len(entries)} packages ({dated} dated {date}), "
          f"{total} songs total")


if __name__ == "__main__":
    main()
