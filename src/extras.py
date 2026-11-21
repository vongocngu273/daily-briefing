"""Chỉ số phụ cho ô thời tiết: chất lượng không khí (AQI) và thủy triều.

Cả hai lấy từ Open-Meteo (không cần API key). Lỗi mạng không làm hỏng bản tin:
hàm trả về báo cáo rỗng (ok=False) và trang hiện "Chưa có dữ liệu".
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import requests

from .config import Location

log = logging.getLogger(__name__)

AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
LOCAL_TZ = "Asia/Ho_Chi_Minh"

# Thang US AQI (EPA) -> nhãn tiếng Việt, mức cảnh báo
AQI_LEVELS = [
    (50, "Tốt", "ok"),
    (100, "Trung bình", "ok"),
    (150, "Kém với người nhạy cảm", "warn"),
    (200, "Kém", "alert"),
    (300, "Rất kém", "alert"),
    (10_000, "Nguy hại", "alert"),
]


def aqi_level(aqi: float | None) -> tuple[str, str]:
    if aqi is None:
        return "Chưa có dữ liệu", "ok"
    for upper, label, tone in AQI_LEVELS:
        if aqi <= upper:
            return label, tone
    return AQI_LEVELS[-1][1], AQI_LEVELS[-1][2]


def uv_level(uv: float | None) -> str:
    """Thang UV của WHO."""
    if uv is None:
        return "Chưa có dữ liệu"
    if uv < 3:
        return "Thấp"
    if uv < 6:
        return "Trung bình"
    if uv < 8:
        return "Cao"
    if uv < 11:
        return "Rất cao"
    return "Cực độ"


@dataclass
class AirReport:
    ok: bool = False
    aqi_now: int | None = None
    aqi_max: int | None = None
    pm25: float | None = None
    label: str = "Chưa có dữ liệu"
    tone: str = "ok"


@dataclass
class TideReport:
    place: str
    ok: bool = False
    # [{"kind": "Cao"|"Thấp", "time": "HH:MM", "height": 1.9}]
    extremes: list[dict] = field(default_factory=list)


def _get(url: str, params: dict, timeout: int, attempts: int = 3) -> dict:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            last = e
            log.warning("%s lỗi (lần %d): %s", url.split("/")[2], attempt + 1, type(e).__name__)
            if attempt < attempts - 1:
                time.sleep(5 * (attempt + 1))
    raise last  # type: ignore[misc]


def parse_air(payload: dict) -> AirReport:
    cur = payload.get("current") or {}
    hourly = payload.get("hourly") or {}
    values = [v for v in (hourly.get("us_aqi") or []) if v is not None]
    now = cur.get("us_aqi")
    if now is None and not values:
        return AirReport()
    rep = AirReport(ok=True)
    rep.aqi_now = round(now) if now is not None else None
    rep.aqi_max = round(max(values)) if values else rep.aqi_now
    pm = cur.get("pm2_5")
    rep.pm25 = round(pm, 1) if pm is not None else None
    rep.label, rep.tone = aqi_level(rep.aqi_max)
    return rep


def fetch_air(loc: Location, timeout: int = 30) -> AirReport:
    try:
        data = _get(AIR_URL, {"latitude": loc.lat, "longitude": loc.lon, "current": "us_aqi,pm2_5",
                              "hourly": "us_aqi", "timezone": LOCAL_TZ, "forecast_days": 1}, timeout)
        return parse_air(data)
    except Exception:  # noqa: BLE001
        return AirReport()


def tide_extremes(times: list[str], heights: list[float | None], day: str) -> list[dict]:
    """Đỉnh/chân triều trong ngày `day` (YYYY-MM-DD) từ chuỗi mực nước theo giờ.

    Nội suy parabol qua 3 điểm quanh cực trị để ước giờ chính xác hơn mức 1 giờ."""
    pts = [(t, h) for t, h in zip(times, heights) if h is not None]
    out: list[dict] = []
    for i in range(1, len(pts) - 1):
        (t0, a), (t1, b), (_, c) = pts[i - 1], pts[i], pts[i + 1]
        if not ((b > a and b >= c) or (b < a and b <= c)):
            continue
        denom = a - 2 * b + c
        shift = 0.5 * (a - c) / denom if denom else 0.0
        shift = max(-0.5, min(0.5, shift))
        peak = b - 0.25 * (a - c) * shift
        hour, minute = int(t1[11:13]), int(t1[14:16])
        total = round((hour * 60 + minute) + shift * 60)
        if t1[:10] != day or not 0 <= total < 24 * 60:
            continue
        out.append({"kind": "Cao" if b > a else "Thấp", "time": f"{total // 60:02d}:{total % 60:02d}",
                    "height": round(peak, 1)})
    return out


def fetch_tide(lat: float, lon: float, place: str, day: str, timeout: int = 30) -> TideReport:
    rep = TideReport(place=place)
    try:
        data = _get(MARINE_URL, {"latitude": lat, "longitude": lon, "hourly": "sea_level_height_msl",
                                 "timezone": LOCAL_TZ, "forecast_days": 2}, timeout)
        h = data.get("hourly") or {}
        rep.extremes = tide_extremes(h.get("time") or [], h.get("sea_level_height_msl") or [], day)
        rep.ok = bool(rep.extremes)
    except Exception:  # noqa: BLE001
        pass
    return rep


def air_advice(air: AirReport) -> str | None:
    if not air.ok or air.aqi_max is None:
        return None
    if air.aqi_max > 150:
        return f"Không khí {air.label.lower()} (AQI {air.aqi_max}), nên đeo khẩu trang khi ra đường"
    if air.aqi_max > 100:
        return f"Không khí kém với người nhạy cảm (AQI {air.aqi_max}), nên đeo khẩu trang nếu đi xa"
    return None
