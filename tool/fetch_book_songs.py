#!/usr/bin/env python3
"""Fetches the songbook (carte) songs from the resursecrestine.ro CANTECE
section — lyrics-only hymnals like Cântările Harului / Evangheliei / Domnului /
Psalmilor / Harfa — and converts them to ChordPro with proper {soc}/{eoc}
chorus markers (the pages carry labeled stanzas).

Reads tool/out/cantece_index.jsonl (from scan_cantece_books.py), fetches every
song (the known book collections keep their "book" grouping; standalone
uploads come in without one), and appends to tool/out/cantece_songs.jsonl
(resumable). The merged catalog is produced by import_resursecrestine.py
finalize, which picks this file up when present.

Usage: python3 tool/fetch_book_songs.py [id ...]
With ids given, only those songs are fetched (targeted refresh).
"""

import html
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from import_resursecrestine import OUT, fetch  # noqa: E402

INDEX = OUT / "cantece_index.jsonl"
SONGS = OUT / "cantece_songs.jsonl"

STROFA = re.compile(
    r'<div class="strofa"><div class="strofa-label">([^<]*)</div>'
    r'<div class="strofa-text">(.*?)</div></div>',
    re.S,
)
BR = re.compile(r"<br\s*/?>")
TAG = re.compile(r"<[^>]+>")


def canonical_book(album: str):
    """Maps an album string to its canonical songbook name, or None."""
    a = (
        album.lower()
        .replace("î", "i").replace("â", "a").replace("ă", "a")
        .replace("ș", "s").replace("ş", "s").replace("ț", "t").replace("ţ", "t")
    )
    if "cantarile harului" in a or "cintarile harului" in a:
        return "Cântările Harului"
    if "cantarile domnului" in a or "cintarile domnului" in a:
        return "Cântările Domnului"
    if "evangheliei - 1913" in a or a in (
        "cintarile evangheliei", "cantarile evangheliei",
        "cantarile evangheliei 1968",
    ):
        return "Cântările Evangheliei"
    if "psalmilor" in a:
        return "Cântările Psalmilor"
    if "harfa" in a:
        return "Harfa Coriștilor"
    if "jubilate" in a:
        return "Jubilate"
    return None


def to_chordpro(page_html: str, meta: dict, book: str):
    """Builds a lyrics-only ChordPro doc from the labeled stanza blocks."""
    stanzas = STROFA.findall(page_html)
    if not stanzas:
        return None
    seen = set()
    body = []
    for label, text_html in stanzas:
        # The page repeats the stanza list (carousel + scroll modes).
        key = (label, text_html)
        if key in seen:
            continue
        seen.add(key)
        lines = []
        for raw_line in BR.split(text_html):
            line = html.unescape(TAG.sub("", raw_line))
            line = re.sub(r"\s+", " ", line).strip()
            if line:
                lines.append(line)
        if not lines:
            continue
        label_l = label.strip().lower()
        if label_l.startswith("refren"):
            body.append("{soc}")
            body.extend(lines)
            body.append("{eoc}")
        else:
            body.extend(lines)
        body.append("")
    while body and body[-1] == "":
        body.pop()
    if not body:
        return None

    doc = [f"{{title: {meta['title']}}}"]
    author = meta.get("author", "").strip()
    if author and author.lower() != "anonim":
        doc.append(f"{{artist: {author}}}")
    if book:
        doc.append(f"# Carte: {meta['album']}")
    doc.append(f"# Sursă: resursecrestine.ro — {meta['url']}")
    doc.append("# Licență conținut: CC BY-NC-SA 3.0 (atribuire, necomercial)")
    doc.append("")
    doc.extend(body)
    return "\n".join(doc)


def main() -> None:
    entries = []
    for line in INDEX.read_text().split("\n"):
        if not line.strip():
            continue
        rec = json.loads(line)
        # Songs outside the known hymnals (worship bands, standalone
        # uploads, ex. „Nobody"/BBSO) se importă și ele, doar fără carte.
        rec["book"] = canonical_book(rec.get("album", "")) or ""
        entries.append(rec)

    done = set()
    if SONGS.exists():
        for line in SONGS.read_text().split("\n"):
            if line.strip():
                # Stored ids carry the "c" prefix, index ids do not, so
                # strip it, otherwise every re-run refetches everything.
                done.add(json.loads(line)["id"].removeprefix("c"))
    todo = [e for e in entries if e["id"] not in done]
    only = set(sys.argv[1:])
    if only:
        todo = [e for e in todo if e["id"] in only]
    print(f"{len(entries)} cantece songs, {len(done)} fetched, {len(todo)} to go",
          flush=True)

    failed = 0
    with SONGS.open("a", encoding="utf-8") as out:
        for n, meta in enumerate(todo, 1):
            try:
                page = fetch(meta["url"])
                chordpro = to_chordpro(page, meta, meta["book"])
            except RuntimeError as e:
                print(f"  !! {meta['url']}: {e}", flush=True)
                failed += 1
                continue
            rec = {
                "id": "c" + meta["id"],  # avoid id collisions with acorduri
                "title": meta["title"],
                "author": meta.get("author", ""),
                "theme": meta.get("theme", ""),
                "url": meta["url"],
                "book": meta["book"],
                "album": meta.get("album", ""),
                "chordpro": chordpro or "",
                "ok": chordpro is not None,
            }
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
            if n % 50 == 0 or n == len(todo):
                print(f"fetched {n}/{len(todo)} (failed: {failed})", flush=True)
    print("BOOKS FETCH COMPLETE", flush=True)


if __name__ == "__main__":
    main()
