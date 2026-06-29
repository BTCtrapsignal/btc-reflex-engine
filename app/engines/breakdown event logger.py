"""
BTC Reflex Engine — Breakdown Event Logger
Reflex Sprint 3B-P1

Single logging interface for all CompositeBreakdownDetector events.

DESIGN:
  All logging from the breakdown subsystem routes through this class.
  - Centralised log format — consistent prefix [breakdown]
  - Brain Ops can consume via log aggregation without parsing scattered calls
  - Tests can inject a mock BreakdownEventLogger to capture log events
  - Production uses the standard Python logging module

RUNTIME LOG SIGNATURES:
  [breakdown] eval level=... signals=N trend=... confidence=... weight=...
  [breakdown] cooldown_active remaining=Nmin
  [breakdown] exception (non-fatal): ...

These signatures are the authoritative runtime verification surface for
Sprint 3B-P2 observation. Do not change without updating W26_RUNTIME_EVIDENCE.md.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.engines.composite_breakdown_detector import BreakdownSignals

logger = logging.getLogger(__name__)


class BreakdownEventLogger:
    """
    Centralised event logger for CompositeBreakdownDetector.

    All log calls from the breakdown subsystem go through this class.
    Inject a subclass or mock in tests to capture events without parsing strings.

    Log level policy:
      INFO  — every evaluation result (fired or not)
      INFO  — cooldown skipped
      ERROR — non-fatal exceptions
      DEBUG — extended signal detail (not emitted in production by default)
    """

    # ── Core evaluation event ──────────────────────────────────────────────────

    def evaluation(
        self,
        level: str,
        signals: "BreakdownSignals",
        verdict: str,
        confidence: str,
        weight: float,
    ) -> None:
        logger.info(
            "[breakdown] eval level=%s signals=%d trend=%s "
            "verdict=%s confidence=%s weight=%.3f "
            "flags=%s",
            level,
            signals.bearish_count,
            signals.trend_bearish,
            verdict,
            confidence,
            weight,
            ",".join(signals.as_tags()) if signals.as_tags() else "none",
        )

    # ── Cooldown event ─────────────────────────────────────────────────────────

    def cooldown_skipped(self, remaining_min: int) -> None:
        logger.info(
            "[breakdown] cooldown_active remaining=%dmin", remaining_min
        )

    # ── Exception event ────────────────────────────────────────────────────────

    def exception(self, exc: Exception) -> None:
        logger.error(
            "[breakdown] exception (non-fatal): %s", exc, exc_info=True
        )

    # ── Optional debug events ──────────────────────────────────────────────────

    def signal_detail(
        self,
        s_verdict: bool,
        s_volume: bool,
        s_choch: bool,
        s_rotation: bool,
        s_post_expansion: bool,
        exp_score: float,
        vol_state: str,
    ) -> None:
        logger.debug(
            "[breakdown] signals detail: verdict=%s volume=%s choch=%s "
            "rotation=%s post_exp=%s exp_score=%.2f vol_state=%s",
            s_verdict, s_volume, s_choch,
            s_rotation, s_post_expansion, exp_score, vol_state,
        )


class CapturingBreakdownEventLogger(BreakdownEventLogger):
    """
    Test double that captures all events without writing to logging.

    Use in unit tests:
        event_log = CapturingBreakdownEventLogger()
        detector  = CompositeBreakdownDetector(event_logger=event_log)
        result    = detector.evaluate(ctx)
        assert event_log.last_level == "BEARISH_BREAKDOWN_WATCH"
    """

    def __init__(self) -> None:
        self.events:        list[dict] = []
        self.last_level:    str        = ""
        self.cooldowns:     int        = 0
        self.exceptions:    list[str]  = []

    def evaluation(self, level, signals, verdict, confidence, weight) -> None:
        self.last_level = level
        self.events.append({
            "type":       "evaluation",
            "level":      level,
            "signals":    signals.bearish_count,
            "verdict":    verdict,
            "confidence": confidence,
            "weight":     weight,
            "tags":       signals.as_tags(),
        })

    def cooldown_skipped(self, remaining_min: int) -> None:
        self.cooldowns += 1
        self.events.append({
            "type":      "cooldown",
            "remaining": remaining_min,
        })

    def exception(self, exc: Exception) -> None:
        self.exceptions.append(str(exc))
        self.events.append({
            "type":    "exception",
            "message": str(exc),
        })

    def signal_detail(self, **kwargs) -> None:
        self.events.append({"type": "signal_detail", **kwargs})

    def reset(self) -> None:
        self.events     = []
        self.last_level = ""
        self.cooldowns  = 0
        self.exceptions = []
