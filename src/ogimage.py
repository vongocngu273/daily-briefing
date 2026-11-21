"""Ảnh xem trước khi chia sẻ link (Open Graph, 1200×630) theo phong cách cuống vé của trang.

Tạo lại mỗi lần render (bản tin sáng, cập nhật trend), không gọi dịch vụ ngoài.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path

from .config import ROOT

log = logging.getLogger(__name__)

OG_PATH = ROOT / "docs" / "og.png"
FONTS = ROOT / "assets" / "fonts"
W, H = 1200, 630

# Cùng bảng màu cuống vé theo thứ (light mode) với templates/index.html.j2
STUB = ["#5bbbe9", "#a6d64a", "#f7a440", "#a98ddc", "#3ccdbf", "#f06e98", "#f6cf3a"]
INK, RED, WHITE = "#1b1f4a", "#d0021b", "#ffffff"


def _font(name: str, size: int):
    from PIL import ImageFont

    return ImageFont.truetype(str(FONTS / name), size)


def _wrap(draw, text: str, font, width: int, max_lines: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= width:
            cur = trial
            continue
        if cur:
            lines.append(cur)
        cur = w
        if len(lines) == max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    used = " ".join(lines).split()
    if len(used) < len(words) and lines:  # cắt bớt thì thêm dấu …
        last = lines[-1]
        while last and draw.textlength(last + "…", font=font) > width:
            last = last.rsplit(" ", 1)[0] if " " in last else last[:-1]
        lines[-1] = last.rstrip(",.;:") + "…"
    return lines


def _get(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def make_og(ctx: dict, out: Path = OG_PATH) -> Path | None:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        log.warning("Thiếu Pillow – bỏ qua ảnh xem trước")
        return None

    day = int(ctx.get("weekday", 0)) % 7
    img = Image.new("RGB", (W, H), STUB[day])
    d = ImageDraw.Draw(img, "RGBA")

    # hoa văn guilloche nhẹ
    for k in range(9):
        pts = [(x, 30 + k * 70 + 22 * math.sin(x / 38 + k)) for x in range(0, W + 1, 6)]
        d.line(pts, fill=(255, 255, 255, 70), width=2)
        pts = [(x, 30 + k * 70 + 22 * math.sin(x / 38 + k + math.pi)) for x in range(0, W + 1, 6)]
        d.line(pts, fill=(255, 255, 255, 50), width=2)

    cond, cond6 = _font("BarlowCondensed-ExtraBold.ttf", 54), _font("BarlowCondensed-SemiBold.ttf", 30)
    d.text((60, 40), "BẢN TIN SÁNG", font=cond, fill=INK)
    upd = f"CẬP NHẬT {ctx.get('updated_at', '')}"
    d.text((W - 60 - d.textlength(upd, font=cond6), 56), upd, font=cond6, fill=INK)

    # ô ngày
    box = (60, 130, 560, 470)
    d.rounded_rectangle(box, radius=34, fill=WHITE, outline=INK, width=5)
    serial = ctx.get("serial", "")
    big = _font("BarlowCondensed-ExtraBold.ttf", 230)
    sw = d.textlength(serial, font=big)
    d.text(((box[0] + box[2] - sw) / 2, 128), serial, font=big, fill=RED)
    wd = _font("BarlowCondensed-ExtraBold.ttf", 58)
    name = str(ctx.get("weekday_name", "")).upper()
    d.text(((box[0] + box[2] - d.textlength(name, font=wd)) / 2, 368), name, font=wd, fill=INK)
    sub = f"{ctx.get('year', '')} · {ctx.get('total_items', 0)} TIN"
    d.text(((box[0] + box[2] - d.textlength(sub, font=cond6)) / 2, 428), sub, font=cond6, fill=INK)

    # ô "Cần nhớ"
    box2 = (600, 130, W - 60, 470)
    d.rounded_rectangle(box2, radius=34, fill=WHITE, outline=INK, width=5)
    d.text((box2[0] + 30, box2[1] + 22), "CẦN NHỚ HÔM NAY", font=_font("BarlowCondensed-ExtraBold.ttf", 34), fill=RED)
    body = _font("BeVietnamPro-SemiBold.ttf", 27)
    y = box2[1] + 70
    for i, t in enumerate([t for t in (ctx.get("takeaways") or []) if t][:3], 1):
        lines = _wrap(d, t, body, box2[2] - box2[0] - 90, 2)
        d.text((box2[0] + 30, y), str(i), font=_font("BarlowCondensed-ExtraBold.ttf", 36), fill=RED)
        for ln in lines:
            if y > box2[3] - 44:
                break
            d.text((box2[0] + 62, y + 2), ln, font=body, fill=INK)
            y += 34
        y += 6

    # dòng thời tiết / không khí
    w = ctx.get("weather")
    slots = [s for s in (_get(w, "slots") or []) if _get(s, "temp_min") is not None]
    bits = []
    if slots:
        bits.append(f"{min(_get(s, 'temp_min') for s in slots)}–{max(_get(s, 'temp_max') for s in slots)}°C")
    uv = _get(w, "uv_day")
    if uv is not None:
        bits.append(f"UV {str(uv).replace('.', ',')}")
    air = ctx.get("air")
    if _get(air, "ok") and _get(air, "aqi_max") is not None:
        bits.append(f"AQI {_get(air, 'aqi_max')}")
    if bits:
        d.text((60, 500), "  ·  ".join(bits), font=_font("BarlowCondensed-ExtraBold.ttf", 44), fill=INK)

    # răng cưa cuống vé
    for x in range(0, W + 40, 40):
        d.ellipse((x - 14, H - 14, x + 14, H + 14), fill=WHITE)

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.png")
    img.save(tmp, "PNG", optimize=True)
    tmp.replace(out)
    return out
