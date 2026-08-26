#!/usr/bin/env python3
"""Scans the resursecrestine.ro CANTECE (lyrics) section and indexes every
song with its album/songbook. Used to locate the classic hymnals (Laudele
Domnului, Pe Drumul Credinței, Cântările Evangheliei, ...) which exist on the
site only as per-song "album" links.

Output: tool/out/cantece_index.jsonl (one JSON per song: id, url, title,
author, album, album_slug, theme) + a per-album summary printed at the end.
Resumable: letters already finished are skipped on re-run.

Politeness: same regime as the chords importer (~1 req/sec, identifying UA).
"""

import html
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from import_resursecrestine import LETTERS, OUT, fetch  # noqa: E402

INDEX = OUT / "cantece_index.jsonl"
DONE = OUT / "cantece_letters_done.txt"
BASE = "https://www.resursecrestine.ro"

ENTRY = re.compile(
    r'<a href="(?:https://www\.resursecrestine\.ro)?(/cantece/(\d+)/([^"]+))"'
    r'\s+class="listingTitleLink">([^<]+)</a>(.*?)(?=<a href="[^"]*/cantece/\d+/|$)',
    re.S,
)
AUTHOR = re.compile(r'index-autori/([^/"]+)"[^>]*>\s*([^<]+?)\s*</a>', re.S)
ALBUM = re.compile(r'album/([^/"]+)"[^>]*>\s*([^<]+?)\s*</a>', re.S)
THEME = re.compile(r'index-tematic/[^"]*"[^>]*>\s*([^<]+?)\s*</a>', re.S)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    seen = set()
    if INDEX.exists():
        for line in INDEX.read_text().split("\n"):
            if line.strip():
                seen.add(json.loads(line)["id"])
        print(f"resuming; {len(seen)} songs already indexed", flush=True)
    done_letters = set(DONE.read_text().split()) if DONE.exists() else set()

    with INDEX.open("a", encoding="utf-8") as out:
        for letter in LETTERS:
            if letter in done_letters:
                continue
            page, prev_ids, letter_new = 1, None, 0
            while True:
                url = f"{BASE}/cantece/index-alfabetic/{letter}"
                if page > 1:
                    url += f"/pagina/{page}"
                body = fetch(url)
                entries = ENTRY.findall(body)
                if not entries:
                    break
                page_ids = {e[1] for e in entries}
                if page_ids == prev_ids:
                    break
                prev_ids = page_ids
                for path, sid, slug, title, tail in entries:
                    if sid in seen:
                        continue
                    seen.add(sid)
                    letter_new += 1
                    author = AUTHOR.search(tail)
                    album = ALBUM.search(tail)
                    theme = THEME.search(tail)
                    out.write(
                        json.dumps(
                            {
                                "id": sid,
                                "url": BASE + path,
                                "title": html.unescape(title).strip(),
                                "author": html.unescape(author.group(2)).strip()
                                if author
                                else "",
                                "album": html.unescape(album.group(2)).strip()
                                if album
                                else "",
                                "album_slug": album.group(1) if album else "",
                                "theme": html.unescape(theme.group(1)).strip()
                                if theme
                                else "",
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                out.flush()
                if page % 10 == 0:
                    print(f"[{letter}] p{page} (+{letter_new})", flush=True)
                page += 1
            print(f"[{letter}] done: +{letter_new}", flush=True)
            with DONE.open("a") as p:
                p.write(letter + "\n")

    # Summary: songs per album (top + the books we care about).
    from collections import Counter

    albums = Counter()
    for line in INDEX.read_text().split("\n"):
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec["album"]:
            albums[rec["album"]] += 1
    print(f"\nTOTAL songs indexed: {len(seen)}; distinct albums: {len(albums)}")
    print("\nTop 25 albums:")
    for name, n in albums.most_common(25):
        print(f"  {n:5}  {name}")
    print("\nBooks of interest (matching name):")
    for key in ("evanghel", "laudele", "drumul credin"):
        for name, n in albums.items():
            if key in name.lower():
                print(f"  {n:5}  {name}")
    print("SCAN COMPLETE", flush=True)


if __name__ == "__main__":
    main()
