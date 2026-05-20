"""
BTC Reflex Engine — Brain Ops Reader

READ-ONLY integration with BTC Brain Ops.
Fetches contextual state via HTTP GET only.

INTEGRATION RULES:
  - Never writes to Brain Ops
  - Never imports Brain Ops modules
  - Never shares DB or mutable state
  - Fails gracefully with a safe fallback state
  - Brain Ops must remain fully functional if this fails

FALLBACK PHILOSOPHY:
  If Brain Ops is unreachable, Reflex continues operating with
  a conservative fallback state (unknown regime, neutral bias).
  Brain context enriches observations — it does not gate them.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Optional
import requests
from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class BrainState:
    """
    Read-only snapshot of BTC Brain Ops contextual state.
    Used to enrich Reflex behavioral observations only.
    Never used to gate or block Reflex operation.
    """
    market_regime: str        # "bull_trend", "bear_trend", "ranging", "distribution", "unknown"
    macro_bias: str           # "bullish", "bearish", "neutral"
    confidence: float         # 0.0–1.0
    continuation_state: str   # "continuing", "weakening", "exhausted", "reversing", "unknown"
    volatility_state: str     # "low", "normal", "elevated", "extreme", "unknown"
    risk_mode: str            # "normal", "reduced", "off"
    source: str               # "btc_brain_ops_live" or "fallback"


_FALLBACK_STATE = BrainState(
    market_regime="unknown",
    macro_bias="neutral",
    confidence=0.0,
    continuation_state="unknown",
    volatility_state="unknown",
    risk_mode="normal",
    source="fallback",
)


def fetch_brain_state(timeout: float = 5.0) -> BrainState:
    """
    Fetch current state from BTC Brain Ops /brain-state endpoint.

    Returns the live state on success, or a safe fallback on any failure.
    Reflex must never crash or block due to Brain Ops unavailability.

    Args:
        timeout: HTTP timeout in seconds.
    """
    url = settings.brain_state_url
    if not url:
        logger.debug("[brain_reader] BRAIN_STATE_URL not configured — using fallback.")
        return _FALLBACK_STATE

    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        state = _parse_brain_state(data)
        logger.info(
            "[brain_reader] Brain state fetched: regime=%s bias=%s conf=%.2f",
            state.market_regime, state.macro_bias, state.confidence
        )
        return state

    except requests.Timeout:
        logger.warning("[brain_reader] Brain Ops request timed out — using fallback.")
        return _FALLBACK_STATE
    except requests.ConnectionError:
        logger.warning("[brain_reader] Brain Ops unreachable — using fallback.")
        return _FALLBACK_STATE
    except requests.HTTPError as exc:
        logger.warning("[brain_reader] Brain Ops HTTP error %s — using fallback.", exc)
        return _FALLBACK_STATE
    except (ValueError, KeyError) as exc:
        logger.warning("[brain_reader] Brain Ops response parse error %s — using fallback.", exc)
        return _FALLBACK_STATE
    except Exception as exc:
        logger.error("[brain_reader] Unexpected error: %s — using fallback.", exc)
        return _FALLBACK_STATE


def _parse_brain_state(data: dict) -> BrainState:
    """
    Parse the /brain-state response dict into a BrainState.
    All fields have safe defaults — malformed responses never crash Reflex.
    """
    return BrainState(
        market_regime=str(data.get("market_regime", "unknown")),
        macro_bias=str(data.get("macro_bias", "neutral")),
        confidence=_safe_float(data.get("confidence", 0.0)),
        continuation_state=str(data.get("continuation_state", "unknown")),
        volatility_state=str(data.get("volatility_state", "unknown")),
        risk_mode=str(data.get("risk_mode", "normal")),
        source=str(data.get("source", "unknown")),
    )


def _safe_float(val) -> float:
    try:
        return round(float(val), 4)
    except (TypeError, ValueError):
        return 0.0
