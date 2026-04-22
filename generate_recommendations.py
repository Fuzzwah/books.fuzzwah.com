#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

from book_utils import dump_markdown, parse_markdown


STOPWORDS: Set[str] = {
    "about", "above", "after", "again", "against", "also", "among", "another",
    "because", "been", "before", "being", "below", "between", "both", "came",
    "could", "does", "doing", "down", "during", "each", "even", "ever", "every",
    "from", "further", "have", "having", "here", "himself", "into", "itself",
    "just", "knew", "know", "like", "more", "most", "much", "must", "never",
    "next", "none", "nothing", "often", "once", "only", "other", "over", "ours",
    "ourselves", "same", "seem", "seemed", "seems", "should", "since", "some",
    "somehow", "still", "such", "take", "than", "that", "their", "theirs",
    "them", "themselves", "then", "there", "these", "they", "this", "those",
    "through", "toward", "under", "until", "upon", "used", "very", "want",
    "were", "what", "when", "where", "which", "while", "whose", "with",
    "without", "would", "your", "yours",
}

_TOKEN_RE = re.compile(r"[a-z]{4,}")


def tokenize(text: object) -> Set[str]:
    if not isinstance(text, str) or not text:
        return set()
    return {t for t in _TOKEN_RE.findall(text.lower()) if t not in STOPWORDS}


def decade(year_value: object) -> int:
    try:
        year = int(year_value)
    except (TypeError, ValueError):
        return -1
    return (year // 10) * 10


def normalized_subjects(value: object) -> Set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item).strip().lower() for item in value if str(item).strip()}


def score(a: Dict, b: Dict) -> Tuple[int, int, int, int, int, int]:
    same_series = 1 if a["series"] and a["series"] == b["series"] else 0
    same_author = 1 if a["author"] and a["author"] == b["author"] else 0

    tokens_a, tokens_b = a["tokens"], b["tokens"]
    union = len(tokens_a | tokens_b)
    jaccard_bucket = int(len(tokens_a & tokens_b) / union * 1000) if union else 0

    category_overlap = len(a["subjects"] & b["subjects"])
    same_decade = 1 if a["decade"] != -1 and a["decade"] == b["decade"] else 0
    rating_proximity = -abs(a["rating"] - b["rating"])

    return (same_series, same_author, jaccard_bucket, category_overlap, same_decade, rating_proximity)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate blurb-based recommendations for each book.")
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
                "author": str(front_matter.get("author", "")).strip().lower(),
                "series": str(front_matter.get("series_name", "")).strip().lower(),
                "subjects": normalized_subjects(front_matter.get("subjects")),
                "decade": decade(front_matter.get("year_published")),
                "rating": int(front_matter.get("my_rating") or 0),
                "tokens": tokenize(front_matter.get("blurb", "")),
            }
        )

    updated = 0

    for book in entries:
        scored = []
        for other in entries:
            if other["slug"] == book["slug"]:
                continue
            scored.append((score(book, other), other["slug"]))

        # Higher scores rank first; ties break on slug for stability.
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
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
