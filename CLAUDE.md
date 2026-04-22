# Agent workflow for books.fuzzwah.com

- Keep all slugs in strict lower-kebab-case.
- Keep all cover filenames in strict lower-kebab-case.
- Covers live at `images/covers/<slug>.jpg`.
- Do not use git-lfs for cover images.
- Never hand-edit the `cover:` front matter field. `generate_books.py` owns it.
- To add books, replace `data/goodreads_library_export.csv` with the latest Goodreads export.
- Run scripts in order:
  1. `python generate_books.py` (add `-v` for per-book progress, cache hits, and network timing)
  2. `python generate_reviews.py` (optional for newly rated books)
  3. `python generate_recommendations.py`
- Commit and push changes to `main` for GitHub Pages deployment.
- Keep `_cache/` out of git.
- The Goodreads export (`data/goodreads_library_export.csv`) is tracked in git so the pipeline runs across dev machines.
