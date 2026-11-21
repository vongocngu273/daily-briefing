"""Latest closing prices: yfinance for world markets, SSI/VPS for VN-Index. Never invents numbers."""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

log = logging.getLogger(__name__)

NO_DATA = "Chưa có dữ liệu"


@dataclass
class Quote:
    symbol: str
    name: str
    close: float | None = None
    change_pct: float | None = None
    date: str | None = None

    @property
    def ok(self) -> bool:
        return self.close is not None

    @property
    def close_str(self) -> str:
        if self.close is None:
            return NO_DATA
        if self.close >= 1000 and self.symbol != "^VNINDEX":  # chỉ số VN giữ 2 số lẻ như bảng điện
            return f"{self.close:,.0f}".replace(",", ".")
        return f"{self.close:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    @property
    def change_str(self) -> str:
        if self.change_pct is None:
            return ""
        sign = "+" if self.change_pct > 0 else ("−" if self.change_pct < 0 else "±")
        return f"{sign}{abs(self.change_pct):.2f}%".replace(".", ",")

    @property
    def direction(self) -> str:
        if self.change_pct is None or self.change_pct == 0:
            return "flat"
        return "up" if self.change_pct > 0 else "down"


def _valid(x) -> bool:
    try:
        return x is not None and not math.isnan(float(x)) and float(x) > 0
    except (TypeError, ValueError):
        return False


def fetch_quote(symbol: str, name: str) -> Quote:
    q = Quote(symbol=symbol, name=name)
    try:
        import yfinance as yf

        hist = yf.Ticker(symbol).history(period="10d", interval="1d", auto_adjust=False)
        if hist is None or hist.empty or "Close" not in hist:
            return q
        closes = [(idx, float(c)) for idx, c in hist["Close"].items() if _valid(c)]
        if not closes:
            return q
        last_idx, last = closes[-1]
        q.close = last
        q.date = last_idx.strftime("%d/%m")
        if len(closes) >= 2:
            prev = closes[-2][1]
            q.change_pct = (last - prev) / prev * 100
    except Exception as e:  # noqa: BLE001
        log.warning("yfinance %s lỗi: %s", symbol, type(e).__name__)
    return q


# VN-Index không có trên Yahoo Finance: lấy từ bảng giá SSI iBoard (dữ liệu sở HOSE),
# dự phòng bằng chuỗi giá ngày của VPS. Cả hai là API công khai, không cần key.
VN_INDEX_SYMBOLS = {"^VNINDEX", "VNINDEX"}
SSI_URL = "https://iboard-query.ssi.com.vn/exchange-index/VNINDEX?hasHistory=false"
VPS_URL = "https://histdatafeed.vps.com.vn/tradingview/history"
_VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
_UA = {"User-Agent": "Mozilla/5.0 (compatible; daily-briefing/1.0)"}


def parse_ssi_index(payload: dict, q: Quote) -> Quote:
    d = (payload or {}).get("data") or {}
    val, prev = d.get("indexValue"), d.get("prevIndexValue")
    if not _valid(val):
        return q
    q.close = float(val)
    if _valid(prev) and prev:  # tính từ điểm tham chiếu cho chính xác hơn số % đã làm tròn
        q.change_pct = (float(val) - float(prev)) / float(prev) * 100
    elif isinstance(d.get("changePercent"), (int, float)):
        q.change_pct = float(d["changePercent"])
    if d.get("time"):
        q.date = datetime.fromtimestamp(d["time"] / 1000, tz=timezone.utc).astimezone(_VN_TZ).strftime("%d/%m")
    return q


def parse_vps_history(payload: dict, q: Quote) -> Quote:
    t, c = (payload or {}).get("t") or [], (payload or {}).get("c") or []
    pts = [(ts, float(v)) for ts, v in zip(t, c) if _valid(v)]
    if (payload or {}).get("s") != "ok" or not pts:
        return q
    q.close = pts[-1][1]
    q.date = datetime.fromtimestamp(pts[-1][0], tz=timezone.utc).astimezone(_VN_TZ).strftime("%d/%m")
    if len(pts) >= 2 and pts[-2][1]:
        q.change_pct = (pts[-1][1] - pts[-2][1]) / pts[-2][1] * 100
    return q


def fetch_vnindex(name: str, timeout: int = 15) -> Quote:
    q = Quote(symbol="^VNINDEX", name=name)
    try:
        r = requests.get(SSI_URL, headers=_UA, timeout=timeout)
        r.raise_for_status()
        if parse_ssi_index(r.json(), q).ok:
            return q
    except Exception as e:  # noqa: BLE001
        log.warning("SSI VN-Index lỗi: %s", type(e).__name__)
    try:
        now = int(time.time())
        r = requests.get(VPS_URL, params={"symbol": "VNINDEX", "resolution": "D", "from": now - 14 * 86400, "to": now},
                         headers=_UA, timeout=timeout)
        r.raise_for_status()
        parse_vps_history(r.json(), q)
    except Exception as e:  # noqa: BLE001
        log.warning("VPS VN-Index lỗi: %s", type(e).__name__)
    return q


def fetch_market(cfg: dict) -> list[Quote]:
    tickers = cfg.get("market", {}).get("tickers", [])
    quotes = [fetch_vnindex(t["name"]) if t["symbol"] in VN_INDEX_SYMBOLS else fetch_quote(t["symbol"], t["name"])
              for t in tickers]
    log.info("Thị trường: %d/%d mã có dữ liệu", sum(q.ok for q in quotes), len(quotes))
    return quotes
