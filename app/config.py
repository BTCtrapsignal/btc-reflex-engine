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
    reflex_brain_state_url: str | None = os.getenv("REFLEX_BRAIN_STATE_URL")

    # ── Binance data feed ────────────────────────────────────────────────────
    reflex_binance_base_url: str = os.getenv(
        "REFLEX_BINANCE_BASE_URL", "https://api.binance.com"
    )
    reflex_symbol: str = os.getenv("REFLEX_SYMBOL", "BTCUSDT")

    # ── System mode (observer = alert-only, no execution) ───────────────────
    reflex_mode: str = os.getenv("REFLEX_MODE", "observer")

    # ── Scheduler intervals (seconds) ───────────────────────────────────────
    reflex_poll_interval_4h: int = int(
        os.getenv("REFLEX_POLL_INTERVAL_4H", "3600")
    )
    reflex_poll_interval_1h: int = int(
        os.getenv("REFLEX_POLL_INTERVAL_1H", "900")
    )

    # ── Structure detection thresholds ──────────────────────────────────────
    reflex_swing_lookback: int = int(
        os.getenv("REFLEX_SWING_LOOKBACK", "5")
    )

    reflex_boundary_proximity_pct: float = float(
        os.getenv("REFLEX_BOUNDARY_PROXIMITY_PCT", "0.03")
    )

    # ── Alert thresholds ─────────────────────────────────────────────────────
    reflex_alert_threshold: float = float(
        os.getenv("REFLEX_ALERT_THRESHOLD", "0.40")
    )


settings = Settings()
