"""
BTC Reflex Engine — Monitor Status Endpoint

Lightweight read-only HTTP endpoint for btc-system-monitor.

ISOLATION GUARANTEE:
  - Read-only. Zero writes.
  - If this server crashes, scheduler continues unaffected.
  - If monitor crashes, Reflex continues unaffected.
  - No dependency in either direction.

ENDPOINTS:
  GET /status        — full operational status (for monitor)
  GET /health        — minimal liveness check (for Railway health probe)
  GET /              — identity confirmation

SECURITY:
  - Exposes only operational summary fields
  - No internal engine state
  - No memory structure internals
  - No execution capabilities
  - No write interfaces
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.monitor.runtime_state import get_status
from app.config import settings

logger = logging.getLogger(__name__)

# ── FastAPI app ───────────────────────────────────────────────────────────────
# Separate from any main app — isolated, lightweight.
monitor_app = FastAPI(
    title="BTC Reflex Engine — Monitor API",
    description="Read-only operational status for btc-system-monitor.",
    version="1.0.0",
    docs_url=None,      # disable Swagger UI in production
    redoc_url=None,
)


@monitor_app.get("/")
async def root():
    """Identity confirmation."""
    return {
        "service":     "btc-reflex-engine",
        "role":        "behavioral_observer",
        "runtime_mode": "passive",
        "execution":   False,
    }


@monitor_app.get("/health")
async def health():
    """
    Minimal liveness check.
    Returns 200 if the HTTP server is alive.
    Used by Railway health probes and monitor watchdog.
    """
    return {"status": "ok", "ts": datetime.now(timezone.utc).isoformat()}


@monitor_app.get("/status")
async def status():
    """
    Full operational status for btc-system-monitor.

    Returns safe operational summary only.
    Never exposes internals, execution state, or memory structures.
    """
    try:
        data = get_status()
        logger.debug("[monitor] /status served: cycles=%d", data.get("cycles_completed", 0))
        return JSONResponse(content=data)
    except Exception as exc:
        logger.error("[monitor] /status error: %s", exc)
        return JSONResponse(
            status_code=503,
            content={
                "status":  "degraded",
                "error":   "status_unavailable",
                "message": "Runtime state temporarily unavailable.",
            },
        )
