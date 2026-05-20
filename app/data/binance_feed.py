"""
BTC Reflex Engine — Binance Candle Feed
Fetches OHLCV candles via Binance public REST API.
No API key required for market data.
Returns clean list of dicts consumed by all engines.
"""
from __future__ import annotations
import logging
import time
from typing import Optional
import requests
from app.config import settings

logger = logging.getLogger(__name__)

# Binance klines column order
_KLINE_KEYS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "num_trades",
    "taker_buy_base_vol", "taker_buy_quote_vol", "ignore",
]


def fetch_candles(
    symbol: str | None = None,
    interval: str = "4h",
    limit: int = 100,
    retries: int = 3,
    retry_delay: float = 2.0,
) -> list[dict]:
    """
    Fetch OHLCV candles from Binance.

    Args:
        symbol:   Trading pair, e.g. "BTCUSDT". Defaults to settings.symbol.
        interval: Binance interval string: "1h", "4h", "1d", etc.
        limit:    Number of candles (max 1000).
        retries:  Retry attempts on network failure.

    Returns:
        List of candle dicts with float-typed OHLCV fields and timestamps.
        Returns [] on failure (engines must handle empty input gracefully).
    """
    sym = symbol or settings.symbol
    url = f"{settings.binance_base_url}/api/v3/klines"
    params = {"symbol": sym, "interval": interval, "limit": limit}

    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            raw = r.json()
            candles = _parse_klines(raw)
            logger.info(
                "[binance_feed] %s %s: fetched %d candles",
                sym, interval, len(candles)
            )
            return candles
        except requests.RequestException as exc:
            logger.warning(
                "[binance_feed] attempt %d/%d failed: %s",
                attempt + 1, retries, exc
            )
            if attempt < retries - 1:
                time.sleep(retry_delay)

    logger.error("[binance_feed] all retries exhausted for %s %s", sym, interval)
    return []


def fetch_current_price(symbol: str | None = None) -> Optional[float]:
    """Fetch the latest traded price for a symbol."""
    sym = symbol or settings.symbol
    url = f"{settings.binance_base_url}/api/v3/ticker/price"
    try:
        r = requests.get(url, params={"symbol": sym}, timeout=5)
        r.raise_for_status()
        return float(r.json()["price"])
    except Exception as exc:
        logger.warning("[binance_feed] price fetch failed: %s", exc)
        return None


def _parse_klines(raw: list) -> list[dict]:
    """Parse raw Binance kline arrays into clean dicts with float values."""
    candles = []
    for row in raw:
        c = dict(zip(_KLINE_KEYS, row))
        candles.append({
            "open_time":  int(c["open_time"]),
            "close_time": int(c["close_time"]),
            "open":       float(c["open"]),
            "high":       float(c["high"]),
            "low":        float(c["low"]),
            "close":      float(c["close"]),
            "volume":     float(c["volume"]),
            "num_trades": int(c["num_trades"]),
            # Taker buy ratio: buy volume / total volume — measures aggression direction
            "taker_buy_ratio": (
                float(c["taker_buy_base_vol"]) / float(c["volume"])
                if float(c["volume"]) > 0 else 0.5
            ),
        })
    return candles


def get_market_snapshot(symbol: str | None = None) -> dict:
    """
    Convenience: fetch 4H and 1H candles + current price in one call.
    Returns dict consumed by the engine pipeline.
    """
    sym = symbol or settings.symbol
    return {
        "symbol": sym,
        "candles_4h": fetch_candles(sym, interval="4h", limit=100),
        "candles_1h": fetch_candles(sym, interval="1h", limit=100),
        "current_price": fetch_current_price(sym),
    }
