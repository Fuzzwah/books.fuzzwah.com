#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

uv venv "$SCRIPT_DIR/.venv"
uv pip install --python "$SCRIPT_DIR/.venv/bin/python" -r "$SCRIPT_DIR/requirements.txt"

ln -sf /home/fuz/code/books/.env "$SCRIPT_DIR/.env"

echo "Workspace ready. Activate with: source .venv/bin/activate"
