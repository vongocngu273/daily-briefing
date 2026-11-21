from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from src.curator import CuratedItem, hydrate
from src.news import Article, add_to_history, normalize_url, prune_history, url_hash, window_start
from src.renderer import render
from src.weather import Slot, build_slots, make_advice

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
    assert lines == ["Thời tiết ổn định, không cần áo mưa."]


def test_no_data():
    assert make_advice([Slot(key="m", label="Sáng", hours="")]) == ["Chưa có dữ liệu thời tiết."]


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
    }
    render(ctx, out_path=out)
    html = out.read_text(encoding="utf-8")
    assert "&lt;b&gt;HCM&lt;/b&gt;" in html
    assert not (tmp_path / "docs" / "index.html.tmp").exists()
