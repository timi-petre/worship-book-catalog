#!/usr/bin/env python3
"""One-time importer: resursecrestine.ro chord sheets -> ChordPro catalog.

Enumerates all songs in the "acorduri" (chords) section via the site's
alphabetical index, fetches each song page, converts the chords-over-lyrics
HTML into ChordPro, and writes assets/catalog/catalog.json for the app.

Content license: the site's terms license user-submitted content under
CC BY-NC-SA 3.0 (attribution + non-commercial + share-alike). Every song
entry records its source URL and author for attribution, and the app that
ships this catalog must remain free.

Politeness: single-threaded, ~1 req/sec with jitter, identifying User-Agent,
retries with backoff. Resumable: progress is stored in tool/out/*.jsonl and
already-fetched songs are skipped on re-run.

Usage:
  python3 tool/import_resursecrestine.py enumerate   # build the song index
  python3 tool/import_resursecrestine.py fetch       # fetch + convert songs
  python3 tool/import_resursecrestine.py finalize    # write catalog.json
  python3 tool/import_resursecrestine.py all         # all three phases
"""

import html
import json
import pathlib
import random
import re
import sys
import time
import urllib.error
import urllib.request

BASE = "https://www.resursecrestine.ro"
# Letters as listed on the site's alphabetical index (no Q, no X).
LETTERS = list("ABCDEFGHIJKLMNOPRSTUVWYZ")
UA = "CantariDeLaudaImport/1.0 (one-time catalog import; contact: ontagonal@gmail.com)"
OUT = pathlib.Path(__file__).parent / "out"
INDEX_FILE = OUT / "index.jsonl"
SONGS_FILE = OUT / "songs.jsonl"
CATALOG_FILE = pathlib.Path(__file__).parent.parent / "assets" / "catalog" / "catalog.json"

DELAY_S = 0.9  # base delay between requests


def fetch(url: str, tries: int = 4) -> str:
    """GET a URL politely, with retries and backoff. Returns decoded body."""
    for attempt in range(tries):
        time.sleep(DELAY_S + random.uniform(0.0, 0.4))
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            wait = 5 * (attempt + 1)
            print(f"  ! {e} -> retry in {wait}s", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"failed after {tries} tries: {url}")


# ---------------------------------------------------------------- enumerate

LISTING_ENTRY = re.compile(
    r'<a href="(?:https://www\.resursecrestine\.ro)?(/acorduri/(\d+)/([^"]+))"'
    r'\s+class="listingTitleLink">([^<]+)</a>(.*?)(?=<a href="[^"]*/acorduri/\d+/|$)',
    re.S,
)
AUTHOR_IN_ENTRY = re.compile(r'index-autori/[^"]*"[^>]*>\s*([^<]+?)\s*</a>', re.S)
THEME_IN_ENTRY = re.compile(r'index-tematic/[^"]*"[^>]*>\s*([^<]+?)\s*</a>', re.S)


