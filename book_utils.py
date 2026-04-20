#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

import yaml


def parse_markdown(path: Path) -> Tuple[Dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, text
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        return {}, ""
    front_matter = yaml.safe_load(parts[1]) or {}
    body = parts[2]
    return front_matter, body


def dump_markdown(front_matter: Dict[str, Any], body: str) -> str:
    yaml_text = yaml.safe_dump(front_matter, sort_keys=False, allow_unicode=True).strip()
    normalized_body = body.rstrip()
    return f"---\n{yaml_text}\n---\n" + (f"{normalized_body}\n" if normalized_body else "\n")
