"""
BTC Reflex Engine — Telegram Notifier

Delivers behavioral observation narratives to a dedicated Telegram bot.
Separate bot from BTC Brain — never reuses Brain's token or chat.

RESILIENCE:
  - Missing token/chat ID → silently skip, log warning, never crash
  - 404 token error → clear error message in logs, system continues
  - Network error → log and return False, system continues

ERROR THROTTLE:
  Repeated identical errors are suppressed from Telegram to prevent spam.
  First occurrence → full message sent.
  Repeats within cooldown window → Railway log only, Telegram silent.
  After cooldown → one summary sent, then resets.
"""
from __future__ import annotations
import hashlib
import logging
import time
import requests
from app.config import settings
from app.engines.context_assembler import BehavioralContext

logger = logging.getLogger(__name__)

_MAX_LENGTH = 4096

# ── Error throttle state (in-memory, per process) ────────────────────────────
# { error_hash: (first_seen_ts, suppressed_count) }
_error_throttle: dict[str, tuple[float, int]] = {}
_ERROR_COOLDOWN_SECONDS = 4 * 3600   # 4 hours


def send_observation(context: BehavioralContext) -> bool:
    if not _is_configured():
        return False
    return _send(_format_message(context))


def send_startup_message() -> bool:
    if not _is_configured():
        logger.warning(
            "[telegram] REFLEX_TELEGRAM_BOT_TOKEN or REFLEX_TELEGRAM_CHAT_ID "
            "not set in Railway ENV — Telegram alerts disabled. "
            "System will continue running in silent observer mode."
        )
        return False
    text = (
        "BTC Reflex Engine started.\n"
        "Mode: Observer only — no execution.\n"
        "Watching: structure, rotation, CHoCH, volatility.\n"
        "Alerts fire when behavioral weight exceeds threshold."
    )
    return _send(text)


def send_error_alert(error_description: str) -> bool:
    """
    Send a runtime error to Telegram with throttling.

    First occurrence: full message sent immediately.
    Repeats within cooldown: suppressed from Telegram, logged to Railway only.
    After cooldown expires: one summary sent, counter resets.
    """
    if not _is_configured():
        logger.error("[reflex_error] %s", error_description)
        return False

    error_hash = hashlib.md5(error_description[:200].encode()).hexdigest()[:12]
    now = time.time()

    if error_hash in _error_throttle:
        first_seen, suppressed_count = _error_throttle[error_hash]
        age = now - first_seen

        if age < _ERROR_COOLDOWN_SECONDS:
            # Still in cooldown — suppress Telegram, log to Railway only
            _error_throttle[error_hash] = (first_seen, suppressed_count + 1)
            logger.error(
                "[reflex_error] (suppressed from Telegram, occurrence #%d) %s",
                suppressed_count + 2, error_description
            )
            # Every 10 suppressions, send one summary so user knows it's ongoing
            if (suppressed_count + 1) % 10 == 0:
                summary = (
                    f"BTC Reflex — repeated error suppressed "
                    f"({suppressed_count + 1} times in {age / 3600:.1f}h).\n"
                    f"Error: {error_description[:120]}\n"
                    f"Check Railway logs for full detail."
                )
                return _send(summary)
            return False

        else:
            # Cooldown expired — reset and send fresh
            logger.info("[reflex_error] Cooldown expired for error hash %s — resetting.", error_hash)
            del _error_throttle[error_hash]

    # First occurrence — record and send
    _error_throttle[error_hash] = (now, 0)
    logger.error("[reflex_error] (first occurrence) %s", error_description)
    return _send(f"BTC Reflex Engine error:\n{error_description}")


# ── Internal ───────────────────────────────────────────────────────────────────

def _is_configured() -> bool:
    """Check token + chat ID are present. Log clearly if not — never crash."""
    token = settings.reflex_telegram_bot_token
    chat  = settings.reflex_telegram_chat_id

    if not token:
        logger.warning(
            "[telegram] REFLEX_TELEGRAM_BOT_TOKEN not set — "
            "add it to Railway environment variables to enable alerts."
        )
        return False
    if not chat:
        logger.warning(
            "[telegram] REFLEX_TELEGRAM_CHAT_ID not set — "
            "add it to Railway environment variables to enable alerts."
        )
        return False
    return True


def _format_message(context: BehavioralContext) -> str:
    text = context.narrative
    if len(text) > _MAX_LENGTH:
        text = text[: _MAX_LENGTH - 20] + "\n... [truncated]"
    return text


def _send(text: str) -> bool:
    """
    Send plain text message via Telegram Bot API.
    Uses plain text (no MarkdownV2) to avoid parse errors.
    Falls back to no parse_mode on any 400 error.
    Never raises — always returns True/False.
    """
    token = settings.reflex_telegram_bot_token
    chat  = settings.reflex_telegram_chat_id
    url   = f"https://api.telegram.org/bot{token}/sendMessage"

    # Attempt 1: plain text (most reliable — no parse mode escaping issues)
    payload = {
        "chat_id":                  chat,
        "text":                     text,
        "disable_web_page_preview": True,
    }

    try:
        r = requests.post(url, json=payload, timeout=10)

        if r.status_code == 200:
            logger.info("[telegram] Message sent successfully.")
            return True

        if r.status_code == 401:
            logger.error(
                "[telegram] 401 Unauthorized — REFLEX_TELEGRAM_BOT_TOKEN is invalid. "
                "Check Railway ENV variable. System continues without Telegram."
            )
            return False

        if r.status_code == 400:
            # chat_id issue or message issue — log detail
            logger.error(
                "[telegram] 400 Bad Request — check REFLEX_TELEGRAM_CHAT_ID. "
                "Response: %s", r.text[:300]
            )
            return False

        if r.status_code == 404:
            logger.error(
                "[telegram] 404 Not Found — REFLEX_TELEGRAM_BOT_TOKEN is incorrect "
                "or bot does not exist. Response: %s", r.text[:200]
            )
            return False

        logger.error(
            "[telegram] Unexpected status %d: %s", r.status_code, r.text[:200]
        )
        return False

    except requests.Timeout:
        logger.warning("[telegram] Request timed out — Telegram unreachable.")
        return False
    except requests.ConnectionError as exc:
        logger.warning("[telegram] Connection error: %s", exc)
        return False
    except Exception as exc:
        logger.error("[telegram] Unexpected error: %s", exc)
        return False
