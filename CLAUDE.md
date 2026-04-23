# Agent workflow for books.fuzzwah.com

- Keep all slugs in strict lower-kebab-case.
- Keep all cover filenames in strict lower-kebab-case.
- Covers live at `images/covers/<slug>.jpg`.
- Do not use git-lfs for cover images.
- Never hand-edit the `cover:` front matter field. `generate_books.py` owns it.
- Never hand-edit `_data/ext_books.yml`. `generate_recommendations.py` owns it.
- To add books, replace `data/goodreads_library_export.csv` with the latest Goodreads export.
- Metadata comes from Google Books (`https://www.googleapis.com/books/v1/volumes`). Requires `GOOGLE_BOOKS_API_KEY` in `.env` (gitignored). Free tier is 1,000 queries/day; the JSON cache at `_cache/gbooks/` makes re-runs free.
- `generate_recommendations.py` requires `BOOK2REC_API_KEY` env var (or `--api-key`). Limit: 20 API calls/day — results are cached in `_cache/book2rec/`. Use `--force` sparingly to bypass cache.
- Run scripts in order:
  1. `python generate_books.py` (add `-v` for per-book progress, cache hits, and network timing; exit 2 = daily quota hit, rerun tomorrow)
  2. `python generate_reviews.py` (optional for newly rated books)
  3. `BOOK2REC_API_KEY=<key> python generate_recommendations.py`
- Commit and push changes to `main` for GitHub Pages deployment.
- Keep `_cache/` out of git.
- The Goodreads export (`data/goodreads_library_export.csv`) is tracked in git so the pipeline runs across dev machines.
