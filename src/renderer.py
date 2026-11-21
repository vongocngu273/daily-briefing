"""Render docs/index.html atomically with Jinja2 (autoescape on)."""
from __future__ import annotations

import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .config import OUTPUT_PATH, TEMPLATES_DIR


def make_env(templates_dir: Path = TEMPLATES_DIR) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render(context: dict, out_path: Path = OUTPUT_PATH, templates_dir: Path = TEMPLATES_DIR) -> Path:
    html = make_env(templates_dir).get_template("index.html.j2").render(**context)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(html)
    os.replace(tmp, out_path)
    return out_path
