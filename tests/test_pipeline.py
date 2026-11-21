from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from src.curator import CuratedItem, hydrate
from src.news import Article, add_to_history, normalize_url, prune_history, url_hash, window_start
from src.renderer import render
from src.weather import Slot, build_slots, make_advice, met_symbol_to_wmo, met_to_hourly

VN = ZoneInfo("Asia/Ho_Chi_Minh")


# ---------- time window ----------

def test_weekday_window_is_26_hours():
    now = datetime(2026, 11, 18, 7, 10, tzinfo=VN)  # Wednesday
    assert now.weekday() == 2
    assert now - window_start(now) == timedelta(hours=26)


def test_monday_window_covers_from_saturday_0730():
    now = datetime(2026, 11, 23, 7, 10, tzinfo=VN)  # Monday
    assert now.weekday() == 0
    start = window_start(now)
    saturday = datetime(2026, 11, 21, 7, 30, tzinfo=VN)
    assert start <= saturday
    assert now - start >= timedelta(hours=50)
    assert now - start < timedelta(hours=51)


def test_monday_late_run_still_reaches_saturday_0730():
    now = datetime(2026, 11, 23, 11, 0, tzinfo=VN)
    assert window_start(now) == datetime(2026, 11, 21, 7, 30, tzinfo=VN)


def test_window_uses_config_override():
    now = datetime(2026, 11, 19, 7, 0, tzinfo=VN)
    assert now - window_start(now, {"window_hours": 12}) == timedelta(hours=12)


def test_window_requires_aware_datetime():
    with pytest.raises(ValueError):
        window_start(datetime(2026, 11, 19, 7, 0))


# ---------- weather advice ----------

def _slot(label, code, prob=0, mm=0.0, uv=0.0, gust=10):
    return Slot(key=label, label=label, hours="", temp_min=26, temp_max=31, code=code,
                rain_prob=prob, rain_mm=mm, uv_max=uv, gust_max=gust)


def test_thunderstorm_triggers_warning_and_raincoat():
    lines = make_advice([_slot("Sáng", 1), _slot("Trưa", 2, uv=8), _slot("Chiều tối", 95, prob=80, mm=6)])
    text = " ".join(lines)
    assert len(lines) <= 2
    assert "áo mưa" in text
    assert "giông lốc" in text
    assert "chống nắng" in text


def test_heavy_rain_triggers_flood_warning():
    lines = make_advice([_slot("Sáng", 3), _slot("Trưa", 63, prob=70, mm=8), _slot("Chiều tối", 65, prob=90, mm=25)])
    text = " ".join(lines)
    assert "ngập cục bộ" in text
    assert "giông" not in text


def test_strong_gust_without_thunder_code_warns():
    text = " ".join(make_advice([_slot("Sáng", 3, gust=65), _slot("Trưa", 3), _slot("Chiều tối", 3)]))
    assert "giông lốc" in text


def test_calm_day_no_warning():
    lines = make_advice([_slot("Sáng", 0, uv=2), _slot("Trưa", 1, uv=4), _slot("Chiều tối", 2)])
    assert lines == ["Thời tiết ổn định, không cần áo mưa"]


def test_no_data():
    assert make_advice([Slot(key="m", label="Sáng", hours="")]) == ["Chưa có dữ liệu thời tiết"]


def test_build_slots_aggregates_hours():
    times = [f"2026-11-21T{h:02d}:00" for h in range(24)]
    hourly = {
        "time": times,
        "temperature_2m": [20 + h * 0.5 for h in range(24)],
        "precipitation_probability": [10] * 17 + [60] * 7,
        "precipitation": [0.0] * 17 + [1.5] * 7,
        "weather_code": [1] * 18 + [95] + [61] * 5,
        "uv_index": [0] * 11 + [9] * 4 + [0] * 9,
        "wind_gusts_10m": [15] * 24,
    }
    morning, noon, evening = build_slots(hourly)
    assert (morning.temp_min, morning.temp_max) == (24, 24)  # 23.5..24.5 rounded (banker's)
    assert noon.uv_max == 9
    assert evening.code == 95 and evening.condition.startswith("Dông")
    assert evening.rain_prob == 60
    assert evening.rain_mm == 6.0  # hours 17..20


