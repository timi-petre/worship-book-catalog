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
  python3 tool/import_resursecrestine.py reconvert   # redo HTML->ChordPro
                                                     # from tool/out cache,
                                                     # no network; follow
                                                     # with 'finalize'

NOTE (aug 2026): the chord-row recognition was widened (trailing "."/",",
capital M major, "(F)", loose text chords on rows that also carry nice-acord
anchors). The app still repairs old copies at parse time
(lib/services/text_to_chordpro.dart, inlineLooseChordLines).

finalize() rebuilds every song's ChordPro from the raw HTML stored at fetch
time (oct 2026). Before, it copied the conversion frozen at download, and the
weekly CI never ran 'reconvert', so every song fetched before a converter fix
kept the old output forever (1.632 of 4.753 songs, ex. 318533: the chord row
above "R1:" floated as text). The stored chordpro is only the fallback.

Manual corrections: tool/curated/<id>.cho holds a full ChordPro document that
replaces the song's `chordpro` in EVERY published file. They are applied in
write_songs_file(), the one function catalog.json, the book packages and the
collections are written through.
"""

import hashlib
import html
import http.client
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
        except (urllib.error.URLError, TimeoutError, ConnectionError,
                http.client.IncompleteRead, http.client.HTTPException) as e:
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
# Cloudflare hides e-mail addresses in the page as
# <a ... data-cfemail="HEX">[email&#160;protected]</a>; the browser decodes them
# with JavaScript, we never run it, so "[email protected]" reached the catalog
# (35 songs) and the app showed it as a chord chip.
CF_EMAIL = re.compile(r'<a[^>]*\bdata-cfemail="([0-9a-fA-F]*)"[^>]*>(.*?)</a>', re.S)
# A bracket pair, for telling "[Am]" (a chord a contributor typed inline,
# song 234) from literal brackets in the lyric ("[ E glorios, ... ]", 63699).
BRACKET_PAIR = re.compile(r"\[([^\[\]]*)\]")

# Strict chord token for detecting PLAIN-TEXT chord lines (some contributors
# write chords without the nice-acord markup). Root A-G + optional accidental
# + a restricted quality alphabet + optional slash bass. Deliberately strict:
# quality letters outside (m, maj, min, dim, aug, sus, add) are rejected so
# Romanian words like "Da"/"Ce"/"Fa" don't false-positive; the truly ambiguous
# survivors ("E", "A", "Am") only count on lines where EVERY token is a chord.
# Capital M major ("DM", "GM7", "A#Maj9") and mid-quality accidentals
# ("Am7b5", "Ebadd#11") are accepted, both frequent on contributor rows.
# A dangling slash ("Bb/") is a chord whose bass sits in a nice-acord anchor
# right after it ("Bb/[F]"): accepting it lets the row refold as "Bb/F".
CHORD_TOKEN = re.compile(
    r"^[A-G][#b]?"
    r"(?:m(?!aj)|maj|min|dim|aug|sus|add|M(?!aj)|Maj|[0-9#b+°])*"
    r"(?:/[A-G][#b]?|/)?$"
)

# Romanian solfège notation (Sol, Re/Fa#, mim7, lam...), mapped to letters so
# the songs transpose like everything else. Bare note names double as
# Romanian words ("la", "si", "mi"), so a line only counts as solfège when
# at least one UNAMBIGUOUS token (accidental/minor/quality/slash) anchors it.
SOLFEGE_PART = re.compile(
    r"^(do|re|mi|fa|sol|la|si)([#b]?)(m(?!aj))?"
    r"((?:maj|min|dim|aug|sus|add|[0-9]|\+|°)*)$",
    re.I,
)
NOTE_MAP = {"do": "C", "re": "D", "mi": "E", "fa": "F",
            "sol": "G", "la": "A", "si": "B"}
MARKER = re.compile(r"^(?:/+:?|:/+|x\d+|\||,|-|\.|[0-9])+$")


def _solfege_part_to_letter(part):
    m = SOLFEGE_PART.match(part)
    if not m:
        return None
    return (NOTE_MAP[m.group(1).lower()] + (m.group(2) or "")
            + ("m" if m.group(3) else "") + (m.group(4) or ""))


def _solfege_to_letter(token):
    parts = token.split("/")
    if not parts or len(parts) > 2:
        return None
    root = _solfege_part_to_letter(parts[0])
    if root is None:
        return None
    if len(parts) == 1 or parts[1] == "":
        return root
    bass = _solfege_part_to_letter(parts[1])
    return None if bass is None else root + "/" + bass


def _is_unambiguous_solfege(token):
    if "/" in token:
        return _solfege_to_letter(token) is not None
    m = SOLFEGE_PART.match(token)
    return bool(m and (m.group(2) or m.group(3) or m.group(4)))


def _is_bare_cap_solfege(token):
    m = SOLFEGE_PART.match(token)
    if not m or m.group(2) or m.group(3) or m.group(4):
        return False
    return token[:1].isupper()


def _clean_token(token):
    """Wrapping parens/brackets and riding punctuation off a loose chord
    token: "(F)", "Bbm.", "Eb).", because contributors write chord runs
    as "C. F. G. C"."""
    token = re.sub(r"^[(\[]+", "", token)
    return re.sub(r"[)\],;:.]+$", "", token)


def _is_chordish(token):
    # "Amin" fits the letter grammar (A + min) but is the sung word Amen.
    if token.lower() == "amin":
        return False
    if CHORD_TOKEN.match(token) or _is_unambiguous_solfege(token):
        return True
    if "-" in token:
        parts = [p for p in token.split("-") if p]
        return bool(parts) and all(
            CHORD_TOKEN.match(p) or _is_unambiguous_solfege(p)
            or _is_bare_cap_solfege(p) for p in parts)
    return False


def _is_plain_chord_line(text):
    """True when a no-anchor line consists solely of chord tokens/markers."""
    tokens = text.split()
    if not tokens or len(tokens) > 12:
        return False
    has_chord = has_solfege_anchor = False
    bare_solfege = 0
    for t in tokens:
        if len(t) > 20:
            return False
        t = _clean_token(t)
        if not t:
            continue
        if _is_chordish(t):
            has_chord = True
            if _is_unambiguous_solfege(t) or "-" in t:
                has_solfege_anchor = True
            continue
        if _is_bare_cap_solfege(t):
            bare_solfege += 1
            continue
        if MARKER.match(t):
            continue
        return False
    return has_chord or (bare_solfege > 0 and has_solfege_anchor)


def _to_letter_chord(token):
    """Solfège → letter notation; dash-joined runs convert piecewise."""
    mapped = _solfege_to_letter(token)
    if mapped is not None:
        return mapped
    if "-" in token:
        return "-".join(
            (_solfege_to_letter(p) or p) if p else "" for p in token.split("-"))
    return token


def _plain_chords(text):
    """(column, chord) pairs from a plain-text chord line: standalone digit
    qualities attach to the previous chord ("mim 7" → "mim7"), solfège maps
    to letters, and pure markers are dropped."""
    toks = []
    for m in re.finditer(r"\S+", text):
        t = m.group(0)
        if re.match(r"^[0-9]+$", t) and toks:
            toks[-1] = (toks[-1][0], toks[-1][1] + t)
        else:
            toks.append((m.start(), t))
    out = []
    for col, t in toks:
        t = _clean_token(t)
        if not t:
            continue
        if (_is_chordish(t) or _is_bare_cap_solfege(t)
                or re.match(r"^[0-9]+$", t) is None and not MARKER.match(t)):
            out.append((col, _to_letter_chord(t)))
    return out


def _decode_cf_email(m):
    """data-cfemail is hex: the first byte is the key, every other byte is a
    character XOR-ed with it. Undecodable -> the link text without brackets,
    so it can't turn into a chord chip either."""
    try:
        raw = bytes.fromhex(m.group(1))
        key = raw[0]  # IndexError on an empty attribute
        return html.escape(bytes(b ^ key for b in raw[1:]).decode("utf-8"))
    except (ValueError, IndexError, UnicodeDecodeError):
        return m.group(2).replace("[", "").replace("]", "")


