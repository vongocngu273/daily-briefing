"""RSS collection, time-window filtering and history-based dedup."""
from __future__ import annotations

import calendar
import hashlib
import html
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import feedparser
import requests

log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (compatible; daily-briefing/1.0; +https://github.com/)"
TRACKING_PARAMS = re.compile(r"^(utm_|fbclid|gclid|ref$|refsrc|cmpid|ocid)", re.I)


@dataclass
class Article:
    title: str
    url: str
    source: str
    published: datetime  # aware, UTC
    summary: str = ""
    layers: list[int] = field(default_factory=list)
    cid: int = 0

    @property
    def url_hash(self) -> str:
        return url_hash(self.url)


# ---------- time window ----------

def window_start(now: datetime, cfg_news: dict | None = None) -> datetime:
    """Start of the news window.

    Normal day: now - 26h. Monday (local): extend to 50h, and at least back to
    Saturday 07:30 local so the whole weekend is covered."""
    cfg_news = cfg_news or {}
    hours = int(cfg_news.get("window_hours", 26))
    monday_hours = int(cfg_news.get("monday_window_hours", 50))
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if now.weekday() == 0:
        saturday = (now - timedelta(days=2)).replace(hour=7, minute=30, second=0, microsecond=0)
        return min(now - timedelta(hours=monday_hours), saturday)
    return now - timedelta(hours=hours)


# ---------- url / history ----------

def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not TRACKING_PARAMS.match(k)]
    netloc = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower() or "https", netloc, path, urlencode(query), ""))


def url_hash(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()[:20]


def load_history(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            return {"items": []}
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return {"items": []}


def prune_history(history: dict, now: datetime, days: int = 7) -> dict:
    cutoff = now - timedelta(days=days)
    kept = []
    for item in history.get("items", []):
        try:
            ts = datetime.fromisoformat(item["ts"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except (KeyError, TypeError, ValueError):
            continue
        if ts >= cutoff:
            kept.append(item)
    return {"items": kept}


def add_to_history(history: dict, articles: list[Article], now: datetime) -> dict:
    seen = {i["hash"] for i in history.get("items", [])}
    items = list(history.get("items", []))
    for a in articles:
        h = a.url_hash
        if h in seen:
            continue
        seen.add(h)
        items.append({"hash": h, "title": a.title, "ts": now.astimezone(timezone.utc).isoformat(timespec="seconds")})
    return {"items": items}


def save_history(history: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, path)


def recent_titles(history: dict, limit: int = 150) -> list[str]:
    items = sorted(history.get("items", []), key=lambda i: i.get("ts", ""), reverse=True)
    return [i["title"] for i in items[:limit] if i.get("title")]


# ---------- RSS ----------

_TAG = re.compile(r"<[^>]+>")


def clean_text(s: str, limit: int = 400) -> str:
    s = html.unescape(_TAG.sub(" ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit]


_VN = ZoneInfo("Asia/Ho_Chi_Minh")
_LOOSE_FORMATS = ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S")


def parse_loose_date(raw: str) -> datetime | None:
    """Non-RFC dates (e.g. Tuổi Trẻ: '11/21/2026 1:29:00 PM'), assumed Vietnam local time."""
    s = re.sub(r"\s+", " ", (raw or "").replace(" ", " ").replace("\xa0", " ")).strip()
    for fmt in _LOOSE_FORMATS:
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=_VN).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _entry_time(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc)
    for key in ("published", "updated"):
        dt = parse_loose_date(entry.get(key, ""))
        if dt:
            return dt
    return None


def _strip_gnews_suffix(title: str, source: str) -> str:
    # Google News: "Headline - Reuters"
    m = re.match(r"^(.*)\s+[-–—]\s+([^-–—]{2,40})$", title)
    if m:
        return m.group(1).strip()
    return title


def parse_feed(content: bytes, feed_cfg: dict) -> list[Article]:
    parsed = feedparser.parse(content)
    out = []
    is_gnews = "news.google.com" in feed_cfg["url"]
    for e in parsed.entries:
        link = (e.get("link") or "").strip()
        title = clean_text(e.get("title", ""), 300)
        published = _entry_time(e)
        if not link or not title or not published:
            continue
        source = feed_cfg["source"]
        if is_gnews:
            src = e.get("source")
            src_title = src.get("title") if isinstance(src, dict) else getattr(src, "title", None)
            if src_title:
                source = src_title
            title = _strip_gnews_suffix(title, source)
        summary = "" if is_gnews else clean_text(e.get("summary", ""))
        out.append(Article(title=title, url=link, source=source, published=published,
                           summary=summary, layers=list(feed_cfg.get("layers", [1, 2, 3]))))
    return out


def fetch_feed(feed_cfg: dict, timeout: int = 20) -> list[Article]:
    for attempt in range(2):
        try:
            r = requests.get(feed_cfg["url"], headers={"User-Agent": UA}, timeout=timeout)
            r.raise_for_status()
            return parse_feed(r.content, feed_cfg)
        except Exception as e:  # noqa: BLE001
            log.warning("RSS %s lỗi (lần %d): %s", feed_cfg["source"], attempt + 1, type(e).__name__)
    return []


def collect(cfg: dict, now: datetime, history: dict) -> list[Article]:
    """Fetch all feeds, filter by window, drop already-published, merge duplicates."""
    feeds = cfg.get("feeds", [])
    start = window_start(now, cfg.get("news"))
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(fetch_feed, feeds))
    published = {i["hash"] for i in history.get("items", [])}
    by_hash: dict[str, Article] = {}
    by_title: dict[str, str] = {}
    total = 0
    for feed_cfg, arts in zip(feeds, results):
        log.info("RSS %-14s %3d bài | %s", feed_cfg["source"], len(arts), urlsplit(feed_cfg["url"]).path[:40])
        for a in arts:
            total += 1
            if a.published < start or a.published > now + timedelta(hours=1):
                continue
            h = a.url_hash
            if h in published:
                continue
            tkey = re.sub(r"\W+", "", a.title.lower())
            if h in by_hash or tkey in by_title:
                existing = by_hash.get(h) or by_hash[by_title[tkey]]
                existing.layers = sorted(set(existing.layers) | set(a.layers))
                if not existing.summary and a.summary:
                    existing.summary = a.summary
                continue
            by_hash[h] = a
            by_title[tkey] = h
    arts = sorted(by_hash.values(), key=lambda a: a.published, reverse=True)
    for i, a in enumerate(arts, start=1):
        a.cid = i
    log.info("Tin: %d tổng, %d trong cửa sổ từ %s, chưa đăng", total, len(arts),
             start.astimezone(ZoneInfo("Asia/Ho_Chi_Minh")).strftime("%a %d/%m %H:%M"))
    return arts


def candidates_for_layer(arts: list[Article], layer: int, limit: int = 140) -> list[Article]:
    """Pick up to `limit` candidates for a layer, round-robin across sources for diversity."""
    pool = [a for a in arts if layer in a.layers]
    buckets: dict[str, list[Article]] = {}
    for a in pool:  # already newest-first
        buckets.setdefault(a.source, []).append(a)
    out: list[Article] = []
    while len(out) < limit and any(buckets.values()):
        for src in list(buckets):
            if buckets[src]:
                out.append(buckets[src].pop(0))
                if len(out) >= limit:
                    break
    return out
