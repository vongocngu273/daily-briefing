"""Configuration loading. Values come from config.json, overridable via env."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
HISTORY_PATH = ROOT / "data" / "history.json"
SUMMARY_PATH = ROOT / "data" / "latest_summary.json"
TEMPLATES_DIR = ROOT / "templates"
OUTPUT_PATH = ROOT / "docs" / "index.html"

# Fallback: trung tâm TP.HCM (không phải địa chỉ riêng)
DEFAULT_LAT = 10.7769
DEFAULT_LON = 106.7009
DEFAULT_LOCATION = "Trung tâm TP.HCM"

# Cấu trúc 3 lớp tin: layer -> [(key, nhãn)]
LAYERS: dict[int, list[tuple[str, str]]] = {
    1: [
        ("geopolitics", "Địa chính trị quốc tế"),
        ("economy", "Kinh tế – Tài chính toàn cầu"),
        ("domestic", "Thời sự trong nước"),
    ],
    2: [
        ("tech_ai", "Công nghệ – AI"),
        ("mobile", "Điện thoại – Mobile"),
        ("science_health", "Khoa học – Y tế"),
        ("environment", "Môi trường – Khí hậu"),
    ],
    3: [
        ("cyber_digital", "An ninh mạng – Dữ liệu cá nhân & Chuyển đổi số"),
        ("sports", "Thể thao"),
        ("culture_society", "Văn hóa – Xã hội"),
    ],
}
# Gợi ý phạm vi cho AI khi chia chuyên mục (không hiển thị trên trang)
CATEGORY_HINTS: dict[str, str] = {
    "tech_ai": "AI, phần mềm, bán dẫn, Big Tech, internet; tin điện thoại đưa sang mobile",
    "mobile": ("điện thoại & máy tính bảng, đồng hồ/tai nghe đi kèm: Apple/iPhone/iOS, Android, Samsung, "
               "Google Pixel, Xiaomi, OPPO, vivo…; ra mắt máy, cập nhật hệ điều hành, chip di động, rò rỉ đáng tin. "
               "Bỏ tin khuyến mãi/giảm giá/Black Friday và bài hướng dẫn mua hàng"),
}

LAYER_TITLES = {
    1: "Lớp 1 · Trọng tâm",
    2: "Lớp 2 · Tri thức & Tương lai",
    3: "Lớp 3 · Đời sống số & Xã hội",
}


@dataclass(frozen=True)
class Location:
    lat: float
    lon: float
    name: str


def load_config(path: Path = CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def tz(cfg: dict) -> ZoneInfo:
    return ZoneInfo(cfg.get("timezone", "Asia/Ho_Chi_Minh"))


def _float_env(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        log.warning("Biến %s không hợp lệ, dùng giá trị mặc định", name)
        return None


def weather_location(cfg: dict) -> Location:
    """Env WEATHER_* overrides config.json; config.json overrides hard fallback.

    Never logs coordinates (privacy)."""
    wcfg = cfg.get("weather", {})
    lat = _float_env("WEATHER_LAT")
    lon = _float_env("WEATHER_LON")
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        lat = float(wcfg.get("lat", DEFAULT_LAT))
        lon = float(wcfg.get("lon", DEFAULT_LON))
        source = "config.json"
    else:
        source = "env"
    name = os.environ.get("WEATHER_LOCATION_NAME", "").strip() or wcfg.get(
        "location_name", DEFAULT_LOCATION
    )
    log.info("Tọa độ thời tiết lấy từ %s", source)
    return Location(lat=lat, lon=lon, name=name)