# ---------- history ----------

def test_prune_history_drops_items_older_than_7_days():
    now = datetime(2026, 11, 21, 0, 10, tzinfo=timezone.utc)
    history = {"items": [
        {"hash": "a", "title": "cũ", "ts": (now - timedelta(days=8)).isoformat()},
        {"hash": "b", "title": "biên", "ts": (now - timedelta(days=6, hours=23)).isoformat()},
        {"hash": "c", "title": "mới", "ts": now.isoformat()},
        {"hash": "d", "title": "hỏng", "ts": "not-a-date"},
        {"hash": "e", "title": "thiếu ts"},
    ]}
    kept = prune_history(history, now, days=7)
    assert [i["hash"] for i in kept["items"]] == ["b", "c"]


def test_add_to_history_dedups_by_url_hash():
    now = datetime(2026, 11, 21, tzinfo=timezone.utc)
    a = Article(title="X", url="https://vnexpress.net/a.html?utm_source=rss", source="VnExpress", published=now)
    b = Article(title="X2", url="https://www.vnexpress.net/a.html", source="VnExpress", published=now)
    h = add_to_history({"items": []}, [a, b], now)
    assert len(h["items"]) == 1
    assert h["items"][0]["hash"] == url_hash("https://vnexpress.net/a.html")


def test_parse_loose_tuoitre_date():
    from src.news import parse_loose_date

    dt = parse_loose_date("11/21/2026 1:29:00 PM")
    assert dt == datetime(2026, 11, 21, 13, 29, tzinfo=VN)


def test_normalize_url_strips_tracking():
    assert normalize_url("https://WWW.Example.com/x/?utm_medium=a&id=3#frag") == "https://example.com/x?id=3"


# ---------- ID hydration ----------

def _item(cid, cat="geopolitics"):
    return CuratedItem(candidate_id=cid, category=cat, severity="high", title="t", summary="s",
                       developments="d", context="c", why_it_matters="w", is_update=False)


def test_hydrate_maps_urls_and_drops_invalid_and_duplicate_cids():
    now = datetime(2026, 11, 21, tzinfo=timezone.utc)
    cands = [Article(title=f"T{i}", url=f"https://bbc.co.uk/{i}", source="BBC", published=now, cid=i)
             for i in (1, 2)]
    out = hydrate([_item(1), _item(1), _item(99), _item(2, "sports"), _item(2, "economy")], cands, layer=1)
    assert [n.url for n in out["geopolitics"]] == ["https://bbc.co.uk/1"]
    assert [n.url for n in out["economy"]] == ["https://bbc.co.uk/2"]
    assert out["domestic"] == []


def test_hydrate_caps_per_category():
    now = datetime(2026, 11, 21, tzinfo=timezone.utc)
    cands = [Article(title=f"T{i}", url=f"https://x.vn/{i}", source="X", published=now, cid=i) for i in range(1, 9)]
    out = hydrate([_item(i) for i in range(1, 9)], cands, layer=1, max_per_category=5)
    assert len(out["geopolitics"]) == 5


# ---------- renderer ----------

def test_render_is_atomic_and_escapes(tmp_path):
    from src.weather import WeatherReport

    out = tmp_path / "docs" / "index.html"
    ctx = {
        "updated_at": "07:10", "date_str": "Thứ Bảy, 21/11/2026",
        "weather": WeatherReport(location="<b>HCM</b>", slots=[], advice=["ok"]),
        "quotes": [], "sjc_url": "https://sjc.com.vn/gia-vang-online", "layers": [],
        "takeaways": ["a", "b", "c"], "total_items": 0, "ai_degraded": False,
        "weekday": 5, "weekday_name": "Thứ Bảy", "weekday_short": "T7", "serial": "21·11",
        "year": "2026", "date_compact": "20261121",
    }
    render(ctx, out_path=out)
    html = out.read_text(encoding="utf-8")
    assert "&lt;b&gt;HCM&lt;/b&gt;" in html
    assert not (tmp_path / "docs" / "index.html.tmp").exists()


# ---------- retry policy / fallback ----------

class _Err(Exception):
    def __init__(self, code):
        self.code = code


