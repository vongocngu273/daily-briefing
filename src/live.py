"""Làm mới trong ngày (không gọi Gemini): Tin nóng / Tin mới, bảng giá, trend, ảnh chia sẻ.

"Nóng" = cùng một sự kiện được nhiều báo đưa + khớp từ khoá Google Trends VN + còn mới.
Chỉ dùng tiêu đề gốc của báo (không tóm tắt AI). Run: python -m src.live
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import ROOT, load_config

log = logging.getLogger("daily-briefing.live")

LIVE_PATH = ROOT / "data" / "live.json"
WINDOW_HOURS = 12
MAX_ITEMS = 6
VN_SOURCES = {"VnExpress", "Tuổi Trẻ", "VietnamPlus", "BBC Tiếng Việt", "Tinh tế"}
_VN_CHARS = re.compile(r"[ăâđêôơưàáạảãằắặẳẵầấậẩẫèéẹẻẽềếệểễìíịỉĩòóọỏõồốộổỗờớợởỡùúụủũừứựửữỳýỵỷỹ]", re.I)


def _syllables(title: str) -> list[str]:
    t = unicodedata.normalize("NFC", title.lower())
    return [w for w in re.findall(r"\w+", t) if not w.isdigit()]


def _bigrams(title: str) -> set[tuple[str, str]]:
    s = _syllables(title)
    return set(zip(s, s[1:]))


def similar(a: str, b: str, threshold: float = 0.3) -> bool:
    x, y = _bigrams(a), _bigrams(b)
    if not x or not y:
        return False
    return len(x & y) / min(len(x), len(y)) >= threshold


def _ago_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def rank(articles: list, trends_vn: list[dict], now: datetime, limit: int = MAX_ITEMS) -> dict:
    """Gom bài cùng sự kiện, chấm điểm nóng; trả về {'hot': [...], 'latest': [...]}."""
    fresh = [a for a in articles
             if now - timedelta(hours=WINDOW_HOURS) <= a.published <= now + timedelta(minutes=30)
             and _VN_CHARS.search(a.title)]
    fresh.sort(key=lambda a: a.published, reverse=True)

    clusters: list[list] = []
    for a in fresh:
        for c in clusters:
            if similar(a.title, c[0].title):
                c.append(a)
                break
        else:
            clusters.append([a])

    terms = [(t["term"].lower(), t.get("score", 0)) for t in trends_vn if len(t["term"].split()) >= 2]

    def item(a, sources: int = 1, score: float = 0.0) -> dict:
        return {"title": a.title, "url": a.url, "source": a.source, "image": a.image,
                "ts": _ago_iso(a.published), "sources": sources, "score": round(score, 2)}

    scored = []
    for c in clusters:
        rep = max(c, key=lambda a: (bool(a.image), a.source in VN_SOURCES, a.published))
        n_src = len({a.source for a in c})
        newest = max(a.published for a in c)
        age_h = (now - newest).total_seconds() / 3600
        text = " ".join(a.title.lower() for a in c)
        trend = max((math.log10(max(s, 10)) for term, s in terms if term in text), default=0.0)
        score = 3.0 * (n_src - 1) + 1.0 * trend + max(0.0, 2.0 * (1 - age_h / WINDOW_HOURS))
        scored.append((score, item(rep, n_src, score)))
    scored.sort(key=lambda x: -x[0])
    hot = [it for _, it in scored[:limit]]
    hot_urls = {h["url"] for h in hot}
    latest = [item(c[0], len({a.source for a in c})) for c in clusters if c[0].url not in hot_urls][:limit]
    return {"hot": hot, "latest": latest}


def collect_articles(cfg: dict) -> list[tuple[str, object]]:
    """[(feed_url, Article)] từ mọi RSS trừ Google News, bỏ trùng theo URL."""
    from .news import fetch_feed

    feeds = [f for f in cfg.get("feeds", []) if "news.google.com" not in f["url"]]
    with ThreadPoolExecutor(max_workers=8) as ex:
        res = list(ex.map(fetch_feed, feeds))
    seen, out = set(), []
    for f, arts in zip(feeds, res):
        for a in arts:
            if a.url not in seen:
                seen.add(a.url)
                out.append((f["url"], a))
    return out


# Chia tin mới vào chuyên mục mà không cần AI: theo mục RSS của báo, rồi theo từ khoá tiêu đề.
CATEGORY_FEEDS = {
    "geopolitics": ["/the-gioi"],
    "economy": ["/kinh-doanh"],
    "domestic": ["/thoi-su"],
    "tech_ai": ["/so-hoa", "/cong-nghe", "tinhte.vn"],
    "mobile": ["gsmarena.com", "9to5mac.com", "9to5google.com", "macrumors.com"],
    "science_health": ["/khoa-hoc", "/suc-khoe"],
    "sports": ["/the-thao"],
    "culture_society": ["/van-hoa"],
}
CATEGORY_KEYWORDS = {
    "mobile": ["iphone", "ipad", "ios", "android", "samsung", "galaxy", "xiaomi", "oppo", "vivo", "pixel",
               "điện thoại", "smartphone", "máy tính bảng", "apple watch", "airpods"],
    "tech_ai": [" ai ", "trí tuệ nhân tạo", "chatgpt", "openai", "gemini", "chip", "bán dẫn", "nvidia",
                "công nghệ", "phần mềm", "robot"],
    "cyber_digital": ["an ninh mạng", "lừa đảo", "hacker", "tin tặc", "mã độc", "dữ liệu cá nhân", "rò rỉ",
                      "chuyển đổi số", "định danh", "vneid", "deepfake"],
    "environment": ["môi trường", "khí hậu", "ô nhiễm", "bão", "lũ", "mưa lớn", "sạt lở", "nắng nóng",
                    "hạn mặn", "động đất", "rác thải", "phát thải"],
    "science_health": ["bệnh viện", "bác sĩ", "sức khỏe", "dịch", "vắc xin", "ung thư", "nghiên cứu",
                       "nhà khoa học", "y tế"],
    "economy": ["giá vàng", "lãi suất", "chứng khoán", "vn-index", "tỷ giá", "xuất khẩu", "gdp", "lạm phát",
                "doanh nghiệp", "ngân hàng", "bất động sản"],
    "sports": ["bóng đá", "tuyển việt nam", "v-league", "sea games", "world cup", "ngoại hạng", "hlv"],
    "geopolitics": ["nga", "ukraine", "mỹ", "trung quốc", "iran", "israel", "nato", "liên hợp quốc", "eu "],
    "domestic": ["quốc hội", "chính phủ", "thủ tướng", "bộ trưởng", "tp.hcm", "hà nội", "tỉnh"],
    "culture_society": ["văn hóa", "nghệ sĩ", "ca sĩ", "phim", "lễ hội", "du lịch", "giáo dục", "học sinh"],
}
KEYWORD_ORDER = ["mobile", "cyber_digital", "tech_ai", "environment", "science_health", "economy", "sports",
                 "geopolitics", "domestic", "culture_society"]


def categorize(feed_url: str, title: str) -> str | None:
    for key, marks in CATEGORY_FEEDS.items():
        if any(m in feed_url for m in marks):
            if key in ("tech_ai",) and any(k in f" {title.lower()} " for k in CATEGORY_KEYWORDS["mobile"]):
                return "mobile"
            return key
    low = f" {title.lower()} "
    for key in KEYWORD_ORDER:
        if any(k in low for k in CATEGORY_KEYWORDS[key]):
            return key
    return None


def by_category(pairs: list, exclude: list[dict], now: datetime, per_cat: int = 6,
                hours: int = WINDOW_HOURS, since: datetime | None = None) -> dict[str, list[dict]]:
    """Tin mới trong ngày cho từng chuyên mục, bỏ tin đã có trong bản tin (cùng URL hoặc cùng sự kiện)."""
    seen_urls = {e.get("url") for e in exclude}
    seen_titles = [e.get("title", "") for e in exclude]
    out: dict[str, list[dict]] = {}
    for feed_url, a in sorted(pairs, key=lambda p: p[1].published, reverse=True):
        if not (now - timedelta(hours=hours) <= a.published <= now + timedelta(minutes=30)):
            continue
        if since and a.published <= since:
            continue
        cat = categorize(feed_url, a.title)
        if not cat or a.url in seen_urls:
            continue
        if cat != "mobile" and not _VN_CHARS.search(a.title):
            continue
        if any(similar(a.title, t) for t in seen_titles):
            continue
        bucket = out.setdefault(cat, [])
        if len(bucket) >= per_cat:
            continue
        bucket.append({"title": a.title, "url": a.url, "source": a.source, "image": a.image,
                       "ts": _ago_iso(a.published), "sources": 1, "score": 0, "summary": _snippet(a)})
        seen_urls.add(a.url)
        seen_titles.append(a.title)
    return out


def _snippet(a, n: int = 40) -> str:
    """Đoạn mô tả ngắn của báo (RSS), bỏ phần lặp tiêu đề; giữ trọn câu nếu được."""
    from .curator import soft_limit

    text = (a.summary or "").strip()
    if text.lower().startswith(a.title.lower()):
        text = text[len(a.title):].lstrip(" .:-–")
    return soft_limit(text, n)


def _edition_time() -> datetime | None:
    """Giờ bản tin sáng được tạo (từ data/page.json), để chỉ lấy tin đăng sau đó."""
    from zoneinfo import ZoneInfo

    try:
        page = json.loads((ROOT / "data" / "page.json").read_text(encoding="utf-8"))
        local = datetime.strptime(page["date_compact"] + page["updated_at"], "%Y%m%d%H:%M")
        return local.replace(tzinfo=ZoneInfo("Asia/Ho_Chi_Minh")).astimezone(timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def _page_items() -> list[dict]:
    """Tin đã có trong bản tin sáng (data/page.json) để không lặp lại."""
    try:
        page = json.loads((ROOT / "data" / "page.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return [n for layer in page.get("layers", []) for c in layer.get("categories", []) for n in c.get("items", [])]


def for_page(live: dict, tz_name: str = "Asia/Ho_Chi_Minh") -> dict:
    from zoneinfo import ZoneInfo

    upd = live.get("updated")
    label = datetime.fromisoformat(upd).astimezone(ZoneInfo(tz_name)).strftime("%H:%M") if upd else ""

    def fmt(items):
        out = []
        for it in items or []:
            t = datetime.fromisoformat(it["ts"]).astimezone(ZoneInfo(tz_name)).strftime("%H:%M")
            out.append({**it, "time": t})
        return out
    return {"hot": fmt(live.get("hot")), "latest": fmt(live.get("latest")), "updated": label, "updated_iso": upd or "",
            "cats": {k: fmt(v) for k, v in (live.get("cats") or {}).items()}}


def load_live(path: Path = LIVE_PATH) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def update(now: datetime | None = None, path: Path = LIVE_PATH) -> dict:
    from .market import fetch_market
    from .trends import update as update_trends

    now = now or datetime.now(timezone.utc)
    cfg = load_config()
    trends = update_trends(now)
    pairs = collect_articles(cfg)
    live = rank([a for _, a in pairs], trends.get("vn", []), now)
    live["cats"] = by_category(pairs, _page_items(), now, since=_edition_time())
    try:
        live["quotes"] = [asdict(q) for q in fetch_market(cfg)]
    except Exception as e:  # noqa: BLE001
        log.warning("Bảng giá lỗi: %s", type(e).__name__)
    live["updated"] = now.isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(live, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    # bản nhỏ cho nút ⟳ trên trang kiểm tra (cùng origin, không vướng CORS)
    stamp = ROOT / "docs" / "live.json"
    stamp.write_text(json.dumps({"updated": live["updated"]}), encoding="utf-8")
    log.info("Tin nóng %d, tin mới %d, giá %d mã", len(live["hot"]), len(live["latest"]), len(live.get("quotes", [])))
    return live


def run() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    update()
    from .rerender import SNAPSHOT_PATH, run as rerender
    return rerender() if SNAPSHOT_PATH.exists() else 0


if __name__ == "__main__":
    sys.exit(run())
