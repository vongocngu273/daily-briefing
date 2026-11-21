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
    assert msg.startswith("<b>☀️ BẢN TIN SÁNG</b>\nThứ Bảy, 21/11/2026 · 07:12")
    assert "🚨 Cảnh báo" in msg
    assert "📍 Q.1 &lt;HCM&gt;" in msg and "• Nên mang áo mưa &amp; áo khoác." in msg
    assert "🌄 Sáng  <b>26–29°</b>  ·  mưa 10%" in msg and "🌆 Chiều  <b>28–30°</b>  ·  mưa 80%" in msg
    assert "1. Fed &lt;giữ&gt; lãi suất" in msg and "3. Bão số 9 &gt; cấp 12" in msg
    assert '👉 <a href="https://user.github.io/daily-briefing/?v=20261121">Đọc bản tin đầy đủ · 38 tin</a>' in msg
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
    assert "🌅 Mặt trời  05:51 – 17:26" in msg and "😷 AQI <b>114</b> · Kém với người nhạy cảm" in msg
    assert "💡 Nhắc nhở" in msg


# ---------- thumbnails ----------
def test_entry_image_sources_and_filters():
    from src.news import entry_image
    assert entry_image({"media_thumbnail": [{"url": "https://ichef.bbci.co.uk/ace/standard/240/cpsprodpb/a.jpg"}]}) \
        == "https://ichef.bbci.co.uk/ace/standard/480/cpsprodpb/a.jpg"
    assert entry_image({"links": [{"rel": "enclosure", "type": "image/jpeg", "href": "https://i.vnecdn.net/x.jpg"}]}) \
        == "https://i.vnecdn.net/x.jpg"
    assert entry_image({"summary": '<p><img src="http://insecure/x.jpg"><img src="https://cdn.x/y.png?w=1&amp;h=2"></p>'}) \
        == "https://cdn.x/y.png?w=1&h=2"
    assert entry_image({"summary": '<img src="https://feeds.feedburner.com/~r/x/1x1.gif">'}) == ""
    assert entry_image({}) == ""


def test_parse_feed_keeps_image_but_not_for_google_news():
    from src.news import parse_feed
    rss = b"""<?xml version="1.0"?><rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel>
    <item><title>Tin A</title><link>https://vnexpress.net/a.html</link><pubDate>Sat, 21 Nov 2026 01:00:00 +0700</pubDate>
    <enclosure url="https://i1-vnexpress.vnecdn.net/a.jpg" type="image/jpeg" length="1"/></item></channel></rss>"""
    arts = parse_feed(rss, {"source": "VnExpress", "url": "https://vnexpress.net/rss/x.rss"})
    assert arts[0].image == "https://i1-vnexpress.vnecdn.net/a.jpg"
    arts = parse_feed(rss, {"source": "Reuters", "url": "https://news.google.com/rss/search?q=x"})
    assert arts[0].image == ""


# ---------- snapshot / rerender ----------
def test_snapshot_roundtrip_renders_same_page(tmp_path):
    from src.curator import NewsItem
    from src.extras import AirReport, TideReport
    from src.market import Quote
    from src.renderer import render
    from src.rerender import load_snapshot, save_snapshot
    from src.weather import Slot, WeatherReport

    item = NewsItem(cid=1, category="geopolitics", severity="high", title="Tin <A>", summary="Tóm tắt",
                    developments="", context="", why_it_matters="", is_update=False, url="https://x.vn/a",
                    source="VnExpress", published="2026-11-21T00:00:00+00:00", num=1, image="https://x.vn/a.jpg")
    ctx = {
        "updated_at": "07:10", "date_str": "Thứ Bảy, 21/11/2026",
        "weather": WeatherReport(location="HCM", slots=[Slot(key="m", label="Sáng", hours="07:00–09:00",
                                 temp_min=26, temp_max=29)], advice=["ok"], ok=True, sunrise="05:51"),
        "air": AirReport(ok=True, aqi_max=80, label="Trung bình"), "uv_label": "Cao",
        "tide": TideReport(place="Cần Giờ", ok=True, extremes=[{"kind": "Cao", "time": "22:26", "height": 2.1}]),
        "quotes": [Quote(symbol="^DJI", name="Dow Jones", close=48147.0, change_pct=-1.9)],
        "sjc_url": "https://sjc.com.vn", "takeaways": ["a", "b", "c"], "total_items": 1, "ai_degraded": False,
        "layers": [{"id": 1, "title": "Lớp 1", "categories": [{"key": "geopolitics", "label": "Địa chính trị",
                    "items": [item], "first": 1, "last": 1}]}],
        "weekday": 5, "weekday_name": "Thứ Bảy", "weekday_short": "T7", "serial": "21·11",
        "year": "2026", "date_compact": "20261121", "site_url": "https://x.github.io/daily-briefing/",
    }
    a, b, snap = tmp_path / "a.html", tmp_path / "b.html", tmp_path / "page.json"
    render(ctx, out_path=a)
    save_snapshot(ctx, snap)
    render(load_snapshot(snap, trends_path=tmp_path / "none.json"), out_path=b)
    assert a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8")