def test_retry_policy():
    from src.curator import is_retryable

    assert is_retryable(_Err(429)) and is_retryable(_Err(503))
    assert not is_retryable(_Err(404)) and not is_retryable(_Err(400))
    assert is_retryable(TimeoutError())


def test_fallback_items_not_marked_ai():
    from src.curator import fallback_layer

    now = datetime(2026, 11, 21, tzinfo=timezone.utc)
    cands = [Article(title="T", url="https://x.vn/1", source="X", published=now, cid=1)]
    out = fallback_layer(1, cands)
    assert out["geopolitics"][0].ai is False


# ---------- Telegram notify ----------

def _summary(**kw):
    s = {
        "date_str": "Thứ Bảy, 21/11/2026", "date_compact": "20261121", "updated_at": "07:12",
        "total_articles": 38,
        "weather": {"location_name": "Q.1 <HCM>", "severity": "alert",
                    "advice": ["Nên mang áo mưa & áo khoác."],
                    "windows": [{"label": "Sáng", "temp_min": 26, "temp_max": 29, "rain_prob": 10},
                                {"label": "Trưa", "temp_min": 31, "temp_max": 33, "rain_prob": 40},
                                {"label": "Chiều tối", "temp_min": 28, "temp_max": 30, "rain_prob": 80}]},
        "takeaways": ["Fed <giữ> lãi suất", "Giá vàng & USD", "Bão số 9 > cấp 12"],
    }
    s.update(kw)
    return s


def test_build_message_escapes_and_has_all_blocks():
    from src.notify import build_message

    msg = build_message(_summary(), "https://user.github.io/daily-briefing/")
    assert msg.startswith("<b>Bản tin sáng · Thứ Bảy, 21/11/2026</b> (07:12)")
    assert "🚨" in msg
    assert "Q.1 &lt;HCM&gt;" in msg and "áo mưa &amp; áo khoác" in msg
    assert "Sáng 26–29° ☔10%" in msg and "Chiều 28–30° ☔80%" in msg
    assert "• Fed &lt;giữ&gt; lãi suất" in msg and "• Bão số 9 &gt; cấp 12" in msg
    assert msg.count("• ") == 3
    assert '<a href="https://user.github.io/daily-briefing/?v=20261121">Đọc bản tin đầy đủ (38 tin) ↗</a>' in msg
    # no raw dynamic '<' left except our own tags
    import re
    assert not re.search(r"<(?!/?b>|a href=|/a>)", msg)


def test_cache_bust_replaces_existing_v():
    from src.notify import with_cache_bust

    assert with_cache_bust("https://x.io/p/?v=1&a=2", "20261121") == "https://x.io/p/?a=2&v=20261121"


def test_notify_skips_safely_without_token(monkeypatch, tmp_path):
    from src import notify

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    called = []
    monkeypatch.setattr(notify, "send", lambda *a, **k: called.append(1) or True)
    assert notify.run(tmp_path / "missing.json") == 0
    assert called == []


def test_send_retries_and_never_logs_token(caplog):
    import requests as rq
    from src.notify import send

    token = "123456:SECRET-TOKEN"
    calls = []

    def boom(url, **kw):
        calls.append(url)
        raise rq.ConnectionError(f"failed to reach {url}")

    with caplog.at_level("INFO"):
        ok = send(token, "1", "hi", post=boom, sleep=lambda s: None)
    assert ok is False and len(calls) == 3
    assert token not in caplog.text


def test_weather_severity_levels():
    from src.weather import weather_severity

    assert weather_severity([_slot("Sáng", 1)]) == "ok"
    assert weather_severity([_slot("Trưa", 2, uv=8)]) == "warn"
    assert weather_severity([_slot("Chiều tối", 95, prob=80, mm=5)]) == "alert"


def test_key_problem_detection():
    from src.curator import is_key_problem

    assert is_key_problem(_Err(429)) and is_key_problem(_Err(403))
    assert not is_key_problem(_Err(503)) and not is_key_problem(_Err(404))


# ---------- MET Norway fallback ----------
def test_met_symbol_mapping():
    assert met_symbol_to_wmo("rainandthunder_day") == 95
    assert met_symbol_to_wmo("lightrainshowers_night") == 80
    assert met_symbol_to_wmo("cloudy") == 3
    assert met_symbol_to_wmo(None) is None


