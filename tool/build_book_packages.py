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

Output: tool/out/books/*.json
Upload: gh release upload books tool/out/books/*.json -R timi-petre/worship-book-catalog
"""

import gzip
import json
import pathlib
import unicodedata

ROOT = pathlib.Path(__file__).parent.parent
OUT = ROOT / "tool" / "out" / "books"
RELEASE_URL = (
    "https://github.com/timi-petre/worship-book-catalog"
    "/releases/download/books"
)

# Mirrors _priorityBooks in lib/utils/book_order.dart (prefix match).
PRIORITY = ["Laudele Domnului", "Pe Drumul Credinței", "Cântările Evangheliei"]


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
    entries = []
    total = 0
    for name in ordered + ["Diverse"]:
        book_songs = diverse if name == "Diverse" else by_book[name]
        cid = slug(name)
        payload = {
            "collection": cid,
            "name": name,
            "description": "",
            "source": catalog["source"],
            "license": catalog["license"],
            "generated": date,
            "count": len(book_songs),
            "songs": book_songs,
        }
        f = OUT / f"{cid}.json"
        f.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
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
                "generated": date,
            }
        )
        gz = len(gzip.compress(f.read_bytes()))
        print(f"{cid}.json: {len(book_songs)} songs, "
              f"{size / 1e6:.2f} MB ({gz / 1e6:.2f} MB gzip)")

    assert total == len(songs), f"{total} packaged != {len(songs)} in catalog"
    manifest = {"collections": entries, "generated": date}
    (OUT / "books.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"books.json: {len(entries)} packages, {total} songs total")


if __name__ == "__main__":
    main()
