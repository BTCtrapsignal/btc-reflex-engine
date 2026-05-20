"""
BTC Reflex Engine — Entry Point

Phase 1: Observer mode only.
Starts the observation scheduler. No exchange connections. No execution.
"""
from __future__ import annotations
import logging
import sys

from app.database.models import init_db
from app.notifiers.telegram_reflex_bot import send_startup_message
from app.scheduler import start_scheduler

# ── Logging Setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("━━━ BTC Reflex Engine ━━━")
    logger.info("Phase 1 — Observer Mode")
    logger.info("Behavioral structure and rotation intelligence.")
    logger.info("No execution. No auto-trading. Observation only.")
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━")

    # Initialize database
    logger.info("Initializing Reflex database...")
    init_db()
    logger.info("Database ready.")

    # Notify Telegram
    send_startup_message()

    # Start observation loop
    start_scheduler()


if __name__ == "__main__":
    main()
