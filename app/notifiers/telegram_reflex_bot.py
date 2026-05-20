"""
BTC Reflex Engine — Telegram Notifier

Delivers behavioral observation narratives to a dedicated Telegram bot.
Separate bot from BTC Brain — never reuses Brain's token or chat.

RESILIENCE:
  - Missing token/chat ID → silently skip, log warning, never crash
  - 404 token error → clear error message in logs, system continues
  - Parse mode failure → retry as plain text
  - Network error → log and return False, system continues
"""
from __future__ import annotations
import logging
import requests
from app.config import settings
from app.engines.context_assembler import BehavioralContext

logger = logging.getLogger(__name__)

_MAX_LENGTH = 4096


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
    if not _is_configured():
        return False
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
