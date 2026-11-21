"""Từ khoá đang hot (Google Trends RSS, không cần API key) cho dòng chữ chạy trên trang.

RSS mỗi lần chỉ trả ~10 từ khoá mới nhất, nên ta gom dần vào data/trends.json và chỉ giữ
những từ khoá trong 24 giờ gần nhất. Run: python -m src.trends  (cập nhật + render lại trang,
không gọi Gemini).
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

from .config import ROOT

log = logging.getLogger("daily-briefing.trends")

RSS_URL = "https://trends.google.com/trending/rss?geo={geo}"
TRENDS_PATH = ROOT / "data" / "trends.json"
GROUPS = {"vn": ["VN"], "world": ["US", "GB"]}
WINDOW_HOURS = 24
UA = "Mozilla/5.0 (compatible; daily-briefing/1.0; +https://github.com/)"


def parse_traffic(label: str | None) -> int:
    """'2000+' / '20K+' / '1M+' -> số nguyên (để xếp hạng)."""
    m = re.match(r"\s*([\d.,]+)\s*([KkMm]?)", label or "")
    if not m:
        return 0
    num = float(m.group(1).replace(",", ""))
    return int(num * {"": 1, "k": 1_000, "m": 1_000_000}[m.group(2).lower()])


def _tag(block: str, name: str) -> str:
    m = re.search(rf"<{name}>(.*?)</{name}>", block, re.S)
    if not m:
        return ""
    raw = m.group(1).strip()
    if raw.startswith("<![CDATA["):
        raw = raw[9:-3]
    return html.unescape(raw).strip()


def parse_rss(xml: str, geo: str) -> list[dict]:
    out = []
    for block in re.findall(r"<item>(.*?)</item>", xml, re.S):
        term = _tag(block, "title")
        if not term:
            continue
        try:
            ts = parsedate_to_datetime(_tag(block, "pubDate")).astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
        traffic = _tag(block, "ht:approx_traffic")
        news_url = _tag(block, "ht:news_item_url")
        out.append({"term": term, "geo": geo, "traffic": traffic, "score": parse_traffic(traffic),
                    "ts": ts.isoformat(), "url": news_url if news_url.startswith("https://") else "",
                    "news": _tag(block, "ht:news_item_title")})
    return out


def fetch_geo(geo: str, timeout: int = 20) -> list[dict]:
    try:
        r = requests.get(RSS_URL.format(geo=geo), headers={"User-Agent": UA}, timeout=timeout)
        r.raise_for_status()
        return parse_rss(r.text, geo)
    except Exception as e:  # noqa: BLE001
        log.warning("Google Trends %s lỗi: %s", geo, type(e).__name__)
        return []


def merge(store: dict, group: str, fresh: list[dict], now: datetime) -> None:
    """Gộp từ khoá mới vào nhóm, bỏ trùng (giữ lượt tìm cao nhất), xoá mục quá 24h."""
    cutoff = now - timedelta(hours=WINDOW_HOURS)
    by_key: dict[str, dict] = {}
    for it in store.get(group, []) + fresh:
        if datetime.fromisoformat(it["ts"]) < cutoff:
            continue
        key = it["term"].casefold()
        old = by_key.get(key)
        if old is None or it["score"] > old["score"] or (it["score"] == old["score"] and it["ts"] > old["ts"]):
            by_key[key] = it
    store[group] = sorted(by_key.values(), key=lambda x: (-x["score"], x["ts"]))


def load_store(path: Path = TRENDS_PATH) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_store(store: dict, path: Path = TRENDS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def update(now: datetime | None = None, path: Path = TRENDS_PATH) -> dict:
    now = now or datetime.now(timezone.utc)
    store = load_store(path)
    for group, geos in GROUPS.items():
        fresh = [it for g in geos for it in fetch_geo(g)]
        merge(store, group, fresh, now)
    store["updated"] = now.isoformat()
    save_store(store, path)
    log.info("Trends: VN %d, thế giới %d từ khoá (24h)", len(store.get("vn", [])), len(store.get("world", [])))
    return store


def for_page(store: dict, limit: int = 15, tz_name: str = "Asia/Ho_Chi_Minh") -> dict:
    """Dữ liệu gọn cho template."""
    from zoneinfo import ZoneInfo

    upd = store.get("updated")
    label = datetime.fromisoformat(upd).astimezone(ZoneInfo(tz_name)).strftime("%H:%M") if upd else ""

    def pick(items):
        return [{"term": i["term"][:1].upper() + i["term"][1:], "traffic": i.get("traffic", ""),
                 "url": i.get("url") or "https://www.google.com/search?q=" + requests.utils.quote(i["term"])}
                for i in items[:limit]]
    return {"vn": pick(store.get("vn", [])), "world": pick(store.get("world", [])), "updated": label}


def run() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    update()
    from .rerender import SNAPSHOT_PATH, run as rerender
    return rerender() if SNAPSHOT_PATH.exists() else 0


if __name__ == "__main__":
    sys.exit(run())
