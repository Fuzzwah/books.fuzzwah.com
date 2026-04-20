#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from book_utils import dump_markdown, parse_markdown

DEFAULT_INPUT = Path("/Users/fuzzwah/Documents/goodreads_library_export.csv")
DEFAULT_SANITIZED_INPUT = Path("data/goodreads_sanitized.csv")
ALLOWED_SHELVES = {"read", "currently-reading", "to-read"}


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


def slugify_title(title: str) -> str:
    stripped = re.sub(r"\s*\([^)]*#\d+[^)]*\)\s*$", "", title).strip()
    norm = unicodedata.normalize("NFKD", stripped).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", norm.lower()).strip("-")
    return slug or "book"


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def fetch_json(url: str, cache_path: Path, timeout: int = 20) -> Dict[str, Any]:
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    req = urllib.request.Request(url, headers={"User-Agent": "books-site-generator/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = response.read().decode("utf-8")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(payload, encoding="utf-8")
    return json.loads(payload)


def search_openlibrary_isbn(title: str, author: str, cache_dir: Path, slug: str) -> str:
    params = urllib.parse.urlencode({"title": title, "author": author, "limit": 5})
    cache_path = cache_dir / f"search-{slug}.json"
    try:
        data = fetch_json(f"https://openlibrary.org/search.json?{params}", cache_path)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError):
        return ""
    docs = data.get("docs", [])
    for doc in docs:
        for candidate in doc.get("isbn", []):
            isbn = clean_isbn(candidate)
            if isbn:
                return isbn
    return ""


def extract_description(work_data: Dict[str, Any]) -> str:
    description = work_data.get("description")
    if isinstance(description, str):
        return description.strip()
    if isinstance(description, dict):
        return clean_value(description.get("value"))
    return ""


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


def ensure_cover(slug: str, isbn: str, covers_dir: Path, cache_dir: Path) -> None:
    cover_path = covers_dir / f"{slug}.jpg"
    cover_meta_path = cache_dir / "cover_sources.json"
    cover_sources = load_json(cover_meta_path, {})
    cover_url = f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg"

    if cover_path.exists() and cover_sources.get(slug) == cover_url:
        return

    try:
        req = urllib.request.Request(cover_url, headers={"User-Agent": "books-site-generator/1.0"})
        with urllib.request.urlopen(req, timeout=20) as response:
            content_type = response.headers.get("Content-Type", "")
            data = response.read()
        if "image" not in content_type.lower() or not data:
            raise ValueError("Cover URL did not return an image")
        resize_and_save_cover(data, cover_path)
        cover_sources[slug] = cover_url
        cover_meta_path.parent.mkdir(parents=True, exist_ok=True)
        cover_meta_path.write_text(json.dumps(cover_sources, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:
        if not cover_path.exists():
            write_placeholder_cover(cover_path)


def openlibrary_book_data(isbn: str, cache_dir: Path) -> Tuple[str, List[str]]:
    isbn_cache = cache_dir / f"{isbn}.json"
    isbn_data = fetch_json(f"https://openlibrary.org/isbn/{isbn}.json", isbn_cache)

    work_key = ""
    works = isbn_data.get("works") or []
    if works and isinstance(works[0], dict):
        work_key = works[0].get("key", "")

    work_data: Dict[str, Any] = {}
    if work_key:
        work_id = work_key.strip("/").replace("/", "-")
        work_cache = cache_dir / f"{work_id}.json"
        work_data = fetch_json(f"https://openlibrary.org{work_key}.json", work_cache)

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
    isbn = row.isbn13 or row.isbn10
    if not isbn:
        isbn = search_openlibrary_isbn(row.title, row.author, cache_dir, slug)
    if not isbn:
        return None, f"{slug}: unable to resolve ISBN"

    try:
        blurb, subjects = openlibrary_book_data(isbn, cache_dir)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError):
        blurb, subjects = "", []
    return ResolvedBook(row=row, slug=slug, isbn=isbn, blurb=blurb, subjects=subjects), None


def choose_input_path(path_arg: Optional[str]) -> Path:
    if path_arg:
        return Path(path_arg)
    if DEFAULT_INPUT.exists():
        return DEFAULT_INPUT
    return DEFAULT_SANITIZED_INPUT


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Jekyll book markdown files from a Goodreads CSV export.")
    parser.add_argument("--input", help="Path to Goodreads CSV export")
    parser.add_argument("--books-dir", default="_books", help="Output directory for markdown files")
    parser.add_argument("--cache-dir", default="_cache/openlibrary", help="OpenLibrary cache directory")
    parser.add_argument("--covers-dir", default="images/covers", help="Directory for downloaded cover JPGs")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing files")
    args = parser.parse_args()

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

    unresolved: List[str] = []
    missing_blurbs: List[str] = []
    written = 0

    for row in rows:
        resolved, error = resolve_book(row, cache_dir)
        if error:
            unresolved.append(error)
            continue
        assert resolved is not None

        ensure_cover(resolved.slug, resolved.isbn, covers_dir, cache_dir)

        target = books_dir / f"{resolved.slug}.md"
        old_front, old_body = ({}, "")
        if target.exists():
            old_front, old_body = parse_markdown(target)

        body = old_body.strip()
        review_needs_generation = bool(resolved.row.my_rating > 0 and not body)
        if body:
            review_needs_generation = False

        recommendations = old_front.get("recommendations", [])
        if not isinstance(recommendations, list):
            recommendations = []

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
            "review_needs_generation": review_needs_generation,
        }

        if not resolved.blurb:
            missing_blurbs.append(resolved.slug)

        content = dump_markdown(front_matter, body)
        if args.dry_run:
            print(f"[dry-run] would write {target}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or target.read_text(encoding="utf-8") != content:
            target.write_text(content, encoding="utf-8")
            written += 1

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
