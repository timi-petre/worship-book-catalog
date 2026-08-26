#!/usr/bin/env python3
"""Fetches the hymn number ("cântarea nr. N") for every songbook song.

The number is printed only on each song's own page, in the info line after
the lyrics ("I: Cântările Evangheliei - 1913, cântarea nr. 280") — the
alphabetical/album listings don't carry it, so this is one request per song.

Writes tool/out/book_numbers.jsonl: one {"id", "url", "number"} per line
(number is null when the page has none), resumable. finalize() in
import_resursecrestine.py attaches the numbers to the catalog.

Run: python3 tool/fetch_book_numbers.py [max_fetches]
"""
import json
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from import_resursecrestine import OUT, fetch  # noqa: E402

BOOK_SONGS = OUT / "cantece_songs.jsonl"
RESULT = OUT / "book_numbers.jsonl"
SLEEP = 1.0

# The info line: "I: <book/album>, cântarea nr. 280". Fall back to any
# "cântarea nr. N" mention if a page words it differently.
INFO_NR = re.compile(r"I:[^<]*c[âa]ntarea\s+nr\.?\s*(\d+)", re.I)
ANY_NR = re.compile(r"c[âa]ntarea\s+nr\.?\s*(\d+)", re.I)


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None

    songs = []
    for line in BOOK_SONGS.read_text().split("\n"):
        if line.strip():
            r = json.loads(line)
            if r.get("ok") and r.get("book"):
                songs.append(r)

    done = set()
    if RESULT.exists():
        for line in RESULT.read_text().split("\n"):
            if line.strip():
                done.add(json.loads(line)["id"])

    todo = [s for s in songs if s["id"] not in done]
    print(f"{len(done)} done; {len(todo)} to fetch", flush=True)

    fetched = numbered = failed = 0
    with RESULT.open("a", encoding="utf-8") as out:
        for song in todo:
            if limit is not None and fetched >= limit:
                break
            try:
                page = fetch(song["url"])
            except Exception as e:  # noqa: BLE001 — log and move on
                print(f"  !! {song['url']}: {e}", flush=True)
                failed += 1
                time.sleep(SLEEP)
                continue
            m = INFO_NR.search(page) or ANY_NR.search(page)
            number = int(m.group(1)) if m else None
            out.write(json.dumps({
                "id": song["id"],
                "url": song["url"],
                "number": number,
            }, ensure_ascii=False) + "\n")
            fetched += 1
            if number is not None:
                numbered += 1
            if fetched % 50 == 0:
                out.flush()
                print(f"fetched {fetched}/{len(todo)} "
                      f"(numbered: {numbered}, failed: {failed})", flush=True)
            time.sleep(SLEEP)

    print(f"BOOK NUMBERS COMPLETE: fetched {fetched}, numbered {numbered}, "
          f"failed {failed}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