def test_met_to_hourly_keeps_local_today_and_builds_slots():
    def row(utc, temp, mm, sym, gust=None):
        inst = {"air_temperature": temp, "ultraviolet_index_clear_sky": 7.0}
        if gust is not None:
            inst["wind_speed_of_gust"] = gust
        return {"time": utc, "data": {"instant": {"details": inst},
                "next_1_hours": {"summary": {"symbol_code": sym}, "details": {"precipitation_amount": mm}}}}
    payload = {"properties": {"timeseries": [
        row("2026-11-20T23:00:00Z", 26, 0, "fair_day"),            # 06:00 VN 21/11
        row("2026-11-21T00:00:00Z", 27, 0, "fair_day"),            # 07:00 VN
        row("2026-11-21T05:00:00Z", 33, 2.5, "rainshowers_day", gust=15),  # 12:00 VN
        row("2026-11-21T17:00:00Z", 25, 0, "clearsky_night"),      # 00:00 VN 22/11 -> bỏ
    ]}}
    h = met_to_hourly(payload, "2026-11-21")
    assert h["time"][0] == "2026-11-21T06:00" and len(h["time"]) == 3
    assert h["wind_gusts_10m"][2] == 54.0
    slots = build_slots(h)
    assert slots[0].temp_max == 27 and slots[1].code == 81 and slots[1].rain_mm == 2.5
    assert not slots[2].has_data


# ---------- extras: AQI, tide, sun ----------
def test_aqi_levels_and_advice():
    from src.extras import AirReport, air_advice, aqi_level, parse_air
    assert aqi_level(42) == ("Tốt", "ok")
    assert aqi_level(114)[0] == "Kém với người nhạy cảm"
    assert aqi_level(160)[1] == "alert"
    rep = parse_air({"current": {"us_aqi": 94, "pm2_5": 33.24}, "hourly": {"us_aqi": [80, 115, None, 101]}})
    assert rep.ok and rep.aqi_now == 94 and rep.aqi_max == 115 and rep.pm25 == 33.2
    assert "khẩu trang" in air_advice(rep)
    assert air_advice(AirReport(ok=True, aqi_max=60)) is None
    assert not parse_air({}).ok


def test_tide_extremes_finds_high_and_low_today():
    from src.extras import tide_extremes
    times = [f"2026-11-21T{h:02d}:00" for h in range(24)] + ["2026-11-22T00:00"]
    heights = [1.65, 1.25, 0.85, 0.5, 0.26, 0.21, 0.37, 0.65, 0.93, 1.19, 1.41, 1.5, 1.41, 1.2, 0.98,
               0.8, 0.69, 0.71, 0.92, 1.27, 1.63, 1.91, 2.07, 2.06, 1.82]
    ex = tide_extremes(times, heights, "2026-11-21")
    kinds = [e["kind"] for e in ex]
    assert kinds == ["Thấp", "Cao", "Thấp", "Cao"]
    assert ex[0]["time"] == "04:44" and ex[0]["height"] == 0.2  # nội suy giữa 04:00 và 05:00
    assert ex[-1]["time"].startswith("22") and ex[-1]["height"] == 2.1


def test_apply_daily_sun_and_uv():
    from src.weather import WeatherReport, apply_daily
    r = WeatherReport(location="x")
    apply_daily(r, {"sunrise": ["2026-11-21T05:51"], "sunset": ["2026-11-21T17:26"], "uv_index_max": [7.44]})
    assert (r.sunrise, r.sunset, r.uv_day) == ("05:51", "17:26", 7.4)
    apply_daily(r, {})
    assert r.sunrise is None


def test_telegram_message_has_sun_and_aqi():
    from src.notify import build_message
    msg = build_message({"date_str": "Thứ Bảy, 21/11/2026", "updated_at": "07:10", "weather": {
        "advice": ["Nên mặc áo khoác"], "sunrise": "05:51", "sunset": "17:26", "aqi": 114,
        "aqi_label": "Kém với người nhạy cảm"}}, "")
    assert "05:51" in msg and "AQI 114 (Kém với người nhạy cảm)" in msg
