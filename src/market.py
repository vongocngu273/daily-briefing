"""Latest closing prices via yfinance. Never invents numbers."""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass

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
        if self.close >= 1000:
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


def fetch_market(cfg: dict) -> list[Quote]:
    tickers = cfg.get("market", {}).get("tickers", [])
    quotes = [fetch_quote(t["symbol"], t["name"]) for t in tickers]
    log.info("Thị trường: %d/%d mã có dữ liệu", sum(q.ok for q in quotes), len(quotes))
    return quotes
