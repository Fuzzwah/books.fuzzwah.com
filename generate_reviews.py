#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List

from book_utils import dump_markdown, parse_markdown


def build_review(title: str, author: str, rating: int, subjects: List[str]) -> str:
    tones = {
        5: "I loved how confidently this book delivers on its ideas and emotional impact.",
        4: "I really enjoyed this and found it consistently engaging and thoughtfully put together.",
        3: "This was a mixed read for me, with strong moments alongside some clear weaknesses.",
        2: "I struggled with this more than I expected, even though a few elements still worked.",
        1: "I was disappointed by this overall, despite trying to meet it on its own terms.",
    }
    subject_text = ""
    if subjects:
        subject_text = f" It touches on {', '.join(subjects[:3]).lower()}, which gave it an interesting angle."

    review = (
        f"{title} by {author} left a clear impression on me. "
        f"{tones.get(rating, tones[3])} "
        f"The pacing, character work, and central themes gave me enough to think about after finishing.{subject_text} "
        "It may not work for every reader, but it feels significant within its genre and worth recommending with context."
    )

    words = review.split()
    if len(words) < 50:
        review += " I appreciated what it was trying to do and would still discuss it with other readers."
        words = review.split()
    if len(words) > 80:
        review = " ".join(words[:80]).rstrip(" ,.;") + "."
    return review


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate review text for books marked review_needs_generation.")
    parser.add_argument("--books-dir", default="_books", help="Directory containing book markdown files")
    parser.add_argument("--force", action="store_true", help="Overwrite existing review bodies")
    args = parser.parse_args()

    books_dir = Path(args.books_dir)
    updated = 0

    for path in sorted(books_dir.glob("*.md")):
        front_matter, body = parse_markdown(path)
        rating = int(front_matter.get("my_rating", 0) or 0)
        needs = bool(front_matter.get("review_needs_generation", False))
        has_body = bool(body.strip())

        if rating <= 0:
            continue
        if has_body and not args.force:
            continue
        if not needs and not args.force:
            continue

        review = build_review(
            title=str(front_matter.get("title", "Untitled")),
            author=str(front_matter.get("author", "Unknown Author")),
            rating=rating,
            subjects=front_matter.get("subjects", []) if isinstance(front_matter.get("subjects"), list) else [],
        )

        front_matter["review_needs_generation"] = False
        content = dump_markdown(front_matter, review)

        if path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8")
            updated += 1

    print(f"Updated {updated} review(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
