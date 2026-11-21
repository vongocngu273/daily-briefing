"""Entry point: python -m src.main"""
from __future__ import annotations

import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from .config import HISTORY_PATH, SUMMARY_PATH, LAYER_TITLES, LAYERS, OUTPUT_PATH, load_config, tz, weather_location
from .curator import Curator, NewsItem, fallback_layer
from .market import fetch_market
from .news import (add_to_history, fill_missing_images, candidates_for_layer, collect, load_history, prune_history,
                   recent_titles, save_history)
from .renderer import render
from .extras import air_advice, fetch_air, fetch_tide, uv_level
from .weather import fetch_weather, weather_severity

log = logging.getLogger("daily-briefing")

WEEKDAY_SHORT = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
WEEKDAYS = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]


def _tide_high(tide) -> dict | None:
    """Đỉnh triều cao nhất trong ngày (để nhắc triều cường)."""
    highs = [t for t in (getattr(tide, "extremes", None) or []) if t.get("kind") == "Cao"]
    if not highs:
        return None
    top = max(highs, key=lambda t: t["height"])
    return {"place": tide.place, "time": top["time"], "height": top["height"]}


def build_summary(context: dict, local: datetime) -> dict:
    """Compact data for notifications (src.notify). Not committed (.gitignore)."""
    w = context["weather"]
    return {
        "date_str": context["date_str"],
        "date_compact": local.strftime("%Y%m%d"),
        "updated_at": context["updated_at"],
        "total_articles": context["total_items"],
        "weather": {
            "location_name": w.location,
            "severity": weather_severity(w.slots),
            "advice": list(w.advice),
            "sunrise": w.sunrise,
            "sunset": w.sunset,
            "aqi": context["air"].aqi_max if context.get("air") else None,
            "aqi_label": context["air"].label if context.get("air") else None,
            "tide_high": _tide_high(context.get("tide")),
            "windows": [
                {"label": s.label, "hours": s.hours, "temp_min": s.temp_min, "temp_max": s.temp_max,
                 "rain_prob": s.rain_prob, "rain_mm": s.rain_mm, "condition": s.condition}
                for s in w.slots
            ],
        },
        "takeaways": list(context["takeaways"]),
    }


def write_summary(summary: dict, path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def run() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    zone = tz(cfg)
    now = datetime.now(timezone.utc)
    local = now.astimezone(zone)
    ncfg = cfg.get("news", {})
    max_per_cat = int(ncfg.get("max_per_category", 5))

    api_keys = [os.environ.get(n, "").strip() for n in ("GEMINI_API_KEY", "GEMINI_API_KEY_2")]
    api_keys = [k for k in api_keys if k]
    if not api_keys:
        log.error("Thiếu biến môi trường GEMINI_API_KEY")
        return 2

    loc = weather_location(cfg)
    weather = fetch_weather(loc)
    air = fetch_air(loc)
    extra = air_advice(air)
    if extra:
        weather.advice = [a for a in weather.advice if a != "Chưa có dữ liệu thời tiết"][:2] + [extra]
    tcfg = cfg.get("tide", {})
    tide = fetch_tide(float(tcfg.get("lat", 10.38)), float(tcfg.get("lon", 106.98)),
                      tcfg.get("place", "Cần Giờ"), local.strftime("%Y-%m-%d"))
    quotes = fetch_market(cfg)

    history = prune_history(load_history(HISTORY_PATH), now, int(ncfg.get("history_retention_days", 7)))
    articles = collect(cfg, now, history)
    recent = recent_titles(history, int(ncfg.get("recent_titles_for_ai", 150)))

    gcfg = cfg.get("gemini", {})
    model = os.environ.get("GEMINI_MODEL", "").strip() or gcfg.get("model", "gemini-3.8-flash")
    curator = Curator(api_keys, model, int(gcfg.get("max_retries", 4)), float(gcfg.get("temperature", 0.3)),
                      fallback_models=gcfg.get("fallback_models", []),
                      thinking_level=gcfg.get("thinking_level"))

    limit = int(ncfg.get("max_candidates_per_layer", 140))
    cands_by_layer = {layer: candidates_for_layer(articles, layer, limit) for layer in LAYERS}
    failed: set[int] = set()

    def curate(layer: int):
        try:
            return curator.curate_layer(layer, cands_by_layer[layer], recent, max_per_cat)
        except Exception as e:  # noqa: BLE001
            failed.add(layer)
            log.error("Lớp %d: Gemini thất bại, dùng fallback: %s", layer, str(e)[:200])
            return fallback_layer(layer, cands_by_layer[layer], max_per_cat)

    # 3 layer requests in parallel (each is slow); cross-layer dedup applied afterwards in order.
    with ThreadPoolExecutor(max_workers=len(LAYERS)) as ex:
        results = dict(zip(sorted(LAYERS), ex.map(curate, sorted(LAYERS))))
    ai_failures = len(failed)

    layers_out = []
    all_items: list[NewsItem] = []
    used_cids: set[int] = set()
    for layer in sorted(LAYERS):
        by_cat = results[layer]
        cats = []
        for key, label in LAYERS[layer]:
            items = [i for i in by_cat.get(key, []) if i.cid not in used_cids]
            used_cids.update(i.cid for i in items)
            for it in items:
                it.num = len(all_items) + 1
                all_items.append(it)
            cats.append({"key": key, "label": label, "items": items,
                         "first": items[0].num if items else 0, "last": items[-1].num if items else 0})
        layers_out.append({"id": layer, "title": LAYER_TITLES[layer], "categories": cats})
    fill_missing_images(all_items)
    log.info("Ảnh minh hoạ: %d/%d tin", sum(1 for i in all_items if i.image), len(all_items))

    takeaways: list[str] = []
    try:
        takeaways = curator.takeaways(all_items)
    except Exception as e:  # noqa: BLE001
        log.error("Không tạo được 3 điều cần nhớ: %s", str(e)[:200])

    by_cid = {a.cid: a for a in articles}
    # Only AI-curated items count as "published"; fallback headlines stay eligible next run.
    published_articles = [by_cid[i.cid] for i in all_items if i.ai and i.cid in by_cid]
    history = add_to_history(history, published_articles, now)

    context = {
        "updated_at": local.strftime("%H:%M"),
        "date_str": f"{WEEKDAYS[local.weekday()]}, {local.strftime('%d/%m/%Y')}",
        "weather": weather,
        "air": air,
        "tide": tide,
        "uv_label": uv_level(weather.uv_day),
        "quotes": quotes,
        "sjc_url": cfg.get("market", {}).get("sjc_url", "https://sjc.com.vn/gia-vang-online"),
        "layers": layers_out,
        "takeaways": takeaways,
        "total_items": len(all_items),
        "ai_degraded": ai_failures > 0,
        "weekday": local.weekday(),
        "weekday_name": WEEKDAYS[local.weekday()],
        "weekday_short": WEEKDAY_SHORT[local.weekday()],
        "serial": local.strftime("%d·%m"),
        "year": local.strftime("%Y"),
        "date_compact": local.strftime("%Y%m%d"),
    }
    render(context)
    write_summary(build_summary(context, local), SUMMARY_PATH)
    save_history(history, HISTORY_PATH)
    log.info("Đã xuất %d tin (model %s) -> %s", len(all_items), curator.model, OUTPUT_PATH)
    if ai_failures == len(LAYERS):
        log.error("Cả %d lớp đều thất bại khi gọi Gemini", ai_failures)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run())
