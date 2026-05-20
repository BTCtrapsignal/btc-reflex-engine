"""
BTC Reflex Engine — Configuration
All settings sourced from environment variables with safe defaults.
Never shares ENV namespace with BTC Brain Ops (all keys prefixed REFLEX_).
"""
from __future__ import annotations
from pydantic import BaseModel
from dotenv import load_dotenv
import os

load_dotenv()


class Settings(BaseModel):
    # ── Database ────────────────────────────────────────────────────────────
    reflex_database_url: str = os.getenv(
        "REFLEX_DATABASE_URL", "sqlite:///reflex.db"
    )

    # ── Telegram (separate bot, separate chat — never reuse Brain bot) ───────
    reflex_telegram_bot_token: str | None = os.getenv("REFLEX_TELEGRAM_BOT_TOKEN")
    reflex_telegram_chat_id: str | None = os.getenv("REFLEX_TELEGRAM_CHAT_ID")

    # ── Brain Ops read-only feed ─────────────────────────────────────────────
    brain_state_url: str | None = os.getenv("BRAIN_STATE_URL")

    # ── Binance data feed ────────────────────────────────────────────────────
    binance_base_url: str = os.getenv(
        "BINANCE_BASE_URL", "https://api.binance.com"
    )
    symbol: str = os.getenv("SYMBOL", "BTCUSDT")

    # ── System mode (observer = alert-only, no execution) ───────────────────
    mode: str = os.getenv("MODE", "observer")

    # ── Scheduler intervals (seconds) ───────────────────────────────────────
    poll_interval_4h: int = int(os.getenv("POLL_INTERVAL_4H", "3600"))   # 1 hr check
    poll_interval_1h: int = int(os.getenv("POLL_INTERVAL_1H", "900"))    # 15 min check

    # ── Structure detection thresholds ──────────────────────────────────────
    # Minimum candles needed to define a swing point
    swing_lookback: int = int(os.getenv("SWING_LOOKBACK", "5"))
    # How close to boundary (% of range) counts as "at boundary"
    boundary_proximity_pct: float = float(os.getenv("BOUNDARY_PROXIMITY_PCT", "0.03"))

    # ── Alert thresholds ─────────────────────────────────────────────────────
    # Minimum behavioral weight to send a Telegram alert
    alert_threshold: float = float(os.getenv("ALERT_THRESHOLD", "0.40"))


settings = Settings()
