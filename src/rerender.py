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


def load_snapshot(path: Path = SNAPSHOT_PATH, trends_path: Path | None = None, live_path: Path | None = None) -> dict:
    ctx = json.loads(Path(path).read_text(encoding="utf-8"))
    w = ctx["weather"]
    ctx["weather"] = _build(WeatherReport, {**w, "slots": [_build(Slot, s) for s in w.get("slots", [])]})
    if ctx.get("air") is not None:
        ctx["air"] = _build(AirReport, ctx["air"])
    if ctx.get("tide") is not None:
        ctx["tide"] = _build(TideReport, ctx["tide"])
    # Trend luôn lấy bản mới nhất trong data/trends.json (cập nhật 2 giờ/lần)
    from .config import load_config
    from .trends import TRENDS_PATH, for_page, load_store
    _cfg = load_config()
    ctx.setdefault("site_url", _cfg.get("site_url", ""))
    ctx["ai_url"] = _cfg.get("ai_worker_url", "")
    ctx["trends"] = for_page(load_store(trends_path or TRENDS_PATH))
    # Làm mới trong ngày: tin nóng/mới + bảng giá mới nhất (không gọi Gemini)
    from . import live as _live
    lv = _live.load_live(live_path or _live.LIVE_PATH)
    ctx["live"] = _live.for_page(lv)
    if lv.get("quotes"):
        ctx["quotes"] = lv["quotes"]
    ctx["quotes"] = [_build(Quote, q) for q in ctx.get("quotes", [])]
    for layer in ctx.get("layers", []):
        for cat in layer.get("categories", []):
            cat["items"] = [_build(NewsItem, n) for n in cat.get("items", [])]
    # Không tự chèn tin mới trong ngày nữa: trang chỉ đổi khi chạy lại bản tin (nút Update)
    return ctx


def merge_fresh(ctx: dict, cats: dict, cap: int = 6) -> None:
    """Thay tin mới trong ngày vào từng chuyên mục: tin mới đứng đầu, đẩy tin buổi sáng cũ nhất ra.

    Giữ số tin chẵn (lưới 2 cột) và đánh số lại toàn trang."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from .curator import even_count

    tz_vn = ZoneInfo("Asia/Ho_Chi_Minh")
    n = 0
    for layer in ctx.get("layers", []):
        for cat in layer.get("categories", []):
            old = cat["items"]
            fresh = []
            for i, f in enumerate(cats.get(cat["key"], [])):
                ts = datetime.fromisoformat(f["ts"])
                fresh.append(NewsItem(cid=-(i + 1), category=cat["key"], severity="low", title=f["title"],
                                      summary=f.get("summary", ""), developments="", context="", why_it_matters="",
                                      is_update=False, url=f["url"], source=f["source"], published=f["ts"],
                                      ai=False, image=f.get("image", ""), fresh=ts.astimezone(tz_vn).strftime("%H:%M")))
            if fresh:
                target = min(cap, max(len(old), 2))
                items = even_count((fresh + old)[:target])
            else:
                items = old
            for it in items:
                n += 1
                it.num = n
            cat["items"] = items
            cat["first"] = items[0].num if items else 0
            cat["last"] = items[-1].num if items else 0
    ctx["total_items"] = n


def run(path: Path = SNAPSHOT_PATH, out: Path = OUTPUT_PATH) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if not Path(path).exists():
        log.error("Chưa có %s – cần một lần chạy pipeline đầy đủ trước", path)
        return 1
    ctx = load_snapshot(path)
    render(ctx, out_path=out)
    if Path(out).resolve() == OUTPUT_PATH.resolve():
        from .ogimage import make_og
        make_og(ctx)
    log.info("Đã render lại %s từ %s", out, path)
    return 0


if __name__ == "__main__":
    sys.exit(run())
