"""
BTC Reflex Engine — Binance Candle Feed

Fetches OHLCV candles via Binance public REST API.
No API key required for market data.

FAILOVER STRATEGY:
  Binance has multiple API endpoints. Some Railway regions are geo-blocked
  on the primary endpoint (HTTP 451 — Unavailable For Legal Reasons).
  The fetcher tries each endpoint in order until one succeeds.

  Priority:
    1. api.binance.com        (primary)
    2. api1.binance.com       (fallback 1)
    3. api2.binance.com       (fallback 2)
    4. api3.binance.com       (fallback 3)

  BINANCE_BASE_URL in ENV overrides the primary if set.
  All fallbacks are always attempted regardless of ENV setting.
"""
from __future__ import annotations
import logging
import time
from typing import Optional
import requests
from app.config import settings

logger = logging.getLogger(__name__)

# Klines column order (Binance API spec)
_KLINE_KEYS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "num_trades",
    "taker_buy_base_vol", "taker_buy_quote_vol", "ignore",
]

# Endpoint failover chain — tried in order
# Primary from settings, then hardcoded fallbacks
def _get_endpoints() -> list[str]:
    primary = settings.binance_base_url.rstrip("/")
    fallbacks = [
        "https://api1.binance.com",
        "https://api2.binance.com",
        "https://api3.binance.com",
        "https://api.binance.com",
    ]
    # Primary first, then all fallbacks (deduped)
    chain = [primary] + [f for f in fallbacks if f != primary]
    return chain


def fetch_candles(
    symbol: str | None = None,
    interval: str = "4h",
    limit: int = 100,
    retry_delay: float = 3.0,
) -> list[dict]:
    """
    Fetch OHLCV candles from Binance with automatic endpoint failover.

    Tries each endpoint in the failover chain.
    Returns [] only if ALL endpoints fail — never raises.
    """
    sym = symbol or settings.symbol
    params = {"symbol": sym, "interval": interval, "limit": limit}
    endpoints = _get_endpoints()

    for base_url in endpoints:
        url = f"{base_url}/api/v3/klines"
        try:
            r = requests.get(url, params=params, timeout=15)

            # 451 = geo-blocked — try next endpoint immediately
            if r.status_code == 451:
                logger.warning(
                    "[binance_feed] %s geo-blocked (451) — trying next endpoint", base_url
                )
                continue

            r.raise_for_status()
            candles = _parse_klines(r.json())
            logger.info(
                "[binance_feed] %s %s: %d candles via %s",
                sym, interval, len(candles), base_url
            )
            return candles

        except requests.HTTPError as exc:
            logger.warning("[binance_feed] HTTP error at %s: %s", base_url, exc)
            time.sleep(retry_delay)
        except requests.ConnectionError as exc:
            logger.warning("[binance_feed] Connection error at %s: %s", base_url, exc)
        except requests.Timeout:
            logger.warning("[binance_feed] Timeout at %s", base_url)
        except Exception as exc:
            logger.warning("[binance_feed] Unexpected error at %s: %s", base_url, exc)

    logger.error(
        "[binance_feed] All endpoints exhausted for %s %s — returning empty",
        sym, interval
    )
    return []


def fetch_current_price(symbol: str | None = None) -> Optional[float]:
    """
    Fetch latest price with endpoint failover.
    Returns None if all endpoints fail — never raises.
    """
    sym = symbol or settings.symbol
    endpoints = _get_endpoints()

    for base_url in endpoints:
        url = f"{base_url}/api/v3/ticker/price"
        try:
            r = requests.get(url, params={"symbol": sym}, timeout=8)
            if r.status_code == 451:
                logger.warning("[binance_feed] price: %s geo-blocked — trying next", base_url)
                continue
            r.raise_for_status()
            price = float(r.json()["price"])
            logger.info("[binance_feed] price %s: %.2f via %s", sym, price, base_url)
            return price
        except Exception as exc:
            logger.warning("[binance_feed] price fetch failed at %s: %s", base_url, exc)

    logger.error("[binance_feed] All endpoints failed for price — returning None")
    return None


def _parse_klines(raw: list) -> list[dict]:
    """Parse raw Binance kline arrays into clean dicts."""
    candles = []
    for row in raw:
        c = dict(zip(_KLINE_KEYS, row))
        vol = float(c["volume"])
        candles.append({
            "open_time":       int(c["open_time"]),
            "close_time":      int(c["close_time"]),
            "open":            float(c["open"]),
            "high":            float(c["high"]),
            "low":             float(c["low"]),
            "close":           float(c["close"]),
            "volume":          vol,
            "num_trades":      int(c["num_trades"]),
            "taker_buy_ratio": (
                float(c["taker_buy_base_vol"]) / vol if vol > 0 else 0.5
            ),
        })
    return candles


def get_market_snapshot(symbol: str | None = None) -> dict:
    """
    Fetch 4H and 1H candles + current price in one call.
    All three use the same failover chain independently.
    """
    sym = symbol or settings.symbol
    return {
        "symbol":        sym,
        "candles_4h":    fetch_candles(sym, interval="4h", limit=100),
        "candles_1h":    fetch_candles(sym, interval="1h", limit=100),
        "current_price": fetch_current_price(sym),
    }