def _neutralize_brackets(text):
    """Literal [ and ] in lyric text become ( and ).

    In ChordPro a bracket IS a chord. Once chords merge into a line that
    starts with "[ E glorios," the app pairs that "[" with the "]" of the
    first chord and swallows the lyric into one chip (63699). A pair whose
    content is a chord ("[Am]", typed inline by the contributor) is kept.
    """
    out, pos = [], 0
    for m in BRACKET_PAIR.finditer(text):
        if _is_chordish(m.group(1).strip()):
            out.append(text[pos:m.start()].replace("[", "(").replace("]", ")"))
            out.append(m.group(0))
            pos = m.end()
    out.append(text[pos:].replace("[", "(").replace("]", ")"))
    return "".join(out)


def _visible(fragment: str) -> str:
    """Strip tags and decode entities; nbsp becomes a regular space."""
    text = TAG.sub("", fragment)
    text = html.unescape(text)
    return text.replace(" ", " ")


def _line_parts(line: str):
    """Split one HTML line into (column, chord) anchors + the plain visible text.

    Returns (chords, text, vis) where chords is a list of (col, chord) with
    col being the visible-column where the chord starts, text is the line's
    visible text with the chord names removed (spacing preserved), and vis is
    the full visible line WITH the (unmapped) chord names in place, so
    columns in vis are the same visible columns the chords report.
    """
    # Mimic browser whitespace handling BEFORE measuring columns: literal
    # newlines/tabs/spaces from HTML source formatting collapse to nothing at
    # the line edges and to a single space inside. Positioning on these pages
    # is done exclusively with &nbsp; entities, which are untouched here
    # because they are still entity-encoded at this point.
    line = re.sub(r"[\r\n\t ]+", " ", line).strip()
    chords = []
    plain = []
    vis = []
    col = 0  # VISIBLE column: includes the width of chord names already seen,
    #          because the lyric line underneath is aligned against what the
    #          browser renders (chords occupy columns there).
    pos = 0
    for m in CHORD_ANCHOR.finditer(line):
        before = _visible(line[pos : m.start()])
        plain.append(before)
        vis.append(before)
        col += len(before)
        chord = _visible(m.group(1)).strip()
        if chord:
            # Map solfège to letters, but advance the visible column by the
            # ORIGINAL width — that's what the browser rendered above lyrics.
            chords.append((col, _to_letter_chord(chord)))
            vis.append(chord)
            col += len(chord)
        pos = m.end()
    rest = _visible(line[pos:])
    plain.append(rest)
    vis.append(rest)
    return chords, "".join(plain), "".join(vis)


