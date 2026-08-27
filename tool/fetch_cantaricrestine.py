#!/usr/bin/env python3
"""Fetches songbook texts from the cantaricrestine.ro public API.

The site (lyrics for projection, PowerPoint) exposes a documented JSON API
(https://www.cantaricrestine.ro/documentatie-api.php; the `token` parameter
is any random value). Terms of use permit free viewing/copying/distribution
— matching our free app. Hymn numbers come inside `denumire` ("001 Lui
Dumnezeu să-I cânți"), the full text in `descriere`.

Output: tool/out/cantaricrestine_songs.jsonl, one record per song:
{id, book_code, book, number, title, text, url}. Resumable per category
page. finalize() in import_resursecrestine.py merges them into the catalog.

Run: python3 tool/fetch_cantaricrestine.py
"""
import json
import random
import re
import sys
import time
import urllib.request
from pathlib import Path

OUT = Path(__file__).parent / "out"
RESULT = OUT / "cantaricrestine_songs.jsonl"

# The site's WAF rejects non-browser user agents (403), including the
# documented API — a plain browser UA is required to use it at all.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
SLEEP = 1.0
LIMIT = 200  # results per page — few requests per book

# Category code -> canonical book name (site menus skip diacritics).
BOOKS = {
    "cr": "Cântările Evangheliei (Carte Roșie)",
    "cn": "Cântările Evangheliei (Carte Neagră)",
    "ca": "Cântările Evangheliei (Carte Albastră)",
    "ic": "Imnuri Creștine (AZSMR)",
    "ic2": "Imnuri Creștine",
    "pdc": "Pe Drumul Credinței",
    "ld": "Laudele Domnului",
    "ih": "Imnurile Harului",
    "lpd": "Lăudați pe Domnul",
    "lpdag": "Lăudați pe Domnul (Groza)",
    "cb": "Cântecele Bucuriei",
    "cc": "Carte de cântări",
}

# "001 Lui Dumnezeu sa-I canti" -> (1, "Lui Dumnezeu sa-I canti").
NUMBERED = re.compile(r"^\s*(\d{1,4})\s+(.*\S)\s*$")
# Site-side dedup suffixes: "Doamne mare Te slavim_2", "..._lpd", "..._ca".
SUFFIX = re.compile(r"_[a-z0-9]{1,6}$")


def fetch_page(code, page):
    token = random.randint(10**9, 10**10 - 1)
    url = (f"https://www.cantaricrestine.ro/api.php?token={token}"
           f"&categorie={code}&limita={LIMIT}&pagina={page}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    # Dincolo de ultima pagina API-ul raspunde cu un sir ("Nu sunt
    # rezultate"), nu cu un obiect. La reluare, paginile deja facute sunt
    # sarite fara sa se citeasca total_pagini, deci se ajunge acolo.
    return data if isinstance(data, dict) else {}


def parse_song(code, raw):
    denumire = (raw.get("denumire") or "").strip()
    text = (raw.get("descriere") or "").replace("\r\n", "\n").strip()
    if not text:
        return None  # a handful of entries carry only the .pptx, no text
    match = NUMBERED.match(denumire)
    number = int(match.group(1)) if match else None
    title = SUFFIX.sub("", match.group(2) if match else denumire).strip()
    if not title:
        return None
    # The title field lacks diacritics; the text has them — when the first
    # text line is the same phrase, prefer its spelling for display.
    first_line = text.split("\n", 1)[0].strip().rstrip(".,;:!?")
    if first_line and _fold(first_line) == _fold(title):
        title = first_line
    return {
        "id": f"k{raw['id']}",
        "book_code": code,
        "book": BOOKS[code],
        "number": number,
        "title": title,
        "text": text,
        "url": (raw.get("url") or "").strip(),
    }


def _fold(s):
    table = str.maketrans("ăâîșşțţĂÂÎȘŞȚŢ", "aaisstt" "AAISSTT")
    return re.sub(r"[^a-z0-9]+", " ", s.translate(table).lower()).strip()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    done_pages = set()
    seen_ids = set()
    if RESULT.exists():
        for line in RESULT.read_text().split("\n"):
            if line.strip():
                rec = json.loads(line)
                if "page_done" in rec:
                    done_pages.add((rec["book_code"], rec["page_done"]))
                else:
                    seen_ids.add(rec["id"])
        print(f"resuming: {len(seen_ids)} songs, "
              f"{len(done_pages)} pages done", flush=True)

    total_new = skipped = 0
    with RESULT.open("a", encoding="utf-8") as out:
        for code in BOOKS:
            page = 1
            while True:
                if (code, page) in done_pages:
                    page += 1
                    continue
                try:
                    data = fetch_page(code, page)
                except Exception as e:  # noqa: BLE001 — log and move on
                    print(f"  !! {code} p{page}: {e}", flush=True)
                    time.sleep(SLEEP * 5)
                    continue
                results = data.get("rezultate") or {}
                for raw in results.values():
                    song = parse_song(code, raw)
                    if song is None:
                        skipped += 1
                        continue
                    if song["id"] in seen_ids:
                        continue
                    seen_ids.add(song["id"])
                    out.write(json.dumps(song, ensure_ascii=False) + "\n")
                    total_new += 1
                out.write(json.dumps(
                    {"book_code": code, "page_done": page}) + "\n")
                out.flush()
                pages = int(data.get("paginatie", {}).get("total_pagini", 1))
                print(f"[{code}] p{page}/{pages} (+{total_new} total)",
                      flush=True)
                if page >= pages or not results:
                    break
                page += 1
                time.sleep(SLEEP)
            time.sleep(SLEEP)

    print(f"CANTARICRESTINE FETCH COMPLETE: {total_new} new songs "
          f"({skipped} without text skipped)", flush=True)


if __name__ == "__main__":
    sys.exit(main())
