#!/usr/bin/env python3
"""Builds a downloadable song collection + its manifest entry.

A collection is a catalog-format JSON (parsed in the app by
CatalogRepository.fromJsonString) whose songs all carry `book` = the
collection's display name, so once downloaded it shows up in the Library
like any other songbook. Collections are published as assets of the
`collections` pre-release on timi-petre/worship-book-catalog, next to a
collections.json manifest the app lists.

Songs come from the resursecrestine.ro CANTECE index built by
scan_cantece_books.py (tool/out/cantece_index.jsonl). Only songs NOT
already fetched into the main catalog (tool/out/cantece_songs.jsonl) are
eligible. Fetches are polite (same fetch()/delay as the importer) and
cached in tool/out/collections/<id>.songs.jsonl, so re-runs resume.

Usage:
  python3 tool/build_collection.py --id cantarile-bibliei \
      --name "Cântările Bibliei" --description "..." \
      [--author "Nicolae Moldoveanu"] [--album "Cantarile Bibliei"] \
      [--limit N] [song_id ...]

Output: tool/out/collections/<id>.json + tool/out/collections/collections.json
Upload: gh release upload collections <files> -R timi-petre/worship-book-catalog
"""

import argparse
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from import_resursecrestine import CATALOG_FILE, OUT, fetch  # noqa: E402
from fetch_book_songs import canonical_book, to_chordpro  # noqa: E402

RELEASE_URL = (
    "https://github.com/timi-petre/worship-book-catalog"
    "/releases/download/collections"
)


def eligible_entries():
    """Index entries not already in the SHIPPED catalog: standalone songs
    (no canonical hymnal). Songs the books crawler has already fetched into
    cantece_songs.jsonl stay eligible, their ChordPro is reused (see
    crawled_chordpro) instead of refetched."""
    shipped = set()
    if CATALOG_FILE.exists():
        shipped = {
            s["id"] for s in json.loads(CATALOG_FILE.read_text())["songs"]
        }
    entries = []
    for line in (OUT / "cantece_index.jsonl").read_text().split("\n"):
        if not line.strip():
            continue
        rec = json.loads(line)
        if "c" + rec["id"] in shipped:
            continue
        if canonical_book(rec.get("album", "")):
            continue  # belongs to a bundled hymnal, not collection material
        entries.append(rec)
    return entries


def crawled_chordpro():
    """ChordPro already fetched by fetch_book_songs.py, keyed by 'c' id."""
    docs = {}
    songs_file = OUT / "cantece_songs.jsonl"
    if songs_file.exists():
        for line in songs_file.read_text().split("\n"):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # partial last line while the crawler still appends
            if rec.get("ok") and rec.get("chordpro"):
                docs[rec["id"]] = rec["chordpro"]
    return docs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True, dest="cid")
    ap.add_argument("--name", required=True)
    ap.add_argument("--description", default="")
    ap.add_argument("--author")
    ap.add_argument("--album")
    ap.add_argument("--limit", type=int)
    ap.add_argument("ids", nargs="*")
    args = ap.parse_args()

    todo = eligible_entries()
    if args.author:
        todo = [e for e in todo if e.get("author") == args.author]
    if args.album:
        todo = [e for e in todo if e.get("album") == args.album]
    if args.ids:
        only = set(args.ids)
        todo = [e for e in todo if e["id"] in only]
    if args.limit:
        todo = todo[: args.limit]
    if not todo:
        sys.exit("no matching songs (all filtered out or already in catalog)")

    col_dir = OUT / "collections"
    col_dir.mkdir(parents=True, exist_ok=True)
    cache = col_dir / f"{args.cid}.songs.jsonl"

    done = {}
    if cache.exists():
        for line in cache.read_text().split("\n"):
            if line.strip():
                rec = json.loads(line)
                done[rec["id"]] = rec
    print(f"{len(todo)} songs, {len(done)} cached", flush=True)

    crawled = crawled_chordpro()
    failed = 0
    with cache.open("a", encoding="utf-8") as out:
        for n, meta in enumerate(todo, 1):
            sid = "c" + meta["id"]
            if sid in done:
                continue
            if sid in crawled:
                chordpro = crawled[sid]
            else:
                try:
                    page = fetch(meta["url"])
                    # book="" here: no "# Carte:" comment in the ChordPro
                    # (the album is just a site grouping); the JSON `book`
                    # field below is what groups the collection in the app.
                    chordpro = to_chordpro(page, meta, "")
                except Exception as e:  # noqa: BLE001
                    # Orice, nu doar RuntimeError: un `socket.timeout` la
                    # citire a omorat o rulare de 4 ore si jumatate dupa
                    # 12.600 de cantari (26 aug 2026). O pagina pierduta se
                    # reia la urmatoarea rulare, fiindca in cache intra doar
                    # reusitele; un proces mort pierde tot ce mai avea de
                    # facut.
                    print(f"  !! {meta['url']}: {e!r}", flush=True)
                    failed += 1
                    continue
            if not chordpro:
                print(f"  -- no stanzas: {meta['url']}", flush=True)
                failed += 1
                continue
            rec = {
                "id": sid,  # "c" prefix: same id space as cantece imports
                "title": meta["title"],
                "author": meta.get("author", ""),
                "theme": meta.get("theme", ""),
                "url": meta["url"],
                "album": meta.get("album", ""),
                "chordpro": chordpro,
            }
            done[sid] = rec
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
            if n % 25 == 0 or n == len(todo):
                print(f"fetched {n}/{len(todo)} (failed: {failed})", flush=True)

    songs = sorted(done.values(), key=lambda s: s["title"].lower())
    for s in songs:
        s["book"] = args.name
    date = time.strftime("%Y-%m-%d")
    # Header fields first: the app reads collection/name/generated from the
    # file's first bytes, so keep the description short.
    payload = {
        "collection": args.cid,
        "name": args.name,
        "description": args.description,
        "source": "resursecrestine.ro",
        "license": "CC BY-NC-SA 3.0",
        "generated": date,
        "count": len(songs),
        "songs": songs,
    }
    col_file = col_dir / f"{args.cid}.json"
    col_file.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"{col_file.name}: {len(songs)} songs, "
          f"{col_file.stat().st_size / 1e6:.1f} MB")

    # Update (or create) the manifest, replacing this collection's entry.
    manifest_file = col_dir / "collections.json"
    manifest = {"collections": []}
    if manifest_file.exists():
        manifest = json.loads(manifest_file.read_text())
    entry = {
        "id": args.cid,
        "name": args.name,
        "description": args.description,
        "count": len(songs),
        "bytes": col_file.stat().st_size,
        "url": f"{RELEASE_URL}/{args.cid}.json",
        "generated": date,
    }
    manifest["collections"] = [
        c for c in manifest.get("collections", []) if c.get("id") != args.cid
    ] + [entry]
    manifest["generated"] = date
    manifest_file.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"manifest updated: {len(manifest['collections'])} collection(s)")
    print("BUILD COMPLETE", flush=True)


if __name__ == "__main__":
    main()
