#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from book_utils import dump_markdown, parse_markdown

DEFAULT_INPUT = Path("data/goodreads_library_export.csv")
DEFAULT_SANITIZED_INPUT = Path("data/goodreads_sanitized.csv")
ALLOWED_SHELVES = {"read", "currently-reading", "to-read"}

VERBOSE = False


def vprint(message: str) -> None:
    if VERBOSE:
        print(message, flush=True)


@dataclass
class BookRow:
    title: str
    author: str
    isbn10: str
    isbn13: str
    my_rating: int
    publisher: str
    binding: str
    pages: int
    year_published: Optional[int]
    date_read: Optional[dt.date]
    date_added: Optional[dt.date]
    shelf: str


@dataclass
class ResolvedBook:
    row: BookRow
    slug: str
    isbn: str
    blurb: str
    subjects: List[str]


def clean_value(value: Any) -> str:
    if value is None:
        return ""
    cleaned = str(value).strip()
    while cleaned.startswith("="):
        cleaned = cleaned[1:].strip()
    if cleaned.startswith('"') and cleaned.endswith('"') and len(cleaned) >= 2:
        cleaned = cleaned[1:-1]
    cleaned = cleaned.replace('""', '"').strip()
    return "" if cleaned in {"", '"'} else cleaned


def clean_isbn(value: str) -> str:
    return re.sub(r"[^0-9Xx]", "", clean_value(value)).upper()


def parse_int(value: Any) -> Optional[int]:
    cleaned = clean_value(value)
    if not cleaned:
        return None
    try:
        return int(float(cleaned))
    except ValueError:
        return None


