"""
BTC Reflex Engine — Telegram Notifier

Delivers behavioral observation narratives to a dedicated Telegram bot.
This is a SEPARATE bot from BTC Brain — never reuses Brain's token or chat.

Alert format philosophy:
  Every alert describes behavioral context.
  No buy/sell commands. No price targets. No leverage recommendations.
  The trader receives a structured observation and interprets it.
"""
from __future__ import annotations
import logging
import requests
from app.config import settings
from app.engines.context_assembler import BehavioralContext

logger = logging.getLogger(__name__)

# Telegram message length limit
_MAX_LENGTH = 4096


def send_observation(context: BehavioralContext) -> bool:
    """
    Send a behavioral observation to the Reflex Telegram bot.

    Args:
        context: Assembled BehavioralContext from the context assembler.

    Returns:
        True if message sent successfully, False otherwise.
    """
    if not settings.reflex_telegram_bot_token or not settings.reflex_telegram_chat_id:
        logger.warning("[telegram] Bot token or chat ID not configured — alert suppressed.")
        return False

    text = _format_message(context)
    return _send(text)


def send_startup_message() -> bool:
    """Notify that Reflex Engine has started in observer mode."""
    text = (
        "🟢 BTC Reflex Engine started.\n"
        "Mode: Observer only — no execution.\n"
        "Watching: structure, rotation, CHoCH, volatility.\n"
        "Alerts will appear when behavioral weight exceeds threshold."
    )
    return _send(text)


def send_error_alert(error_description: str) -> bool:
    """Send a system error notification."""
    text = f"⚠️ BTC Reflex Engine error:\n{error_description}"
    return _send(text)


# ── Internal ──────────────────────────────────────────────────────────────────

def _format_message(context: BehavioralContext) -> str:
    """
    Format the behavioral context narrative for Telegram.
    Uses Markdown-safe formatting (no special chars that break Telegram).
    """
    # The narrative is already fully assembled by BehavioralContextAssembler
    # Wrap it in a code block for clean Telegram rendering
    text = f"```\n{context.narrative}\n```"

    # Truncate if over limit (rare, but safe)
    if len(text) > _MAX_LENGTH:
        text = text[: _MAX_LENGTH - 10] + "\n...```"

    return text


def _send(text: str) -> bool:
    """Send a raw text message via Telegram Bot API."""
    url = (
        f"https://api.telegram.org/bot{settings.reflex_telegram_bot_token}/sendMessage"
    )
    payload = {
        "chat_id": settings.reflex_telegram_chat_id,
        "text": text,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True,
    }

    # MarkdownV2 requires escaping. Use plain text as fallback.
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            logger.info("[telegram] Alert sent.")
            return True

        # If MarkdownV2 parse fails, retry as plain text
        if r.status_code == 400 and "parse" in r.text.lower():
            payload["parse_mode"] = "HTML"
            payload["text"] = _strip_code_block(text)
            r2 = requests.post(url, json=payload, timeout=10)
            if r2.status_code == 200:
                logger.info("[telegram] Alert sent (plain fallback).")
                return True
            logger.error("[telegram] Plain fallback also failed: %s", r2.text)
            return False

        logger.error("[telegram] Send failed %d: %s", r.status_code, r.text[:200])
        return False

    except requests.RequestException as exc:
        logger.error("[telegram] Request error: %s", exc)
        return False


def _strip_code_block(text: str) -> str:
    """Remove code block markers for plain text fallback."""
    return text.replace("```", "").strip()
