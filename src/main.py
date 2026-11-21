"""Entry point: python -m src.main"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone

from .config import HISTORY_PATH, LAYER_TITLES, LAYERS, OUTPUT_PATH, load_config, tz, weather_location
from .curator import Curator, NewsItem, fallback_layer
from .market import fetch_market
from .news import (add_to_history, candidates_for_layer, collect, load_history, prune_history,
                   recent_titles, save_history)
from .renderer import render
from .weather import fetch_weather

log = logging.getLogger("daily-briefing")

WEEKDAYS = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]


def run() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    zone = tz(cfg)
    now = datetime.now(timezone.utc)
    local = now.astimezone(zone)
    ncfg = cfg.get("news", {})
    max_per_cat = int(ncfg.get("max_per_category", 5))

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        log.error("Thiếu biến môi trường GEMINI_API_KEY")
        return 2

    weather = fetch_weather(weather_location(cfg))
    quotes = fetch_market(cfg)

    history = prune_history(load_history(HISTORY_PATH), now, int(ncfg.get("history_retention_days", 7)))
    articles = collect(cfg, now, history)
    recent = recent_titles(history, int(ncfg.get("recent_titles_for_ai", 150)))

    gcfg = cfg.get("gemini", {})
    curator = Curator(api_key, gcfg.get("model", "gemini-2.5-flash"), int(gcfg.get("max_retries", 4)),
                      float(gcfg.get("temperature", 0.3)))

    layers_out = []
    all_items: list[NewsItem] = []
    ai_failures = 0
    used_cids: set[int] = set()
    for layer in sorted(LAYERS):
        cands = [a for a in candidates_for_layer(articles, layer, int(ncfg.get("max_candidates_per_layer", 140)))
                 if a.cid not in used_cids]
        try:
            by_cat = curator.curate_layer(layer, cands, recent, max_per_cat)
        except Exception as e:  # noqa: BLE001
            ai_failures += 1
            log.error("Lớp %d: Gemini thất bại, dùng fallback: %s", layer, str(e)[:200])
            by_cat = fallback_layer(layer, cands, max_per_cat)
        cats = []
        for key, label in LAYERS[layer]:
            items = by_cat.get(key, [])
            used_cids.update(i.cid for i in items)
            all_items.extend(items)
            cats.append({"key": key, "label": label, "items": items})
        layers_out.append({"id": layer, "title": LAYER_TITLES[layer], "categories": cats})

    takeaways: list[str] = []
    try:
        takeaways = curator.takeaways(all_items)
    except Exception as e:  # noqa: BLE001
        log.error("Không tạo được 3 điều cần nhớ: %s", str(e)[:200])

    by_cid = {a.cid: a for a in articles}
    published_articles = [by_cid[i.cid] for i in all_items if i.cid in by_cid]
    history = add_to_history(history, published_articles, now)

    context = {
        "updated_at": local.strftime("%H:%M"),
        "date_str": f"{WEEKDAYS[local.weekday()]}, {local.strftime('%d/%m/%Y')}",
        "weather": weather,
        "quotes": quotes,
        "sjc_url": cfg.get("market", {}).get("sjc_url", "https://sjc.com.vn/gia-vang-online"),
        "layers": layers_out,
        "takeaways": takeaways,
        "total_items": len(all_items),
        "ai_degraded": ai_failures > 0,
    }
    render(context)
    save_history(history, HISTORY_PATH)
    log.info("Đã xuất %d tin -> %s", len(all_items), OUTPUT_PATH)
    if ai_failures == len(LAYERS):
        log.error("Cả %d lớp đều thất bại khi gọi Gemini", ai_failures)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run())