def parse_date(value: Any) -> Optional[dt.date]:
    cleaned = clean_value(value)
    if not cleaned:
        return None
    for fmt in ("%Y/%m/%d", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def iso_date(value: Optional[dt.date]) -> str:
    return value.isoformat() if value else ""


_TRAILING_SERIES_RE = re.compile(r"\s*\([^)]*#\d+[^)]*\)\s*$")


def strip_series_suffix(title: str) -> str:
    stripped = _TRAILING_SERIES_RE.sub("", title).strip()
    return stripped or title


def slugify_title(title: str) -> str:
    stripped = strip_series_suffix(title)
    norm = unicodedata.normalize("NFKD", stripped).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", norm.lower()).strip("-")
    return slug or "book"


def parse_series_info(title: str) -> Tuple[str, Optional[float]]:
    paren_matches = re.findall(r"\(([^)]*)\)", title)
    for segment in reversed(paren_matches):
        segment = segment.strip()
        if not segment:
            continue

        hash_match = re.search(r"#\s*([0-9]+(?:\.[0-9]+)?)", segment)
        if hash_match:
            number = float(hash_match.group(1))
            series_name = segment[: hash_match.start()].rstrip(" ,;:-")
            if series_name:
                return series_name, number

        comma_num_match = re.search(r",\s*([0-9]+(?:\.[0-9]+)?)\s*$", segment)
        if comma_num_match:
            number = float(comma_num_match.group(1))
            series_name = segment[: comma_num_match.start()].rstrip(" ,;:-")
            if series_name:
                return series_name, number

    return "", None


def load_dotenv(path: Path = Path(".env")) -> None:
    """Populate os.environ from a KEY=VALUE file. Existing env vars win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


_REDACT_QUERY_KEYS_RE = re.compile(r"([?&])(key|api_key|apikey)=[^&]*", re.IGNORECASE)


def _redact_url(url: str) -> str:
    return _REDACT_QUERY_KEYS_RE.sub(r"\1\2=REDACTED", url)


def fetch_json(url: str, cache_path: Path, timeout: int = 20) -> Dict[str, Any]:
    if cache_path.exists():
        vprint(f"    [cache] {_redact_url(url)}")
        return json.loads(cache_path.read_text(encoding="utf-8"))
    vprint(f"    [net]   {_redact_url(url)}")
    t0 = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": "books-site-generator/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = response.read().decode("utf-8")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(payload, encoding="utf-8")
    vprint(f"    [net]   -> {len(payload)} bytes in {time.monotonic() - t0:.2f}s")
    return json.loads(payload)


_TRAILING_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")
_NAME_SUFFIX_RE = re.compile(r"^(?:jr|sr|i{1,3}|iv|v)\.?$", re.IGNORECASE)


def _last_name(author: str) -> str:
    tokens = [t for t in author.split() if not _NAME_SUFFIX_RE.match(t)]
    return tokens[-1] if tokens else ""


def _search_attempts(title: str, author: str) -> List[Tuple[str, str]]:
    """Produce (title, author) pairs in order of specificity for OpenLibrary search."""
    attempts: List[Tuple[str, str]] = []

    def add(t: str, a: str) -> None:
        pair = (t.strip(), a.strip())
        if pair[0] and pair[1] and pair not in attempts:
            attempts.append(pair)

    base_title = strip_series_suffix(title)
    add(base_title, author)

    loose_title = _TRAILING_PAREN_RE.sub("", base_title).strip() or base_title
    add(loose_title, author)

    before_colon = loose_title.split(":", 1)[0].strip()
    add(before_colon, author)

    before_slash = (before_colon or loose_title).split("/", 1)[0].strip()
    add(before_slash, author)

    last_name = _last_name(author)
    if last_name:
        add(before_slash or before_colon or loose_title, last_name)

    return attempts


def search_openlibrary_isbn(title: str, author: str, cache_dir: Path, slug: str) -> str:
    for search_title, search_author in _search_attempts(title, author):
        params = urllib.parse.urlencode(
            {
                "title": search_title,
                "author": search_author,
                "limit": 5,
                "fields": "isbn,key,cover_i,cover_edition_key",
            }
        )
        url = f"https://openlibrary.org/search.json?{params}"
        url_hash = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
        cache_path = cache_dir / f"search-{slug}-{url_hash}.json"
        try:
            data = fetch_json(url, cache_path)
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError):
            continue
        for doc in data.get("docs", []):
            for candidate in doc.get("isbn", []):
                isbn = clean_isbn(candidate)
                if isbn:
                    vprint(f"    [srch]  matched {search_title!r} + {search_author!r} -> {isbn}")
                    return isbn
    return ""


_ENGLISH_STOPWORDS = {"the", "and", "of", "was", "were", "with", "that", "which", "from", "they"}


def looks_english(text: str) -> bool:
    """Heuristic: English prose typically contains multiple of these stopwords;
    Spanish/French/German/Italian translations almost never do."""
    if not text:
        return False
    words = re.findall(r"[A-Za-z]+", text.lower())
    if len(words) < 20:
        return True  # too short to judge reliably — accept
    hits = sum(1 for w in words if w in _ENGLISH_STOPWORDS)
    return hits >= 3


def extract_description(work_data: Dict[str, Any]) -> str:
    description = work_data.get("description")
    if isinstance(description, str):
        text = description.strip()
    elif isinstance(description, dict):
        text = clean_value(description.get("value"))
    else:
        return ""
    if not looks_english(text):
        vprint(f"    [lang]  dropping non-English description ({len(text)} chars)")
        return ""
    return text


def normalize_subjects(values: Any) -> List[str]:
    if not values:
        return []
    if isinstance(values, str):
        values = [values]
    seen = set()
    subjects = []
    for value in values:
        subject = clean_value(value)
        if not subject:
            continue
        key = subject.lower()
        if key in seen:
            continue
        seen.add(key)
        subjects.append(subject)
    return subjects[:30]


def resize_and_save_cover(source_bytes: bytes, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(io_bytes := __import__("io").BytesIO(source_bytes)) as image:
        image = image.convert("RGB")
        image.thumbnail((600, 900), Image.Resampling.LANCZOS)
        image.save(destination, format="JPEG", quality=85, optimize=True)


def write_placeholder_cover(destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (600, 900), color=(226, 232, 240))
    image.save(destination, format="JPEG", quality=80, optimize=True)


def _download_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "books-site-generator/1.0"})
    with urllib.request.urlopen(req, timeout=20) as response:
        return response.read()


# MD5 of the generic "No image available" JPEG that Google Books serves when
# a volume has no cover; rejected so the OpenLibrary fallback can run.
_GOOGLE_BOOKS_PLACEHOLDER_MD5 = "a64fa89d7ebc97075c1d363fc5fea71f"


def _fetch_json_with_429_retry(url: str, cache_path: Path, max_attempts: int = 4) -> Dict[str, Any]:
    """Like fetch_json, but retries with exponential backoff on HTTP 429."""
    for attempt in range(max_attempts):
        try:
            return fetch_json(url, cache_path)
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == max_attempts - 1:
                raise
            backoff = 2 ** (attempt + 1)
            vprint(f"    [wait]  HTTP 429, backing off {backoff}s (attempt {attempt + 1}/{max_attempts})")
            time.sleep(backoff)
    raise RuntimeError("unreachable")


def fetch_cover_from_google_books(isbn: str, cache_dir: Path) -> Optional[bytes]:
    """Return cover image bytes from Google Books, or None if unavailable."""
    params = {"q": f"isbn:{isbn}"}
    api_key = os.environ.get("GOOGLE_BOOKS_API_KEY", "")
    if api_key:
        params["key"] = api_key
    url = f"https://www.googleapis.com/books/v1/volumes?{urllib.parse.urlencode(params)}"
    cache_path = cache_dir / f"gbooks-{isbn}.json"
    try:
        data = _fetch_json_with_429_retry(url, cache_path)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError) as exc:
        vprint(f"    [warn]  Google Books lookup failed for {isbn}: {exc}")
        return None

    for item in data.get("items") or []:
        image_links = (item.get("volumeInfo") or {}).get("imageLinks") or {}
        thumbnail = image_links.get("thumbnail") or image_links.get("smallThumbnail")
        if not thumbnail:
            continue
        # zoom=0 returns the largest reliable size (~575px wide); strip the curl effect.
        thumbnail = thumbnail.replace("http://", "https://", 1)
        thumbnail = re.sub(r"&zoom=\d+", "&zoom=0", thumbnail)
        thumbnail = thumbnail.replace("&edge=curl", "")
        try:
            image_data = _download_bytes(thumbnail)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            vprint(f"    [warn]  Google Books image fetch failed: {exc}")
            continue
        if not image_data:
            continue
        if hashlib.md5(image_data).hexdigest() == _GOOGLE_BOOKS_PLACEHOLDER_MD5:
            vprint("    [none]  Google Books returned 'no image available' placeholder")
            continue
        return image_data
    return None


def fetch_cover_from_openlibrary(isbn: str) -> Optional[bytes]:
    """Return cover image bytes from OpenLibrary, or None if unavailable."""
    url = f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false"
    try:
        data = _download_bytes(url)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            vprint(f"    [warn]  OpenLibrary cover HTTP {exc.code}: {exc.reason}")
        return None
    except (urllib.error.URLError, TimeoutError) as exc:
        vprint(f"    [warn]  OpenLibrary cover fetch failed: {exc}")
        return None
    return data or None


def _cover_already_recorded(source: str) -> bool:
    if not source:
        return False
    # "covers.openlibrary.org" substring preserves pre-migration entries in cover_sources.json.
    return (
        source.startswith("google:")
        or source.startswith("openlibrary:")
        or "covers.openlibrary.org" in source
    )


def _save_cover_source(
    cover_sources: Dict[str, str], cover_meta_path: Path, slug: str, marker: str
) -> None:
    cover_sources[slug] = marker
    cover_meta_path.parent.mkdir(parents=True, exist_ok=True)
    cover_meta_path.write_text(
        json.dumps(cover_sources, indent=2, sort_keys=True), encoding="utf-8"
    )


def ensure_cover(slug: str, isbn: str, covers_dir: Path, cache_dir: Path) -> None:
    cover_path = covers_dir / f"{slug}.jpg"
    cover_meta_path = cache_dir / "cover_sources.json"
    cover_sources = load_json(cover_meta_path, {})

    existing_source = cover_sources.get(slug, "")
    if cover_path.exists() and _cover_already_recorded(existing_source):
        vprint(f"    [cache] cover {cover_path.name}")
        return

    vprint(f"    [net]   google books cover for ISBN {isbn}")
    t0 = time.monotonic()
    data = fetch_cover_from_google_books(isbn, cache_dir)
    if data:
        try:
            resize_and_save_cover(data, cover_path)
            _save_cover_source(cover_sources, cover_meta_path, slug, f"google:isbn:{isbn}")
            vprint(f"    [net]   -> google cover {len(data)} bytes in {time.monotonic() - t0:.2f}s")
            return
        except Exception as exc:
            vprint(f"    [warn]  google cover save failed: {exc}")
    else:
        vprint(f"    [none]  no Google Books cover for ISBN {isbn}")

    vprint(f"    [net]   openlibrary cover for ISBN {isbn}")
    t0 = time.monotonic()
    data = fetch_cover_from_openlibrary(isbn)
    if data:
        try:
            resize_and_save_cover(data, cover_path)
            _save_cover_source(cover_sources, cover_meta_path, slug, f"openlibrary:isbn:{isbn}")
            vprint(f"    [net]   -> openlibrary cover {len(data)} bytes in {time.monotonic() - t0:.2f}s")
            return
        except Exception as exc:
            vprint(f"    [warn]  openlibrary cover save failed: {exc}")
    else:
        vprint(f"    [none]  no OpenLibrary cover for ISBN {isbn}")

    if not cover_path.exists():
        write_placeholder_cover(cover_path)


def openlibrary_book_data(isbn: str, cache_dir: Path) -> Optional[Tuple[str, List[str]]]:
    """Fetch blurb + subjects for an ISBN. Returns None if OpenLibrary has no record."""
    isbn_cache = cache_dir / f"{isbn}.json"
    try:
        isbn_data = fetch_json(f"https://openlibrary.org/isbn/{isbn}.json", isbn_cache)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise

    work_key = ""
    works = isbn_data.get("works") or []
    if works and isinstance(works[0], dict):
        work_key = works[0].get("key", "")

    work_data: Dict[str, Any] = {}
    if work_key:
        work_id = work_key.strip("/").replace("/", "-")
        work_cache = cache_dir / f"{work_id}.json"
        try:
            work_data = fetch_json(f"https://openlibrary.org{work_key}.json", work_cache)
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise

    subjects = normalize_subjects(work_data.get("subjects") or isbn_data.get("subjects"))
    blurb = extract_description(work_data)
    if not blurb and subjects:
        blurb = ", ".join(subjects[:8])

    return blurb, subjects


def read_rows(csv_path: Path) -> List[BookRow]:
    rows: List[BookRow] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            shelf = clean_value(row.get("Exclusive Shelf", "")).lower()
            if shelf not in ALLOWED_SHELVES:
                continue
            title = clean_value(row.get("Title", ""))
            author = clean_value(row.get("Author", ""))
            if not title or not author:
                continue
            rows.append(
                BookRow(
                    title=title,
                    author=author,
                    isbn10=clean_isbn(row.get("ISBN", "")),
                    isbn13=clean_isbn(row.get("ISBN13", "")),
                    my_rating=max(0, min(5, parse_int(row.get("My Rating", 0)) or 0)),
                    publisher=clean_value(row.get("Publisher", "")),
                    binding=clean_value(row.get("Binding", "")),
                    pages=parse_int(row.get("Number of Pages", "")) or 0,
                    year_published=parse_int(row.get("Year Published", "")),
                    date_read=parse_date(row.get("Date Read", "")),
                    date_added=parse_date(row.get("Date Added", "")),
                    shelf=shelf,
                )
            )
    return rows


def dedupe_rows(rows: List[BookRow]) -> List[BookRow]:
    deduped: Dict[str, BookRow] = {}
    passthrough: List[BookRow] = []

    for row in rows:
        if not row.isbn13:
            passthrough.append(row)
            continue
        existing = deduped.get(row.isbn13)
        if existing is None:
            deduped[row.isbn13] = row
            continue
        existing_date = existing.date_read or dt.date.min
        row_date = row.date_read or dt.date.min
        if (row.my_rating, row_date) > (existing.my_rating, existing_date):
            deduped[row.isbn13] = row

    return list(deduped.values()) + passthrough


def resolve_book(row: BookRow, cache_dir: Path) -> Tuple[Optional[ResolvedBook], Optional[str]]:
    slug = slugify_title(row.title)
    csv_isbn = row.isbn13 or row.isbn10

    isbn = ""
    blurb = ""
    subjects: List[str] = []

    if csv_isbn:
        try:
            result = openlibrary_book_data(csv_isbn, cache_dir)
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
            vprint(f"    [warn]  ISBN lookup failed for {csv_isbn}: {exc}")
            result = None
        if result is not None:
            isbn = csv_isbn
            blurb, subjects = result
        else:
            vprint(f"    [warn]  CSV ISBN {csv_isbn} not in OpenLibrary; searching by title+author")

    if not isbn:
        searched = search_openlibrary_isbn(row.title, row.author, cache_dir, slug)
        if searched:
            try:
                result = openlibrary_book_data(searched, cache_dir)
            except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
                vprint(f"    [warn]  ISBN lookup failed for {searched}: {exc}")
                result = None
            isbn = searched
            if result is not None:
                blurb, subjects = result

    if not isbn:
        return None, f"{slug}: unable to resolve ISBN"

    return ResolvedBook(row=row, slug=slug, isbn=isbn, blurb=blurb, subjects=subjects), None


def choose_input_path(path_arg: Optional[str]) -> Path:
    if path_arg:
        return Path(path_arg)
    if DEFAULT_INPUT.exists():
        return DEFAULT_INPUT
    return DEFAULT_SANITIZED_INPUT


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Generate Jekyll book markdown files from a Goodreads CSV export.")
    parser.add_argument("--input", help="Path to Goodreads CSV export")
    parser.add_argument("--books-dir", default="_books", help="Output directory for markdown files")
    parser.add_argument("--cache-dir", default="_cache/openlibrary", help="OpenLibrary cache directory")
    parser.add_argument("--covers-dir", default="images/covers", help="Directory for downloaded cover JPGs")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing files")
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="SLUG[,SLUG...]",
        help="Process only books whose slug matches (comma-separated or repeatable).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Log per-book progress, cache hits, network fetches, and timing",
    )
    args = parser.parse_args()

    global VERBOSE
    VERBOSE = args.verbose

    input_path = choose_input_path(args.input)
    if not input_path.exists():
        parser.error(
            f"Input CSV not found: {input_path}. Provide --input /path/to/goodreads_library_export.csv"
        )

    books_dir = Path(args.books_dir)
    cache_dir = Path(args.cache_dir)
    covers_dir = Path(args.covers_dir)

    rows = read_rows(input_path)
    rows = dedupe_rows(rows)

    only_slugs = {s.strip().lower() for item in args.only for s in item.split(",") if s.strip()}
    if only_slugs:
        filtered = [r for r in rows if slugify_title(r.title) in only_slugs]
        missed = only_slugs - {slugify_title(r.title) for r in filtered}
        if missed:
            print(f"Warning: --only slugs not found in CSV: {sorted(missed)}", flush=True)
        if not filtered:
            parser.error(f"No books matched --only {sorted(only_slugs)}")
        rows = filtered

    unresolved: List[str] = []
    missing_blurbs: List[str] = []
    written = 0
    total = len(rows)
    print(f"Processing {total} books from {input_path}", flush=True)

    for index, row in enumerate(rows, start=1):
        book_start = time.monotonic()
        vprint(f"[{index}/{total}] {row.title!r} — {row.author}")
        resolved, error = resolve_book(row, cache_dir)
        if error:
            unresolved.append(error)
            vprint(f"    [skip]  {error}")
            continue
        assert resolved is not None

        ensure_cover(resolved.slug, resolved.isbn, covers_dir, cache_dir)

        target = books_dir / f"{resolved.slug}.md"
        old_front, old_body = ({}, "")
        if target.exists():
            old_front, old_body = parse_markdown(target)

        body = old_body.strip()
        if "review_needs_generation" in old_front:
            review_needs_generation = bool(old_front.get("review_needs_generation"))
        else:
            review_needs_generation = bool(resolved.row.my_rating > 0 and not body)

        recommendations = old_front.get("recommendations", [])
        if not isinstance(recommendations, list):
            recommendations = []
        series_name, series_index = parse_series_info(resolved.row.title)

        front_matter = {
            "layout": "book",
            "slug": resolved.slug,
            "title": resolved.row.title,
            "author": resolved.row.author,
            "isbn": resolved.isbn,
            "shelf": resolved.row.shelf,
            "my_rating": resolved.row.my_rating,
            "date_read": iso_date(resolved.row.date_read),
            "date_added": iso_date(resolved.row.date_added),
            "pages": resolved.row.pages,
            "year_published": resolved.row.year_published or "",
            "publisher": resolved.row.publisher,
            "binding": resolved.row.binding,
            "cover": f"{resolved.slug}.jpg",
            "blurb": resolved.blurb,
            "subjects": resolved.subjects,
            "recommendations": recommendations,
            "series_name": series_name,
            "series_index": series_index if series_index is not None else "",
            "review_needs_generation": review_needs_generation,
        }

        if not resolved.blurb:
            missing_blurbs.append(resolved.slug)

        content = dump_markdown(front_matter, body)
        if args.dry_run:
            print(f"[dry-run] would write {target}")
            vprint(f"    [done]  {time.monotonic() - book_start:.2f}s (dry-run)")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        changed = not target.exists() or target.read_text(encoding="utf-8") != content
        if changed:
            target.write_text(content, encoding="utf-8")
            written += 1
        vprint(
            f"    [done]  {'wrote' if changed else 'unchanged'} {target} "
            f"in {time.monotonic() - book_start:.2f}s"
        )

    print(f"Processed {len(rows)} books. Updated {written} markdown files.")
    if missing_blurbs:
        print("Missing blurbs (manual review):")
        for slug in sorted(set(missing_blurbs)):
            print(f"  - {slug}")
    if unresolved:
        print("Unresolved books:")
        for item in unresolved:
            print(f"  - {item}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