# ---------- Google Trends ticker ----------
_TRENDS_RSS = """<?xml version="1.0"?><rss xmlns:ht="https://trends.google.com/trending/rss"><channel>
<item><title>erling haaland</title><ht:approx_traffic>1000+</ht:approx_traffic><pubDate>Sat, 21 Nov 2026 06:40:00 -0800</pubDate>
<ht:news_item><ht:news_item_title>Haaland &amp; City</ht:news_item_title><ht:news_item_url>https://x.com/a</ht:news_item_url></ht:news_item></item>
<item><title>lazio</title><ht:approx_traffic>20K+</ht:approx_traffic><pubDate>Sat, 21 Nov 2026 06:50:00 -0800</pubDate></item>
</channel></rss>"""


def test_trends_parse_and_traffic():
    from src.trends import parse_rss, parse_traffic
    assert parse_traffic("2000+") == 2000 and parse_traffic("20K+") == 20000 and parse_traffic("1M+") == 1_000_000
    items = parse_rss(_TRENDS_RSS, "VN")
    assert [i["term"] for i in items] == ["erling haaland", "lazio"]
    assert items[0]["url"] == "https://x.com/a" and items[0]["news"] == "Haaland & City"


def test_trends_merge_keeps_24h_dedups_and_ranks():
    from datetime import datetime, timezone
    from src.trends import for_page, merge, parse_rss
    now = datetime(2026, 11, 21, 15, 0, tzinfo=timezone.utc)
    old = {"term": "Cũ", "geo": "VN", "traffic": "50K+", "score": 50000, "ts": "2026-11-20T10:00:00+00:00", "url": "", "news": ""}
    dup = {"term": "LAZIO", "geo": "VN", "traffic": "200+", "score": 200, "ts": "2026-11-21T12:00:00+00:00", "url": "", "news": ""}
    store = {"vn": [old, dup]}
    merge(store, "vn", parse_rss(_TRENDS_RSS, "VN"), now)
    assert [i["term"] for i in store["vn"]] == ["lazio", "erling haaland"]   # bỏ mục >24h, giữ lượt cao hơn
    page = for_page({**store, "updated": now.isoformat()})
    assert page["vn"][0]["term"] == "Lazio" and page["vn"][0]["url"].startswith("https://www.google.com/search?q=lazio")
    assert page["updated"] == "22:00"


def test_even_count_per_category():
    from src.curator import even_count
    assert even_count([1, 2, 3, 4, 5]) == [1, 2, 3, 4]
    assert even_count([1, 2, 3]) == [1, 2]
    assert even_count([1, 2]) == [1, 2]
    assert even_count([1]) == [1] and even_count([]) == []


# ---------- VN-Index ----------
def test_vnindex_parsers():
    from src.market import Quote, parse_ssi_index, parse_vps_history
    q = parse_ssi_index({"data": {"indexValue": 1688.79, "prevIndexValue": 1689.62, "changePercent": -0.05,
                                  "time": 1795161905097}}, Quote(symbol="^VNINDEX", name="VN-Index"))
    assert q.ok and q.close == 1688.79 and round(q.change_pct, 2) == -0.05 and q.date == "20/11"
    assert q.close_str == "1.688,79"
    assert not parse_ssi_index({"data": {}}, Quote(symbol="x", name="x")).ok
    v = parse_vps_history({"s": "ok", "t": [1795046400, 1795132800], "c": [1689.62, 1688.79]},
                          Quote(symbol="^VNINDEX", name="VN-Index"))
    assert v.close == 1688.79 and round(v.change_pct, 2) == -0.05 and v.date == "20/11"
    assert not parse_vps_history({"s": "no_data"}, Quote(symbol="x", name="x")).ok


def test_share_image_and_og_tags(tmp_path):
    from PIL import Image
    from src.ogimage import make_og
    from src.weather import Slot, WeatherReport
    ctx = {"weekday": 5, "serial": "21·11", "weekday_name": "Thứ Bảy", "year": "2026", "total_items": 38,
           "updated_at": "07:10", "takeaways": ["Một câu rất dài " * 8, "Hai", "Ba"],
           "weather": WeatherReport(location="x", slots=[Slot(key="m", label="Sáng", hours="", temp_min=26, temp_max=32)],
                                    uv_day=7.5)}
    out = make_og(ctx, tmp_path / "og.png")
    assert Image.open(out).size == (1200, 630)