def to_chordpro(body_html: str) -> str:
    """Convert a stil-acorduri HTML block to a ChordPro body."""
    # Unicode line/paragraph separators (U+2028/U+2029/NEL) occasionally appear
    # in contributor-pasted content. json.dumps leaves them unescaped, and both
    # Python's splitlines() and some editors treat them as newlines — flatten
    # them to spaces before they can leak into the output.
    for ch in (" ", " ", "\x85"):
        body_html = body_html.replace(ch, " ")
    body_html = CF_EMAIL.sub(_decode_cf_email, body_html)
    lines = BR.split(body_html)
    parsed = []  # (chords, text) per line
    for raw_line in lines:
        chords, text, vis = _line_parts(raw_line)
        text = _neutralize_brackets(text.rstrip())
        # Recognize chord lines written as plain text (no nice-acord markup).
        if not chords and _is_plain_chord_line(text):
            chords = _plain_chords(text)
            text = ""
        elif chords and text.strip() and _is_plain_chord_line(text):
            # Anchor chords AND loose text chords on one row ("[Fm7]  Bbm. Ab"
            # in the old output): refold the whole visible row so every chord
            # merges into the lyric below instead of leaving the loose ones
            # behind as lyric text.
            chords = _plain_chords(vis)
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

def _char_trigrams(text):
    t = re.sub(r"[^a-z0-9]+", "", _fold_search(text))
    return {t[i:i + 3] for i in range(len(t) - 2)} if len(t) > 2 else set()