def enumerate_songs() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    seen = set()
    if INDEX_FILE.exists():
        for line in INDEX_FILE.read_text().split("\n"):
            if line.strip():
                seen.add(json.loads(line)["id"])
        print(f"resuming enumeration; {len(seen)} songs already indexed")

    done_letters = set()
    progress = OUT / "letters_done.txt"
    if progress.exists():
        done_letters = set(progress.read_text().split())

    with INDEX_FILE.open("a", encoding="utf-8") as out:
        for letter in LETTERS:
            if letter in done_letters:
                continue
            page = 1
            found_letter = 0
            prev_page_ids = None
            while True:
                url = f"{BASE}/acorduri/index-alfabetic/{letter}"
                if page > 1:
                    url += f"/pagina/{page}"
                body = fetch(url)
                entries = LISTING_ENTRY.findall(body)
                if not entries:
                    break
                # Out-of-range page numbers return the last page again: stop
                # when a page repeats. Pages whose songs are all already seen
                # (from an interrupted earlier run) must still advance.
                page_ids = {e[1] for e in entries}
                if page_ids == prev_page_ids:
                    break
                prev_page_ids = page_ids
                new_here = 0
                for path, sid, slug, title, tail in entries:
                    if sid in seen:
                        continue
                    seen.add(sid)
                    new_here += 1
                    author_m = AUTHOR_IN_ENTRY.search(tail)
                    theme_m = THEME_IN_ENTRY.search(tail)
                    out.write(
                        json.dumps(
                            {
                                "id": sid,
                                "url": BASE + path,
                                "title": html.unescape(title).strip(),
                                "author": html.unescape(author_m.group(1)).strip()
                                if author_m
                                else "",
                                "theme": html.unescape(theme_m.group(1)).strip()
                                if theme_m
                                else "",
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                out.flush()
                found_letter += new_here
                print(f"[{letter}] page {page}: +{new_here} (letter total {found_letter})", flush=True)
                page += 1
            with progress.open("a") as p:
                p.write(letter + "\n")
    print(f"enumeration done: {len(seen)} songs indexed")


# ---------------------------------------------------------------- conversion

BR = re.compile(r"<br\s*\\?/?\s*>")
CHORD_ANCHOR = re.compile(
    r'<a[^>]*class="nice-acord"[^>]*>(.*?)</a>', re.S
)
TAG = re.compile(r"<[^>]+>")
WRAPPER = re.compile(
    r'class="stil-acorduri"+[^>]*>(.*?)</span>', re.S
)
TITLE_TAG = re.compile(r"<title>\s*(.*?)\s*</title>", re.S)

# Strict chord token for detecting PLAIN-TEXT chord lines (some contributors
# write chords without the nice-acord markup). Root A-G + optional accidental
# + a restricted quality alphabet + optional slash bass. Deliberately strict:
# quality letters outside (m, maj, min, dim, aug, sus, add) are rejected so
# Romanian words like "Da"/"Ce"/"Fa" don't false-positive; the truly ambiguous
# survivors ("E", "A", "Am") only count on lines where EVERY token is a chord.
CHORD_TOKEN = re.compile(
    r"^[A-G][#b]?"
    r"(?:m(?!aj)|maj|min|dim|aug|sus|add|[0-9]|\+|°)*"
    r"(?:/[A-G][#b]?)?$"
)


def _is_plain_chord_line(text):
    """True when a no-anchor line consists solely of chord tokens."""
    tokens = text.split()
    if not tokens or len(tokens) > 12:
        return False
    return all(len(t) <= 10 and CHORD_TOKEN.match(t) for t in tokens)


def _plain_chords(text):
    """Extract (column, chord) pairs from a plain-text chord line."""
    return [(m.start(), m.group(0)) for m in re.finditer(r"\S+", text)]


def _visible(fragment: str) -> str:
    """Strip tags and decode entities; nbsp becomes a regular space."""
    text = TAG.sub("", fragment)
    text = html.unescape(text)
    return text.replace(" ", " ")


def _line_parts(line: str):
    """Split one HTML line into (column, chord) anchors + the plain visible text.

    Returns (chords, text) where chords is a list of (col, chord) with col being
    the visible-column where the chord starts, and text is the line's visible
    text with the chord names removed (spacing preserved).
    """
    # Mimic browser whitespace handling BEFORE measuring columns: literal
    # newlines/tabs/spaces from HTML source formatting collapse to nothing at
    # the line edges and to a single space inside. Positioning on these pages
    # is done exclusively with &nbsp; entities, which are untouched here
    # because they are still entity-encoded at this point.
    line = re.sub(r"[\r\n\t ]+", " ", line).strip()
    chords = []
    plain = []
    col = 0  # VISIBLE column: includes the width of chord names already seen,
    #          because the lyric line underneath is aligned against what the
    #          browser renders (chords occupy columns there).
    pos = 0
    for m in CHORD_ANCHOR.finditer(line):
        before = _visible(line[pos : m.start()])
        plain.append(before)
        col += len(before)
        chord = _visible(m.group(1)).strip()
        if chord:
            chords.append((col, chord))
            col += len(chord)
        pos = m.end()
    rest = _visible(line[pos:])
    plain.append(rest)
    return chords, "".join(plain)


def to_chordpro(body_html: str) -> str:
    """Convert a stil-acorduri HTML block to a ChordPro body."""
    # Unicode line/paragraph separators (U+2028/U+2029/NEL) occasionally appear
    # in contributor-pasted content. json.dumps leaves them unescaped, and both
    # Python's splitlines() and some editors treat them as newlines — flatten
    # them to spaces before they can leak into the output.
    for ch in (" ", " ", "\x85"):
        body_html = body_html.replace(ch, " ")
    lines = BR.split(body_html)
    parsed = []  # (chords, text) per line
    for raw_line in lines:
        chords, text = _line_parts(raw_line)
        text = text.rstrip()
        # Recognize chord lines written as plain text (no nice-acord markup).
        if not chords and _is_plain_chord_line(text):
            chords = _plain_chords(text)
            text = ""
        parsed.append((chords, text))

    out = []
    i = 0
    while i < len(parsed):
        chords, text = parsed[i]
        if not chords:
            out.append(text)
            i += 1
            continue

        # Chord line. Pair it with the next line when that one is lyrics.
        next_is_lyric = (
            i + 1 < len(parsed)
            and not parsed[i + 1][0]
            and parsed[i + 1][1].strip() != ""
        )
        annotation = text.strip()
        if next_is_lyric and not annotation:
            lyric = parsed[i + 1][1]
            merged = []
            last = 0
            for col, chord in chords:
                col = min(col, max(len(lyric), col))
                if col > len(lyric):
                    lyric = lyric.ljust(col)
                merged.append(lyric[last:col])
                merged.append(f"[{chord}]")
                last = col
            merged.append(lyric[last:])
            out.append("".join(merged))
            i += 2
        else:
            # Chord-only line (intros, turnarounds) or chord line carrying
            # annotation text: emit it standalone, chords inline in place.
            # `text` holds the annotation with chord names removed, while the
            # chord columns are visible columns — track both cursors.
            merged = []
            cursor = 0  # visible column emitted so far
            consumed = 0  # prefix of `text` already emitted
            for col, chord in chords:
                gap = col - cursor
                if gap > 0:
                    piece = text[consumed : consumed + gap]
                    merged.append(piece.ljust(gap))
                    consumed += len(piece)
                merged.append(f"[{chord}]")
                cursor = col + len(chord)
            merged.append(text[consumed:])
            out.append("".join(merged).rstrip())
            i += 1

    # Collapse >2 consecutive blank lines and trim edges.
    result = []
    blanks = 0
    for line in out:
        if line.strip() == "":
            blanks += 1
            if blanks > 1:
                continue
            result.append("")
        else:
            blanks = 0
            result.append(line)
    while result and result[0] == "":
        result.pop(0)
    while result and result[-1] == "":
        result.pop()
    return "\n".join(result)


def extract_parts(page_html):
    """Pull the chords block + page title out of a full song page."""
    m = WRAPPER.search(page_html)
    wrapper = m.group(1) if m else None
    page_title = ""
    t = TITLE_TAG.search(page_html)
    if t:
        page_title = html.unescape(TAG.sub("", t.group(1))).strip()
        page_title = re.sub(
            r"\s*-\s*Resurse Cre[șs]tine\s*$", "", page_title
        ).strip()
    return wrapper, page_title


def build_doc(wrapper_html, page_title, meta):
    """Chords-block HTML -> ChordPro document (metadata + attribution)."""
    if wrapper_html is None:
        return None
    body = to_chordpro(wrapper_html)
    if not body.strip():
        return None

    title = page_title or meta.get("title", "")

    doc = [f"{{title: {title}}}"]
    author = meta.get("author", "").strip()
    if author and author.lower() != "anonim":
        doc.append(f"{{artist: {author}}}")
    doc.append(f"# Sursă: resursecrestine.ro — {meta['url']}")
    doc.append("# Licență conținut: CC BY-NC-SA 3.0 (atribuire, necomercial)")
    doc.append("")
    doc.append(body)
    return "\n".join(doc)


# ---------------------------------------------------------------- fetch

def fetch_songs() -> None:
    if not INDEX_FILE.exists():
        sys.exit("run the 'enumerate' phase first")
    index = [json.loads(l) for l in INDEX_FILE.read_text().split("\n") if l.strip()]
    done = set()
    if SONGS_FILE.exists():
        for line in SONGS_FILE.read_text().split("\n"):
            if line.strip():
                done.add(json.loads(line)["id"])
    todo = [e for e in index if e["id"] not in done]
    print(f"{len(index)} indexed, {len(done)} fetched, {len(todo)} to go")

    failed = 0
    with SONGS_FILE.open("a", encoding="utf-8") as out:
        for n, meta in enumerate(todo, 1):
            try:
                page = fetch(meta["url"])
                wrapper, page_title = extract_parts(page)
                chordpro = build_doc(wrapper, page_title, meta)
            except RuntimeError as e:
                print(f"  !! giving up on {meta['url']}: {e}", flush=True)
                failed += 1
                continue
            record = dict(meta)
            record["chordpro"] = chordpro or ""
            record["ok"] = chordpro is not None
            # Keep the raw HTML so the converter can be improved and re-run
            # later (phase 'reconvert') without hitting the site again.
            record["html"] = wrapper or ""
            record["page_title"] = page_title
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            if n % 25 == 0 or n == len(todo):
                print(f"fetched {n}/{len(todo)} (failed: {failed})", flush=True)
    print("fetch phase done")


def reconvert() -> None:
    """Re-run HTML->ChordPro conversion over stored raw HTML (no network)."""
    if not SONGS_FILE.exists():
        sys.exit("nothing to reconvert")
    records = [json.loads(l) for l in SONGS_FILE.read_text().split("\n") if l.strip()]
    changed = 0
    for rec in records:
        wrapper = rec.get("html") or None
        chordpro = build_doc(wrapper, rec.get("page_title", ""), rec)
        new_ok = chordpro is not None
        if rec.get("chordpro") != (chordpro or "") or rec.get("ok") != new_ok:
            changed += 1
        rec["chordpro"] = chordpro or ""
        rec["ok"] = new_ok
    with SONGS_FILE.open("w", encoding="utf-8") as out:
        for rec in records:
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"reconverted {len(records)} songs ({changed} changed)")


# ---------------------------------------------------------------- finalize

def finalize() -> None:
    if not SONGS_FILE.exists():
        sys.exit("run the 'fetch' phase first")
    songs = []
    for line in SONGS_FILE.read_text().split("\n"):
        if not line.strip():
            continue
        rec = json.loads(line)
        if not rec.get("ok"):
            continue
        songs.append(
            {
                "id": rec["id"],
                "title": rec["title"],
                "author": rec.get("author", ""),
                "theme": rec.get("theme", ""),
                "url": rec["url"],
                "chordpro": rec["chordpro"],
            }
        )

    # Songbook (carte) songs from the lyrics section, when fetched
    # (tool/fetch_book_songs.py). They carry a "book" field the app groups by.
    books_file = OUT / "cantece_songs.jsonl"
    if books_file.exists():
        n_books = 0
        for line in books_file.read_text().split("\n"):
            if not line.strip():
                continue
            rec = json.loads(line)
            if not rec.get("ok"):
                continue
            songs.append(
                {
                    "id": rec["id"],
                    "title": rec["title"],
                    "author": rec.get("author", ""),
                    "theme": rec.get("theme", ""),
                    "url": rec["url"],
                    "book": rec.get("book", ""),
                    "album": rec.get("album", ""),
                    "chordpro": rec["chordpro"],
                }
            )
            n_books += 1
        print(f"merged {n_books} songbook songs")
    songs.sort(key=lambda s: s["title"].lower())
    CATALOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": "resursecrestine.ro",
        "license": "CC BY-NC-SA 3.0",
        "generated": time.strftime("%Y-%m-%d"),
        "count": len(songs),
        "songs": songs,
    }
    CATALOG_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    size_mb = CATALOG_FILE.stat().st_size / 1e6
    print(f"catalog.json written: {len(songs)} songs, {size_mb:.1f} MB")


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "all"
    if phase in ("enumerate", "all"):
        enumerate_songs()
    if phase in ("fetch", "all"):
        fetch_songs()
    if phase == "reconvert":
        reconvert()
    if phase in ("finalize", "all", "reconvert"):
        finalize()
