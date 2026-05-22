"""
BTC Reflex Engine — Telegram Notifier

Operational hardening layer for Telegram delivery.

RESILIENCE GUARANTEES:
  1. Telegram failure NEVER crashes the scheduler or analysis pipeline.
     Every public function returns True/False — never raises.

  2. Retry policy: max 2 retries with exponential backoff (2s → 5s).
     Applied only to recoverable errors (timeout, 5xx, network).
     NOT applied to permanent errors (401, 404, 400).

  3. Error classification:
       PERMANENT  — wrong token/chat_id → log once, stop retrying
       RATE_LIMIT — 429 → respect Retry-After header, then retry
       TRANSIENT  — timeout / 5xx / network → retry with backoff
       UNKNOWN    — unexpected status → log, no retry

  4. Send-failure cooldown:
       If Telegram fails repeatedly (same error class), suppress
       duplicate error noise for 15 minutes.
       Full detail always in Railway logs.
       One summary message per cooldown window.

  5. Error throttle (runtime errors from scheduler):
       First occurrence → full Telegram message.
       Repeats within 4h → Railway log only.
       Every 10 suppressions → one summary.
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

# ── Retry policy ──────────────────────────────────────────────────────────────
_RETRY_MAX          = 2
_RETRY_DELAYS       = [2.0, 5.0]   # seconds: attempt 1 → wait 2s → attempt 2 → wait 5s

# ── Send-failure cooldown (suppresses repeated delivery failure noise) ─────────
_SEND_FAIL_COOLDOWN = 15 * 60      # 15 minutes
# { error_class: (first_fail_ts, suppressed_count) }
_send_fail_state: dict[str, tuple[float, int]] = {}

# ── Runtime error throttle (from scheduler cycle errors) ─────────────────────
_ERROR_COOLDOWN     = 4 * 3600     # 4 hours
# { error_hash: (first_seen_ts, suppressed_count) }
_error_throttle: dict[str, tuple[float, int]] = {}


# ── Public API ────────────────────────────────────────────────────────────────

def send_observation(context: BehavioralContext) -> bool:
    """Send a full behavioral observation narrative."""
    if not _is_configured():
        return False
    return _send_with_retry(_format_message(context))


def send_raw(text: str) -> bool:
    """Send a pre-formatted plain text message (persistence reminders etc.)."""
    if not _is_configured():
        return False
    return _send_with_retry(text)


def send_startup_message() -> bool:
    """One-time boot notification. Outside alert gate — intentional."""
    if not _is_configured():
        logger.warning(
            "[telegram] Token or chat ID not set — "
            "Telegram alerts disabled. Observer mode continues silently."
        )
        return False
    text = (
        "BTC Reflex Engine started.\n"
        "Mode: Observer only — no execution.\n"
        "Watching: structure, rotation, CHoCH, volatility.\n"
        "Alerts fire on meaningful structural events only."
    )
    return _send_with_retry(text)


def send_error_alert(error_description: str) -> bool:
    """
    Send a runtime error alert with throttling.
    First occurrence → full message.
    Repeats within 4h → Railway log only.
    Every 10 suppressions → one summary.
    """
    if not _is_configured():
        logger.error("[reflex_error] %s", error_description)
        return False

    error_hash = hashlib.md5(error_description[:200].encode()).hexdigest()[:12]
    now        = time.time()

    if error_hash in _error_throttle:
        first_seen, count = _error_throttle[error_hash]
        age = now - first_seen

        if age < _ERROR_COOLDOWN:
            _error_throttle[error_hash] = (first_seen, count + 1)
            logger.error(
                "[reflex_error] (suppressed #%d) %s", count + 2, error_description
            )
            if (count + 1) % 10 == 0:
                summary = (
                    f"BTC Reflex — repeated error suppressed "
                    f"({count + 1}x in {age / 3600:.1f}h).\n"
                    f"Error: {error_description[:120]}\n"
                    f"Full detail in Railway logs."
                )
                return _send_with_retry(summary)
            return False
        else:
            logger.info("[reflex_error] Cooldown expired for hash %s — resetting.", error_hash)
            del _error_throttle[error_hash]

    _error_throttle[error_hash] = (now, 0)
    logger.error("[reflex_error] (first occurrence) %s", error_description)
    return _send_with_retry(f"BTC Reflex Engine error:\n{error_description}")


# ── Internal: retry + backoff ─────────────────────────────────────────────────

def _send_with_retry(text: str) -> bool:
    """
    Attempt delivery with retry on recoverable failures.

    Retry policy:
      attempt 1 → on transient fail → wait 2s
      attempt 2 → on transient fail → wait 5s
      attempt 3 (final) → log failure, return False

    Permanent errors (401, 404, 400) abort immediately — no retry.
    Rate limit (429) respects Retry-After header before retrying.
    All failures are non-blocking — scheduler continues regardless.
    """
    for attempt in range(_RETRY_MAX + 1):
        error_class, success = _send_once(text)

        if success:
            _clear_send_fail(error_class)
            return True

        if error_class == "permanent":
            # Wrong token / chat ID — retrying won't help
            _record_send_fail(error_class)
            return False

        if attempt < _RETRY_MAX:
            delay = _RETRY_DELAYS[attempt]
            logger.warning(
                "[telegram] %s — retrying in %.0fs (attempt %d/%d)",
                error_class, delay, attempt + 1, _RETRY_MAX
            )
            time.sleep(delay)

    # All retries exhausted
    _record_send_fail(error_class)
    return False


def _send_once(text: str) -> tuple[str, bool]:
    """
    Single Telegram API call.
    Returns (error_class, success).

    Error classes:
      "permanent"   — 401 Unauthorized, 404 Not Found, 400 Bad Request
      "rate_limit"  — 429 Too Many Requests
      "transient"   — timeout, 5xx, connection error
      "unknown"     — unexpected status code
      "ok"          — success
    """
    token   = settings.reflex_telegram_bot_token
    chat    = settings.reflex_telegram_chat_id
    url     = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id":                  chat,
        "text":                     text[:_MAX_LENGTH],
        "disable_web_page_preview": True,
    }

    try:
        r = requests.post(url, json=payload, timeout=10)

        if r.status_code == 200:
            logger.info("[telegram] Sent successfully.")
            return "ok", True

        if r.status_code == 429:
            retry_after = int(r.headers.get("Retry-After", 5))
            logger.warning(
                "[telegram] 429 Rate limit — Retry-After %ds.", retry_after
            )
            time.sleep(min(retry_after, 30))   # cap wait at 30s
            return "rate_limit", False

        if r.status_code == 401:
            logger.error(
                "[telegram] 401 Unauthorized — "
                "REFLEX_TELEGRAM_BOT_TOKEN invalid. Check Railway ENV."
            )
            return "permanent", False

        if r.status_code == 404:
            logger.error(
                "[telegram] 404 Not Found — "
                "bot token does not exist or has been revoked."
            )
            return "permanent", False

        if r.status_code == 400:
            logger.error(
                "[telegram] 400 Bad Request — "
                "check REFLEX_TELEGRAM_CHAT_ID. Detail: %s", r.text[:200]
            )
            return "permanent", False

        if r.status_code >= 500:
            logger.warning(
                "[telegram] %d Server error — transient.", r.status_code
            )
            return "transient", False

        logger.error(
            "[telegram] Unexpected status %d: %s", r.status_code, r.text[:200]
        )
        return "unknown", False

    except requests.Timeout:
        logger.warning("[telegram] Timeout — transient network issue.")
        return "transient", False

    except requests.ConnectionError as exc:
        logger.warning("[telegram] Connection error: %s", exc)
        return "transient", False

    except Exception as exc:
        logger.error("[telegram] Unexpected error: %s", exc)
        return "unknown", False


# ── Send-failure cooldown ─────────────────────────────────────────────────────

def _record_send_fail(error_class: str) -> None:
    """
    Track repeated delivery failures.
    Suppresses duplicate failure noise in Telegram for 15 minutes.
    Full detail always logged to Railway.
    """
    now = time.time()

    if error_class in _send_fail_state:
        first_fail, count = _send_fail_state[error_class]
        age = now - first_fail

        if age < _SEND_FAIL_COOLDOWN:
            _send_fail_state[error_class] = (first_fail, count + 1)
            logger.error(
                "[telegram] Delivery failure suppressed (class=%s count=%d age=%.0fm)",
                error_class, count + 1, age / 60
            )
            return

        # Cooldown expired — reset
        del _send_fail_state[error_class]

    _send_fail_state[error_class] = (now, 0)
    logger.error(
        "[telegram] Delivery failed (class=%s) — "
        "subsequent failures suppressed for %dm.",
        error_class, _SEND_FAIL_COOLDOWN // 60
    )


def _clear_send_fail(error_class: str) -> None:
    """Clear failure tracking on successful send."""
    if error_class in _send_fail_state:
        _, count = _send_fail_state[error_class]
        if count > 0:
            logger.info(
                "[telegram] Delivery recovered after %d suppressed failures (class=%s).",
                count, error_class
            )
        del _send_fail_state[error_class]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_configured() -> bool:
    if not settings.reflex_telegram_bot_token:
        logger.warning(
            "[telegram] REFLEX_TELEGRAM_BOT_TOKEN not set — "
            "add to Railway ENV to enable alerts."
        )
        return False
    if not settings.reflex_telegram_chat_id:
        logger.warning(
            "[telegram] REFLEX_TELEGRAM_CHAT_ID not set — "
            "add to Railway ENV to enable alerts."
        )
        return False
    return True


def _format_message(context: BehavioralContext) -> str:
    text = context.narrative
    if len(text) > _MAX_LENGTH:
        text = text[:_MAX_LENGTH - 20] + "\n... [truncated]"
    return text
