# Agent workflow for books.fuzzwah.com

- Keep all slugs in strict lower-kebab-case.
- Keep all cover filenames in strict lower-kebab-case.
- Covers live at `images/covers/<slug>.jpg`.
- Do not use git-lfs for cover images.
- Never hand-edit the `cover:` front matter field. `generate_books.py` owns it.
- To add books, replace `goodreads_library_export.csv` at the repo root with the latest Goodreads export.
- Run scripts in order:
  1. `python generate_books.py`
  2. `python generate_reviews.py` (optional for newly rated books)
  3. `python generate_recommendations.py`
- Commit and push changes to `main` for GitHub Pages deployment.
- Keep `_cache/` out of git.
- The Goodreads export (`goodreads_library_export.csv`) is tracked in git.
