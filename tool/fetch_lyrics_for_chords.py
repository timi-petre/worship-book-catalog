#!/usr/bin/env python3
"""Fetches clean lyrics (the site's "versuri" section) for chord songs with
a same-title entry in the cantece index, so the app's lyrics-only view can
show real stanzas instead of chord-stripped text with alignment gaps.

Writes tool/out/chord_lyrics.jsonl: one {"chord_id", "url", "lyrics"} per
line, resumable. Seeds instantly (no network) from the already-fetched book
songs. Whether a pairing is trusted is decided later, in finalize(), by
text-similarity gating.

Run: python3 tool/fetch_lyrics_for_chords.py
"""
import html
import json
import re
import sys
import time
import unicodedata
import urllib.request
from pathlib import Path

OUT = Path(__file__).parent / "out"
CHORD_SONGS = OUT / "songs.jsonl"
CANTECE_INDEX = OUT / "cantece_index.jsonl"
CANTECE_SONGS = OUT / "cantece_songs.jsonl"
RESULT = OUT / "chord_lyrics.jsonl"

UA = "worship-book-importer/1.0 (+https://github.com/timi-petre/worship-book-catalog)"
SLEEP = 1.0

STROFA = re.compile(
    r'<div class="strofa"><div class="strofa-label">([^<]*)</div>'
    r'<div class="strofa-text">(.*?)</div></div>',
    re.S,
)
BR = re.compile(r"<br\s*/?>")
TAG = re.compile(r"<[^>]+>")


def norm_title(t):
    t = unicodedata.normalize("NFKD", t.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def stanza_body(page_html):
    """Lyrics body from labeled stanza blocks ({soc}/{eoc} for refrains)."""
    stanzas = STROFA.findall(page_html)
    if not stanzas:
        return None
    seen = set()
    body = []
    for label, text_html in stanzas:
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
        if label.strip().lower().startswith("refren"):
            body.append("{soc}")
            body.extend(lines)
            body.append("{eoc}")
        else:
            body.extend(lines)
        body.append("")
    while body and body[-1] == "":
        body.pop()
    return "\n".join(body) if body else None


def body_from_doc(chordpro_doc):
    """Stanza body of an already-built lyrics doc (drops the header lines)."""
    lines = chordpro_doc.split("\n")
    for i, line in enumerate(lines):
        if not line.strip():
            return "\n".join(lines[i + 1 :]).strip() or None
    return None


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status}")
        return resp.read().decode("utf-8", "replace")


def main():
    chord_songs = []
    for line in CHORD_SONGS.read_text().split("\n"):
        if line.strip():
            r = json.loads(line)
            if r.get("ok"):
                chord_songs.append(r)

    index = {}
    for line in CANTECE_INDEX.read_text().split("\n"):
        if line.strip():
            r = json.loads(line)
            index.setdefault(norm_title(r["title"]), []).append(r)

    fetched_books = {}
    for line in CANTECE_SONGS.read_text().split("\n"):
        if line.strip():
            r = json.loads(line)
            if r.get("ok"):
                fetched_books.setdefault(norm_title(r["title"]), r)

    done = set()
    if RESULT.exists():
        for line in RESULT.read_text().split("\n"):
            if line.strip():
                done.add(json.loads(line)["chord_id"])

    seeded = fetched = failed = 0
    with RESULT.open("a", encoding="utf-8") as out:
        todo = []
        for song in chord_songs:
            if song["id"] in done:
                continue
            t = norm_title(song["title"])
            # Seed from book lyrics already on disk — no network needed.
            if t in fetched_books:
                body = body_from_doc(fetched_books[t]["chordpro"])
                if body:
                    out.write(json.dumps({
                        "chord_id": song["id"],
                        "url": fetched_books[t]["url"],
                        "lyrics": body,
                    }, ensure_ascii=False) + "\n")
                    seeded += 1
                    continue
            if t in index:
                todo.append((song, index[t][0]))
        out.flush()
        print(f"seeded {seeded} from books; {len(todo)} to fetch", flush=True)

        for n, (song, entry) in enumerate(todo, 1):
            try:
                page = fetch(entry["url"])
                body = stanza_body(page)
            except Exception as e:  # noqa: BLE001 — log and move on
                print(f"  !! {entry['url']}: {e}", flush=True)
                failed += 1
                time.sleep(SLEEP)
                continue
            if body:
                out.write(json.dumps({
                    "chord_id": song["id"],
                    "url": entry["url"],
                    "lyrics": body,
                }, ensure_ascii=False) + "\n")
                fetched += 1
                if fetched % 50 == 0:
                    out.flush()
                    print(f"fetched {fetched}/{len(todo)} (failed: {failed})",
                          flush=True)
            time.sleep(SLEEP)

    print(f"LYRICS FETCH COMPLETE: seeded {seeded}, fetched {fetched}, "
          f"failed {failed}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
