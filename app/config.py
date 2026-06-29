"""
BTC Reflex Engine — Configuration

All ENV vars use REFLEX_ prefix to prevent collision with
BTC Brain / BTC Brain Ops environment variables.

NEVER use generic names like DATABASE_URL, SYMBOL, MODE — those
may already be set in the shared Railway environment by other systems.
"""
from __future__ import annotations
from pydantic import BaseModel
from dotenv import load_dotenv
import os

load_dotenv()


class Settings(BaseModel):
    # ── Database (isolated — never shares with Brain Ops DB) ─────────────────
    reflex_database_url: str = os.getenv(
        "REFLEX_DATABASE_URL", "sqlite:///reflex.db"
    )

    # ── Telegram (separate bot — never reuse Brain bot token) ────────────────
    reflex_telegram_bot_token: str | None = os.getenv("REFLEX_TELEGRAM_BOT_TOKEN")
    reflex_telegram_chat_id: str | None   = os.getenv("REFLEX_TELEGRAM_CHAT_ID")

    # Brain Ops integration removed — W22 architecture correction
    # REFLEX_BRAIN_STATE_URL intentionally removed

    # ── Binance data feed ─────────────────────────────────────────────────────
    binance_base_url: str = os.getenv(
        "REFLEX_BINANCE_BASE_URL", "https://api.binance.com"
    )
    symbol: str = os.getenv("REFLEX_SYMBOL", "BTCUSDT")

    # ── System mode ───────────────────────────────────────────────────────────
    # "observer" = alert-only, no execution (Phase 1 — must stay observer)
    mode: str = os.getenv("REFLEX_MODE", "observer")

    # ── Scheduler intervals (seconds) ─────────────────────────────────────────
    poll_interval_4h: int = int(os.getenv("REFLEX_POLL_INTERVAL_4H", "3600"))
    poll_interval_1h: int = int(os.getenv("REFLEX_POLL_INTERVAL_1H", "900"))

    # ── Structure detection thresholds ────────────────────────────────────────
    swing_lookback: int          = int(os.getenv("REFLEX_SWING_LOOKBACK", "5"))
    boundary_proximity_pct: float = float(os.getenv("REFLEX_BOUNDARY_PROXIMITY_PCT", "0.03"))

    # ── Alert gate tuning ─────────────────────────────────────────────────────
    # Minimum minutes between MEDIUM-priority Telegram alerts
    medium_cooldown_minutes: int = int(
        os.getenv("REFLEX_MEDIUM_COOLDOWN_MINUTES", "45")
    )
    # Hours of structural persistence before a single reminder is allowed
    persistence_reminder_hours: float = float(
        os.getenv("REFLEX_PERSISTENCE_REMINDER_HOURS", "8")
    )

    # ── Monitor HTTP server ───────────────────────────────────────────────────
    # Port for read-only status endpoint (for btc-system-monitor)
    monitor_port: int = int(os.getenv("REFLEX_MONITOR_PORT", "8080"))

    # ── Phase 2 features ─────────────────────────────────────────────────────
    # Sandbox framework (disabled by default — set true to enable replay queries)
    sandbox_enabled: bool = os.getenv("REFLEX_SANDBOX_ENABLED", "false").lower() == "true"
    # Research metadata API (disabled by default)
    research_api_enabled: bool = os.getenv("REFLEX_RESEARCH_API_ENABLED", "false").lower() == "true"

    # ── Alert threshold ───────────────────────────────────────────────────────
    # Minimum behavioral weight to trigger Telegram alert (0.0–1.0)
    alert_threshold: float = float(os.getenv("REFLEX_ALERT_THRESHOLD", "0.40"))

    # ── Composite Breakdown Detector (Sprint 3B-P1) ───────────────────────────
    # Observer mode only. No execution. No Signal Bot modification.
    # All ENV vars prefixed REFLEX_ per project convention.

    # Seconds between consecutive breakdown alerts (default: 30 min)
    breakdown_cooldown_secs: int = int(
        os.getenv("REFLEX_BREAKDOWN_COOLDOWN_SECS", "1800")
    )
    # Minimum non-trend signals for WATCH level
    breakdown_signals_watch: int = int(
        os.getenv("REFLEX_BREAKDOWN_SIGNALS_WATCH", "2")
    )
    # Minimum non-trend signals for HIGH_RISK level
    breakdown_signals_high: int = int(
        os.getenv("REFLEX_BREAKDOWN_SIGNALS_HIGH", "3")
    )
    # Minimum volatility.expansion_score to flag volume expansion
    breakdown_volume_expansion_min: float = float(
        os.getenv("REFLEX_BREAKDOWN_VOLUME_MIN", "0.55")
    )


settings = Settings()
