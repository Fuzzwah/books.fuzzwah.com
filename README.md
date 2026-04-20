# books

A Jekyll-powered reading history site for `books.fuzzwah.com`.

## Ruby / Jekyll setup

```bash
# with rbenv
rbenv install 3.2.3
rbenv local 3.2.3
gem install bundler
bundle config set path '.bundle'
bundle install
```

## Python setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Generate content

```bash
# default input: /Users/fuzzwah/Documents/goodreads_library_export.csv
# fallback sample: data/goodreads_sanitized.csv
python generate_books.py
python generate_reviews.py
python generate_recommendations.py
```

## Run locally

```bash
bundle exec jekyll serve
```

## Key files

- `generate_books.py` - Goodreads CSV ingest + OpenLibrary enrichment + markdown generation
- `generate_reviews.py` - idempotent review body generation (`--force` to overwrite)
- `generate_recommendations.py` - idempotent subject-based recommendations
- `_books/` - generated book collection markdown files
