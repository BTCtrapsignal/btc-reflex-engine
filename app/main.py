"""
BTC Reflex Engine — Entry Point

Phase 1+2: Observer mode only.
Runs two threads:
  1. Observation scheduler (main intelligence loop)
  2. Monitor HTTP server  (read-only status endpoint)

Thread isolation:
  - Scheduler failure does not kill HTTP server
  - HTTP server failure does not kill scheduler
  - Monitor reads shared runtime_state — no locks needed (one writer)
"""
from __future__ import annotations
import logging
import sys
import threading

from app.database.models import init_db, init_phase2_tables
from app.notifiers.telegram_reflex_bot import send_startup_message
from app.scheduler import start_scheduler
from app.config import settings

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def _start_monitor_server() -> None:
    """
    Start the read-only monitor HTTP server in a daemon thread.
    If this fails, scheduler continues unaffected.
    Port: REFLEX_MONITOR_PORT (default 8080)
    """
    try:
        import uvicorn
        from app.monitor.status_endpoint import monitor_app

        port = int(__import__("os").getenv("REFLEX_MONITOR_PORT", "8080"))
        logger.info("[monitor] Starting status server on port %d", port)

        uvicorn.run(
            monitor_app,
            host="0.0.0.0",
            port=port,
            log_level="warning",   # keep uvicorn logs quiet
            access_log=False,
        )
    except Exception as exc:
        logger.error(
            "[monitor] Status server failed to start: %s — "
            "scheduler continues unaffected.", exc
        )


def main() -> None:
    logger.info("━━━ BTC Reflex Engine ━━━")
    logger.info("Phase 1+2 — Observer Mode")
    logger.info("Behavioral structure and rotation intelligence.")
    logger.info("No execution. No auto-trading. Observation only.")
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━")

    # Initialize database (Phase 1 + Phase 2 tables)
    logger.info("Initializing Reflex database...")
    init_db()
    init_phase2_tables()
    logger.info("Database ready.")

    # Start monitor HTTP server in background daemon thread
    # Daemon = dies automatically when main process exits
    monitor_thread = threading.Thread(
        target=_start_monitor_server,
        name="monitor-server",
        daemon=True,
    )
    monitor_thread.start()
    logger.info("[monitor] Status server thread started.")

    # Notify Telegram
    send_startup_message()

    # Start observation loop (blocking — runs forever in main thread)
    start_scheduler()


if __name__ == "__main__":
    main()