def _fold_search(text):
    import unicodedata
    t = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def _strip_chordpro(chordpro):
    """Lyric text of a ChordPro doc: no [chords], {directives}, # comments,
    and no chord-noise lines (plain chord runs, Intro:/Capo lines) — those
    would drag down the similarity score of a genuine same-song pairing."""
    out = []
    for line in chordpro.split("\n"):
        s = line.strip()
        if not s or s.startswith("#") or (s.startswith("{") and s.endswith("}")):
            continue
        bare = re.sub(r"\[[^\]]*\]", "", line)
        b = bare.strip()
        if not b or _is_plain_chord_line(b):
            continue
        if re.match(r"^(intro|capo|outro|bridge|interlud)", b, re.I) and len(b) < 60:
            continue
        out.append(bare)
    return "\n".join(out)


def _lyrics_match(lyrics, chordpro):
    """Same-title pairing can hit a DIFFERENT song, so clean lyrics ship only
    past this gate: character-trigram Jaccard between them and the chord
    version's stripped text (trigrams shrug off the alignment gaps that break
    whole words). Threshold chosen loose enough for variant verses, tight
    enough to reject different songs."""
    a = _char_trigrams(lyrics)
    b = _char_trigrams(_strip_chordpro(chordpro))
    union = len(a | b)
    return union > 0 and len(a & b) / union >= 0.45


def _load_clean_lyrics():
    """chord_id -> clean lyrics body, when tool/fetch_lyrics_for_chords.py ran.
    Candidates only: write_songs_file() runs _lyrics_match on them."""
    return {
        rec["chord_id"]: rec["lyrics"]
        for rec in _read_jsonl(OUT / "chord_lyrics.jsonl")
    }


def _load_book_numbers():
    """song id -> hymn number, when tool/fetch_book_numbers.py ran."""
    return {
        rec["id"]: rec["number"]
        for rec in _read_jsonl(OUT / "book_numbers.jsonl")
        if rec.get("number") is not None
    }


def _read_jsonl(path):
    """Records from a .jsonl file; a partial trailing line (a fetcher may
    still be appending) is skipped instead of crashing finalize()."""
    if not path.exists():
        return
    for line in path.read_text().split("\n"):
        if not line.strip():
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


CURATED_DIR = pathlib.Path(__file__).parent / "curated"


def _curated():
    """id -> manual correction, tool/curated/<id>.cho (full ChordPro doc)."""
    docs = {}
    for f in sorted(CURATED_DIR.glob("*.cho")):
        doc = f.read_text(encoding="utf-8").rstrip("\n")
        # The license (CC BY-NC-SA) requires attribution on every song.
        if "# Sursă:" not in doc:
            sys.exit(f"{f}: lipseste randul '# Sursă: ...' (atribuirea ceruta de licenta)")
        docs[f.stem] = doc
    return docs


def write_songs_file(path, payload):
    """The one exit for every published song file: catalog.json (finalize),
    the book packages incl. Diverse (build_book_packages.py) and the
    collections (build_collection.py).

    Manual corrections replace `chordpro` HERE, so no output can skip them,
    and the clean-lyrics gate runs here, after them, so `lyrics` is judged
    against the text that ships. Both are idempotent: the book packages are
    cut from an already corrected catalog.json and come out the same.
    """
    curated = _curated()
    applied = rejected = 0
    for song in payload["songs"]:
        doc = curated.get(str(song["id"]))
        if doc is not None:
            song["chordpro"] = doc
            applied += 1
        if "lyrics" in song and not _lyrics_match(song["lyrics"], song["chordpro"]):
            del song["lyrics"]
            rejected += 1
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    attached = sum("lyrics" in s for s in payload["songs"])
    if applied or attached or rejected:
        print(f"{path.name}: {applied} curated; clean lyrics: {attached} "
              f"attached, {rejected} rejected by similarity gate")


