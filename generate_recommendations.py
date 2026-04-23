#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True))

from book_utils import dump_markdown, parse_markdown
from generate_books import (
    ensure_cover,
    load_json,
    search_openlibrary_isbn,
    slugify_title,
    write_placeholder_cover,
)

BOOK2REC_URL = "https://book2rec.com/mcp"
BOOK2REC_CACHE_DIR = Path("_cache/book2rec")
OL_CACHE_DIR = Path("_cache/openlibrary")
COVERS_DIR = Path("images/covers")
EXT_BOOKS_PATH = Path("_data/ext_books.yml")


def fetch_book2rec(title: str, slug: str, api_key: str, cache_dir: Path) -> List[Dict[str, Any]]:
    cache_path = cache_dir / f"{slug}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    body = json.dumps({"book": title}).encode("utf-8")
    req = urllib.request.Request(
        BOOK2REC_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-API-KEY": api_key,
            "User-Agent": "books-site-generator/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        results = payload.get("result", [])
    except urllib.error.HTTPError as e:
        print(f"  book2rec {e.code} for '{title}': {e.reason}")
        if e.code == 429:
            print("  Daily rate limit hit — stopping.")
            raise
        results = []
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"  book2rec network error for '{title}': {e}")
        return []  # don't cache transient network errors

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results


def ensure_ext_cover(slug: str, title: str, author: str) -> None:
    cover_path = COVERS_DIR / f"{slug}.jpg"
    if cover_path.exists():
        return
    isbn = search_openlibrary_isbn(title, author, OL_CACHE_DIR, slug)
    if isbn:
        ensure_cover(slug, isbn, COVERS_DIR, OL_CACHE_DIR)
    else:
        write_placeholder_cover(cover_path)


def load_ext_books(path: Path) -> Dict[str, Dict]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return {entry["slug"]: entry for entry in data}


def save_ext_books(path: Path, ext_books: Dict[str, Dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = sorted(ext_books.values(), key=lambda b: b["slug"])
    path.write_text(
        yaml.safe_dump(entries, sort_keys=False, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate book2rec recommendations for each book.")
    parser.add_argument("--books-dir", default="_books")
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--api-key", default=os.environ.get("BOOK2REC_API_KEY", ""))
    parser.add_argument("--force", action="store_true", help="Re-fetch all (ignores cache; use sparingly — 20 req/day limit)")
    args = parser.parse_args()

    if not args.api_key:
        print("Error: set BOOK2REC_API_KEY environment variable or pass --api-key")
        return 1

    books_dir = Path(args.books_dir)

    local_slugs: set[str] = set()
    entries = []
    for path in sorted(books_dir.glob("*.md")):
        fm, body = parse_markdown(path)
        slug = str(fm.get("slug") or path.stem)
        local_slugs.add(slug)
        entries.append({
            "path": path,
            "front_matter": fm,
            "body": body,
            "slug": slug,
            "title": str(fm.get("title", "")),
        })

    ext_books = load_ext_books(EXT_BOOKS_PATH)
    updated = 0
    api_calls = 0

    for book in entries:
        cache_path = BOOK2REC_CACHE_DIR / f"{book['slug']}.json"
        if args.force and cache_path.exists():
            cache_path.unlink()

        was_cached = cache_path.exists()
        bare_title = re.sub(r"\s*\([^)]*#\d+[^)]*\)\s*$", "", book["title"]).strip()
        print(f"{'[cached]' if was_cached else '[api]   '} {bare_title}", flush=True)
        if not was_cached:
            time.sleep(2)
        results = fetch_book2rec(bare_title, book["slug"], args.api_key, BOOK2REC_CACHE_DIR)
        if not was_cached and results is not None:
            api_calls += 1

        rec_slugs: List[str] = []
        for rec in results[: args.top]:
            rec_title = rec.get("Book Title", "")
            rec_author = rec.get("Book Author", "")
            if not rec_title:
                continue
            rec_slug = slugify_title(rec_title)
            rec_slugs.append(rec_slug)

            if rec_slug not in local_slugs and rec_slug not in ext_books:
                ext_books[rec_slug] = {
                    "slug": rec_slug,
                    "title": rec_title,
                    "author": rec_author,
                    "cover": f"{rec_slug}.jpg",
                    "amazon_url": rec.get("Amazon Purchase Link", ""),
                    "book2rec_url": rec.get("Book2Rec Book Page", ""),
                }
                print(f"  fetching cover for external book: {rec_title}")
                ensure_ext_cover(rec_slug, rec_title, rec_author)

        fm = book["front_matter"]
        if fm.get("recommendations") != rec_slugs:
            fm["recommendations"] = rec_slugs
            book["path"].write_text(dump_markdown(fm, book["body"]), encoding="utf-8")
            updated += 1

    save_ext_books(EXT_BOOKS_PATH, ext_books)
    print(f"Updated {updated} book(s). Made {api_calls} live API call(s) to book2rec.")
    if api_calls > 15:
        print(f"Warning: {api_calls} API calls made — approaching 20/day limit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
