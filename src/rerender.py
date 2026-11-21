"""Render lại docs/index.html từ bản chụp nội dung gần nhất (data/page.json).

Dùng khi chỉ sửa giao diện (template/CSS): không gọi Gemini, RSS, thời tiết hay thị trường.
Run: python -m src.rerender
"""
from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict, fields, is_dataclass
from pathlib import Path

from .config import OUTPUT_PATH, ROOT
from .curator import NewsItem
from .extras import AirReport, TideReport
from .market import Quote
from .renderer import render
from .weather import Slot, WeatherReport

log = logging.getLogger("daily-briefing.rerender")

SNAPSHOT_PATH = ROOT / "data" / "page.json"


def _plain(obj):
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_plain(v) for v in obj]
    return obj


def _build(cls, data: dict | None):
    if data is None:
        return None
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in names})


def save_snapshot(context: dict, path: Path = SNAPSHOT_PATH) -> None:
    """Lưu toàn bộ dữ liệu đã render (không có toạ độ hay khoá API) để render lại sau."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_plain(context), f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load_snapshot(path: Path = SNAPSHOT_PATH, trends_path: Path | None = None) -> dict:
    ctx = json.loads(Path(path).read_text(encoding="utf-8"))
    w = ctx["weather"]
    ctx["weather"] = _build(WeatherReport, {**w, "slots": [_build(Slot, s) for s in w.get("slots", [])]})
    if ctx.get("air") is not None:
        ctx["air"] = _build(AirReport, ctx["air"])
    if ctx.get("tide") is not None:
        ctx["tide"] = _build(TideReport, ctx["tide"])
    ctx["quotes"] = [_build(Quote, q) for q in ctx.get("quotes", [])]
    # Trend luôn lấy bản mới nhất trong data/trends.json (cập nhật 2 giờ/lần)
    from .trends import TRENDS_PATH, for_page, load_store
    ctx["trends"] = for_page(load_store(trends_path or TRENDS_PATH))
    for layer in ctx.get("layers", []):
        for cat in layer.get("categories", []):
            cat["items"] = [_build(NewsItem, n) for n in cat.get("items", [])]
    return ctx


def run(path: Path = SNAPSHOT_PATH, out: Path = OUTPUT_PATH) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if not Path(path).exists():
        log.error("Chưa có %s – cần một lần chạy pipeline đầy đủ trước", path)
        return 1
    render(load_snapshot(path), out_path=out)
    log.info("Đã render lại %s từ %s", out, path)
    return 0


if __name__ == "__main__":
    sys.exit(run())
