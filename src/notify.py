"""Send the daily briefing summary to Telegram. Run: python -m src.notify

Fail-safe: missing TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID -> warn and exit 0.
The bot token is never written to logs (request URLs are not logged)."""
from __future__ import annotations

import html
import json
import logging
import os
import sys
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from .config import SUMMARY_PATH, load_config

log = logging.getLogger("daily-briefing.notify")

API = "https://api.telegram.org/bot{token}/sendMessage"
SHORT_LABEL = {"Chiều tối": "Chiều"}


def with_cache_bust(url: str, date_compact: str) -> str:
    """Append ?v=YYYYMMDD (replacing any existing v) so browsers load today's page."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "v"]
    query.append(("v", date_compact))
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", urlencode(query), parts.fragment))


def resolve_briefing_url(cfg: dict | None = None) -> str:
    url = os.environ.get("BRIEFING_URL", "").strip()
    if url:
        return url
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()  # owner/name inside Actions
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner.lower()}.github.io/{name}/"
    return (cfg or {}).get("site_url", "")


SLOT_ICON = {"Sáng": "🌄", "Trưa": "☀️", "Chiều": "🌆"}


def _vn(x) -> str:
    return str(x).replace(".", ",")


def _window_line(w: dict) -> str:
    label = SHORT_LABEL.get(w.get("label", ""), w.get("label", ""))
    icon = SLOT_ICON.get(label, "•")
    if w.get("temp_min") is None:
        return f"{icon} {label}: chưa có dữ liệu"
    line = f"{icon} {label}  <b>{w['temp_min']}–{w['temp_max']}°</b>"
    if w.get("rain_prob") is not None:
        line += f"  ·  mưa {w['rain_prob']}%"
    elif w.get("rain_mm") is not None:
        line += f"  ·  mưa {_vn(w['rain_mm'])} mm"
    return line


def build_message(summary: dict, url: str) -> str:
    """Tin Telegram (parse_mode=HTML). Mọi chuỗi động đều qua html.escape."""
    e = html.escape
    w = summary.get("weather", {})
    out = ["<b>☀️ BẢN TIN SÁNG</b>",
           e(" · ".join(x for x in (summary.get("date_str", ""), summary.get("updated_at", "")) if x))]

    loc = w.get("location_name", "")
    out += ["", f"<b>📍 {e(loc) if loc else 'Thời tiết'}</b>"]
    windows = w.get("windows") or []
    out += [_window_line({k: (e(v) if isinstance(v, str) else v) for k, v in x.items()}) for x in windows]
    if w.get("sunrise") and w.get("sunset"):
        out.append(f"🌅 Mặt trời  {e(w['sunrise'])} – {e(w['sunset'])}")
    if w.get("aqi") is not None:
        label = f" · {e(w['aqi_label'])}" if w.get("aqi_label") else ""
        out.append(f"😷 AQI <b>{int(w['aqi'])}</b>{label}")
    tide = w.get("tide_high")
    if tide:
        out.append(f"🌊 Triều cao {e(tide.get('place', ''))}  {e(tide['time'])} ({_vn(tide['height'])} m)")

    advice = [a for a in (w.get("advice") or []) if a]
    if advice:
        head = "🚨 Cảnh báo" if w.get("severity") == "alert" else "💡 Nhắc nhở"
        out += ["", f"<b>{head}</b>"] + [f"• {e(a)}" for a in advice]

    takeaways = [t for t in (summary.get("takeaways") or []) if t][:3]
    if takeaways:
        out += ["", "<b>📌 3 điều cần nhớ</b>"] + [f"{i}. {e(t)}" for i, t in enumerate(takeaways, 1)]

    if url:
        full = with_cache_bust(url, str(summary.get("date_compact", "")))
        total = int(summary.get("total_articles") or 0)
        out += ["", f'👉 <a href="{e(full, quote=True)}">Đọc bản tin đầy đủ · {total} tin</a>']
    return "\n".join(out)


def send(token: str, chat_id: str, text: str, retries: int = 3, timeout: int = 15,
         post=requests.post, sleep=time.sleep) -> bool:
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    for attempt in range(1, retries + 1):
        try:
            r = post(API.format(token=token), json=payload, timeout=timeout)
            if r.status_code == 200 and r.json().get("ok"):
                log.info("Đã gửi Telegram (lần %d)", attempt)
                return True
            try:
                desc = str(r.json().get("description", ""))[:200]
            except ValueError:
                desc = ""
            log.warning("Telegram trả HTTP %s (lần %d/%d): %s", r.status_code, attempt, retries, desc)
            if 400 <= r.status_code < 500 and r.status_code != 429:
                return False  # bad chat id / token / formatting: retry won't help
        except requests.RequestException as ex:
            # Never log str(ex): it can contain the request URL, which embeds the token.
            log.warning("Telegram lỗi mạng (lần %d/%d): %s", attempt, retries, type(ex).__name__)
        if attempt < retries:
            sleep(2 ** attempt)
    return False


def run(summary_path: Path = SUMMARY_PATH) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        log.warning("Thiếu TELEGRAM_BOT_TOKEN hoặc TELEGRAM_CHAT_ID – bỏ qua gửi thông báo")
        return 0
    try:
        summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as ex:
        log.warning("Không đọc được %s (%s) – bỏ qua gửi thông báo", summary_path, type(ex).__name__)
        return 0
    try:
        cfg = load_config()
    except Exception:  # noqa: BLE001
        cfg = {}
    text = build_message(summary, resolve_briefing_url(cfg))
    return 0 if send(token, chat_id, text) else 1


if __name__ == "__main__":
    sys.exit(run())
