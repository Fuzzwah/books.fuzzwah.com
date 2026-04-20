#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List, Tuple

from book_utils import dump_markdown, parse_markdown


def decade(year_value: object) -> int:
    try:
        year = int(year_value)
    except (TypeError, ValueError):
        return -1
    return (year // 10) * 10


def normalized_subjects(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item).strip().lower() for item in value if str(item).strip()}


def score(book: Dict, other: Dict) -> Tuple[int, int, int, str]:
    shared_subjects = len(book["subjects"] & other["subjects"])
    author_match = 1 if book["author"].lower() == other["author"].lower() else 0
    shared_decade = 1 if book["decade"] != -1 and book["decade"] == other["decade"] else 0
    return (shared_subjects, author_match, shared_decade, other["slug"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate subject-based recommendations for each book.")
    parser.add_argument("--books-dir", default="_books", help="Directory containing book markdown files")
    parser.add_argument("--top", type=int, default=5, help="Number of recommendations per book")
    args = parser.parse_args()

    books_dir = Path(args.books_dir)
    entries: List[Dict] = []

    for path in sorted(books_dir.glob("*.md")):
        front_matter, body = parse_markdown(path)
        slug = str(front_matter.get("slug") or path.stem)
        entries.append(
            {
                "path": path,
                "front_matter": front_matter,
                "body": body,
                "slug": slug,
                "author": str(front_matter.get("author", "")),
                "subjects": normalized_subjects(front_matter.get("subjects")),
                "decade": decade(front_matter.get("year_published")),
            }
        )

    updated = 0

    for book in entries:
        scored = []
        for other in entries:
            if other["slug"] == book["slug"]:
                continue
            scored.append((score(book, other), other["slug"]))

        scored.sort(key=lambda item: item[0], reverse=True)
        recommendations = [slug for _, slug in scored[: args.top]]

        fm = book["front_matter"]
        if fm.get("recommendations") != recommendations:
            fm["recommendations"] = recommendations
            content = dump_markdown(fm, book["body"])
            book["path"].write_text(content, encoding="utf-8")
            updated += 1

    print(f"Updated recommendations for {updated} book(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
