"""Open-Meteo weather for 3 day slots + practical advice."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import requests

from .config import Location

log = logging.getLogger(__name__)

API_URL = "https://api.open-meteo.com/v1/forecast"

# (key, nhãn, giờ bắt đầu, giờ kết thúc) - bao gồm cả 2 đầu
SLOTS = [
    ("morning", "Sáng", 7, 9),
    ("noon", "Trưa", 11, 14),
    ("evening", "Chiều tối", 17, 20),
]

WMO_VI = {
    0: "Trời quang",
    1: "Ít mây",
    2: "Có mây",
    3: "Nhiều mây, u ám",
    45: "Sương mù",
    48: "Sương mù đóng băng",
    51: "Mưa phùn nhẹ",
    53: "Mưa phùn",
    55: "Mưa phùn dày",
    56: "Mưa phùn lạnh",
    57: "Mưa phùn lạnh dày",
    61: "Mưa nhỏ",
    63: "Mưa vừa",
    65: "Mưa to",
    66: "Mưa lạnh",
    67: "Mưa lạnh to",
    71: "Tuyết nhẹ",
    73: "Tuyết",
    75: "Tuyết dày",
    77: "Tuyết hạt",
    80: "Mưa rào nhẹ",
    81: "Mưa rào",
    82: "Mưa rào rất to",
    85: "Mưa tuyết",
    86: "Mưa tuyết to",
    95: "Dông",
    96: "Dông kèm mưa đá",
    99: "Dông mạnh kèm mưa đá",
}
THUNDER_CODES = {95, 96, 99}
HEAVY_RAIN_CODES = {65, 67, 82}


def describe_code(code: int | None) -> str:
    if code is None:
        return "Chưa có dữ liệu"
    return WMO_VI.get(int(code), f"Mã thời tiết {code}")


@dataclass
class Slot:
    key: str
    label: str
    hours: str
    temp_min: float | None = None
    temp_max: float | None = None
    code: int | None = None
    condition: str = "Chưa có dữ liệu"
    rain_prob: int | None = None
    rain_mm: float | None = None
    uv_max: float | None = None
    gust_max: float | None = None

    @property
    def has_data(self) -> bool:
        return self.temp_min is not None


@dataclass
class WeatherReport:
    location: str
    slots: list[Slot] = field(default_factory=list)
    advice: list[str] = field(default_factory=list)
    ok: bool = False


def _severity(code: int) -> int:
    """Higher = worse weather; used to pick representative code for a slot."""
    if code in THUNDER_CODES:
        return 100 + code
    return code


def build_slots(hourly: dict) -> list[Slot]:
    times = hourly.get("time", [])
    out: list[Slot] = []
    for key, label, start, end in SLOTS:
        idx = [i for i, t in enumerate(times) if start <= int(t[11:13]) <= end]
        slot = Slot(key=key, label=label, hours=f"{start:02d}:00–{end:02d}:00")

        def vals(name: str):
            arr = hourly.get(name) or []
            return [arr[i] for i in idx if i < len(arr) and arr[i] is not None]

        temps = vals("temperature_2m")
        if temps:
            slot.temp_min, slot.temp_max = round(min(temps)), round(max(temps))
        codes = vals("weather_code")
        if codes:
            slot.code = int(max(codes, key=_severity))
            slot.condition = describe_code(slot.code)
        probs = vals("precipitation_probability")
        if probs:
            slot.rain_prob = int(max(probs))
        rain = vals("precipitation")
        if rain:
            slot.rain_mm = round(sum(rain), 1)
        uv = vals("uv_index")
        if uv:
            slot.uv_max = round(max(uv), 1)
        gust = vals("wind_gusts_10m")
        if gust:
            slot.gust_max = round(max(gust))
        out.append(slot)
    return out


def make_advice(slots: list[Slot]) -> list[str]:
    """1–2 dòng kết luận: áo mưa, chống nắng, cảnh báo giông lốc/ngập."""
    data = [s for s in slots if s.has_data]
    if not data:
        return ["Chưa có dữ liệu thời tiết"]

    thunder = [s.label for s in data if s.code in THUNDER_CODES]
    rainy = [
        s.label
        for s in data
        if (s.rain_prob or 0) >= 50 or (s.rain_mm or 0) >= 1.0
    ]
    total_rain = sum(s.rain_mm or 0 for s in data)
    flood = any((s.rain_mm or 0) >= 20 for s in data) or total_rain >= 30 or any(
        s.code in HEAVY_RAIN_CODES and (s.rain_mm or 0) >= 10 for s in data
    )
    strong_gust = any((s.gust_max or 0) >= 50 for s in data)
    uv_max = max((s.uv_max or 0) for s in data)

    lines: list[str] = []
    gear: list[str] = []
    if rainy or thunder:
        when = ", ".join(dict.fromkeys(thunder + rainy)).lower()
        gear.append(f"mang áo mưa (khả năng mưa buổi {when})")
    if uv_max >= 6:
        gear.append(f"mặc áo khoác chống nắng (UV tới {uv_max:g})".replace(".", ","))
    if gear:
        lines.append("Nên " + "; ".join(gear))
    else:
        lines.append("Thời tiết ổn định, không cần áo mưa")

    warnings: list[str] = []
    if thunder or strong_gust:
        when = ", ".join(thunder).lower() if thunder else "trong ngày"
        warnings.append(f"⚠️ Cảnh báo giông lốc ({when}) – tránh trú dưới cây lớn, biển quảng cáo")
    if flood:
        warnings.append("nguy cơ ngập cục bộ, hạn chế đi qua đường trũng")
    if warnings:
        line = "; ".join(warnings)
        if not line.startswith("⚠️"):
            line = "⚠️ Cảnh báo " + line
        lines.append(line)
    return lines[:2]


def fetch_weather(loc: Location, timeout: int = 20) -> WeatherReport:
    params = {
        "latitude": loc.lat,
        "longitude": loc.lon,
        "hourly": "temperature_2m,precipitation_probability,precipitation,weather_code,uv_index,wind_gusts_10m",
        "timezone": "Asia/Ho_Chi_Minh",
        "forecast_days": 1,
    }
    report = WeatherReport(location=loc.name)
    for attempt in range(3):
        try:
            r = requests.get(API_URL, params=params, timeout=timeout)
            r.raise_for_status()
            report.slots = build_slots(r.json().get("hourly", {}))
            report.advice = make_advice(report.slots)
            report.ok = any(s.has_data for s in report.slots)
            return report
        except Exception as e:  # noqa: BLE001
            log.warning("Open-Meteo lỗi (lần %d): %s", attempt + 1, type(e).__name__)
    report.slots = [Slot(key=k, label=l, hours=f"{a:02d}:00–{b:02d}:00") for k, l, a, b in SLOTS]
    report.advice = ["Chưa có dữ liệu thời tiết"]
    return report


def weather_severity(slots: list[Slot]) -> str:
    """'alert' (giông/ngập/gió giật mạnh) | 'warn' (mưa hoặc UV cao) | 'ok'."""
    data = [s for s in slots if s.has_data]
    if not data:
        return "ok"
    total_rain = sum(s.rain_mm or 0 for s in data)
    if (any(s.code in THUNDER_CODES for s in data) or any((s.gust_max or 0) >= 50 for s in data)
            or any((s.rain_mm or 0) >= 20 for s in data) or total_rain >= 30):
        return "alert"
    if any((s.rain_prob or 0) >= 50 or (s.rain_mm or 0) >= 1.0 for s in data) or max(s.uv_max or 0 for s in data) >= 6:
        return "warn"
    return "ok"
