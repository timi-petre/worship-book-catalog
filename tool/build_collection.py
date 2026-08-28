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
      [--limit N] [--no-fetch] [--retry-no-stanzas] [song_id ...]

--no-fetch împachetează DOAR ce e deja în cache, fără nicio descărcare. Există
fiindcă descărcarea rulează cu buget de timp în CI: pe 27 aug 2026 bugetul s-a
epuizat înainte de împachetare, deci colecția n-a mai fost publicată deloc, iar
rularea a rămas verde. Cu descărcarea și împachetarea despărțite, colecția
crește în trepte: fiecare rulare publică exact ce e în cache, întreg și coerent.

Pe lângă cache, care ține REUȘITELE, se ține minte și un fel de eșec:
<id>.no-stanzas.txt, paginile care au răspuns dar nu conțin strofe. Pe 27 aug
2026 s-au probat 1.613 pagini în 50 de minute și niciuna n-a reușit, aceleași
în fiecare săptămână, fiindcă în cache intrau doar reușitele. Eșecurile de
TRANSPORT (rețea, timeout, 5xx, 429) NU se țin minte niciodată: sunt temporare,
iar o oră de internet prost ar șterge definitiv sute de cântări bune din
colecție. --retry-no-stanzas ignoră lista pentru rularea aceea, pentru cazul în
care site-ul sau parserul se schimbă; fără expirare, fără reîncercări automate.

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
    ap.add_argument("--no-fetch", action="store_true", dest="no_fetch",
                    help="doar impacheteaza cache-ul, nu descarca nimic")
    ap.add_argument("--retry-no-stanzas", action="store_true",
                    dest="retry_no_stanzas",
                    help="ignora lista de pagini fara strofe si le cere din nou")
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
    if not todo and not args.no_fetch:
        sys.exit("no matching songs (all filtered out or already in catalog)")

    col_dir = OUT / "collections"
    col_dir.mkdir(parents=True, exist_ok=True)
    cache = col_dir / f"{args.cid}.songs.jsonl"

    # Pagini care au raspuns dar n-au strofe. Langa cache, acelasi format: o
    # linie pe id. Se scrie la fiecare esec, nu la final, fiindca rularea din
    # CI e taiata cu SIGTERM la bugetul de timp.
    fail_file = col_dir / f"{args.cid}.no-stanzas.txt"
    memorate = set()
    if fail_file.exists():
        memorate = {
            x.strip() for x in fail_file.read_text().split("\n") if x.strip()
        }
    # --retry-no-stanzas citeste lista (ca sa nu scrie dubluri) dar nu mai sare
    # peste nimic: e reincercarea manuala, pentru cand site-ul s-a schimbat.
    fara_strofe = set() if args.retry_no_stanzas else set(memorate)

    def tine_minte(sid: str) -> None:
        if sid in memorate:
            return
        memorate.add(sid)
        with fail_file.open("a", encoding="utf-8") as f:
            f.write(sid + "\n")

    done = {}
    if cache.exists():
        for line in cache.read_text().split("\n"):
            if line.strip():
                rec = json.loads(line)
                done[rec["id"]] = rec
    # „de adus" e numarul care conteaza, si NU e len(todo) - len(done): cache-ul
    # tine si cantari care intre timp au intrat in catalogul principal, deci nu
    # mai sunt eligibile. Pe 27 aug 2026 linia zicea „17992 songs, 17763 cached"
    # (deci parca 229 ramase) cand de fapt mai erau 1997 de adus, din care 1613
    # pagini fara strofe, cerute degeaba saptamana de saptamana.
    de_adus = [e for e in todo if "c" + e["id"] not in done]
    sarite = sum(1 for e in de_adus if "c" + e["id"] in fara_strofe)
    print(f"{len(todo)} eligibile, {len(done)} in cache, {len(de_adus)} de adus, "
          f"{sarite} fara strofe (sarite), {len(de_adus) - sarite} raman",
          flush=True)

    if args.no_fetch:
        # Garda: fara cache n-avem ce impacheta, iar o colectie goala publicata
        # peste cea buna ar sterge cantarile din aplicatie la toata lumea.
        if not done:
            sys.exit("--no-fetch fara cache: n-am ce impacheta, nu scriu nimic")
        print("--no-fetch: impachetez doar ce e in cache", flush=True)
        todo = []

    crawled = crawled_chordpro() if todo else {}
    failed = 0
    with cache.open("a", encoding="utf-8") as out:
        for n, meta in enumerate(todo, 1):
            sid = "c" + meta["id"]
            if sid in done or sid in fara_strofe:
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
                    # ESEC DE TRANSPORT (sau o crapatura a parserului): n-am
                    # ajuns la pagina. Temporar, deci NU se tine minte, altfel
                    # o ora de internet prost ar sterge definitiv sute de
                    # cantari bune din colectie. `fetch` reincearca de 4 ori si
                    # abia apoi ridica, deci aici ajung doar esecurile reale.
                    #
                    # Orice, nu doar RuntimeError: un `socket.timeout` la
                    # citire a omorat o rulare de 4 ore si jumatate dupa
                    # 12.600 de cantari (26 aug 2026). O pagina pierduta se
                    # reia la urmatoarea rulare; un proces mort pierde tot ce
                    # mai avea de facut.
                    print(f"  !! {meta['url']}: {e!r}", flush=True)
                    failed += 1
                    continue
            if not chordpro:
                # ESEC DE CONTINUT: pagina a raspuns, dar structura ei n-are
                # versuri. Nu se schimba la reincercare, deci se tine minte.
                print(f"  -- no stanzas: {meta['url']}", flush=True)
                tine_minte(sid)
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