def _content_hash(songs):
    """Fingerprint of everything that decides the published songs: the
    uncorrected songs (clean lyrics candidates included) plus the corrections.
    The weekly workflow publishes when it changes, not only when `count` does,
    so a reconversion or a correction reaches people at the same song count."""
    h = hashlib.sha256(
        json.dumps(songs, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    for f in sorted(CURATED_DIR.glob("*.cho")):
        h.update(f.name.encode("utf-8") + b"\0" + f.read_bytes())
    return h.hexdigest()


def finalize() -> None:
    if not SONGS_FILE.exists():
        sys.exit("run the 'fetch' phase first")
    clean_lyrics = _load_clean_lyrics()
    songs = []
    for line in SONGS_FILE.read_text().split("\n"):
        if not line.strip():
            continue
        rec = json.loads(line)
        if not rec.get("ok"):
            continue
        entry = {
            "id": rec["id"],
            "title": rec["title"],
            "author": rec.get("author", ""),
            "theme": rec.get("theme", ""),
            "url": rec["url"],
            # Today's converter over the stored HTML; the conversion frozen at
            # download is only the fallback (see the module docstring).
            "chordpro": build_doc(rec.get("html") or None,
                                  rec.get("page_title", ""), rec)
            or rec["chordpro"],
        }
        lyrics = clean_lyrics.get(rec["id"])
        if lyrics:
            entry["lyrics"] = lyrics
        songs.append(entry)

    # Songbook (carte) songs from the lyrics section, when fetched
    # (tool/fetch_book_songs.py). They carry a "book" field the app groups by.
    books_file = OUT / "cantece_songs.jsonl"
    if books_file.exists():
        numbers = _load_book_numbers()
        n_books = n_numbered = 0
        for rec in _read_jsonl(books_file):
            if not rec.get("ok"):
                continue
            entry = {
                "id": rec["id"],
                "title": rec["title"],
                "author": rec.get("author", ""),
                "theme": rec.get("theme", ""),
                "url": rec["url"],
                "book": rec.get("book", ""),
                "album": rec.get("album", ""),
                "chordpro": rec["chordpro"],
            }
            # Hymn number within the book ("cântarea nr. N"), when fetched
            # (tool/fetch_book_numbers.py). Shown and searchable in the app.
            number = numbers.get(rec["id"])
            if number is not None:
                entry["number"] = number
                n_numbered += 1
            songs.append(entry)
            n_books += 1
        print(f"merged {n_books} songbook songs ({n_numbered} with numbers)")

    # Songbook texts from the cantaricrestine.ro public API (lyrics for
    # projection; terms permit free copying/distribution — the app is free).
    # Lyrics-only, hymn numbers included (tool/fetch_cantaricrestine.py).
    cc_file = OUT / "cantaricrestine_songs.jsonl"
    if cc_file.exists():
        cc_songs = [
            rec for rec in _read_jsonl(cc_file) if "page_done" not in rec
        ]
        # The site keeps duplicate uploads: most unnumbered entries shadow a
        # numbered one of the same title in the same book — drop those (and
        # repeated unnumbered titles), keep the canonical numbered hymn.
        numbered_titles = set()
        for rec in cc_songs:
            if rec.get("number") is not None:
                numbered_titles.add((rec["book"], _fold_search(rec["title"])))
        seen_unnumbered = set()
        n_cc = n_cc_dropped = 0
        for rec in cc_songs:
            if rec.get("number") is None:
                key = (rec["book"], _fold_search(rec["title"]))
                if key in numbered_titles or key in seen_unnumbered:
                    n_cc_dropped += 1
                    continue
                seen_unnumbered.add(key)
            doc = "\n".join([
                f"{{title: {rec['title']}}}",
                f"# Carte: {rec['book']}",
                f"# Sursă: cantaricrestine.ro — {rec['url']}",
                "",
                rec["text"],
            ])
            entry = {
                "id": rec["id"],
                "title": rec["title"],
                "author": "",
                "theme": "",
                "url": rec["url"],
                "book": rec["book"],
                "album": rec["book"],
                "chordpro": doc,
            }
            if rec.get("number") is not None:
                entry["number"] = rec["number"]
            songs.append(entry)
            n_cc += 1
        print(f"merged {n_cc} cantaricrestine.ro songbook songs "
              f"({n_cc_dropped} duplicate uploads dropped)")
    songs.sort(key=lambda s: s["title"].lower())
    CATALOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        # Two free sources: resursecrestine.ro (CC BY-NC-SA 3.0) and
        # cantaricrestine.ro (free distribution per its terms). Per-song
        # attribution lives in each entry's "# Sursă:" comment.
        "source": "resursecrestine.ro · cantaricrestine.ro",
        "license": "CC BY-NC-SA 3.0",
        "generated": time.strftime("%Y-%m-%d"),
        "count": len(songs),
        "content_hash": _content_hash(songs),
        "songs": songs,
    }
    write_songs_file(CATALOG_FILE, payload)
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
