"""
BTC Reflex Engine — Research Metadata API (Phase 2)

Internal-only read-only endpoints exposing observational summaries.

DISABLED BY DEFAULT.
Enable with: REFLEX_RESEARCH_API_ENABLED=true

SECURITY:
  - Read-only. No writes. No deletes.
  - Returns summaries and statistics only.
  - Never returns execution instructions.
  - Never returns confidence overrides.
  - Never returns trade authority.

ENDPOINTS:
  GET /research/structure-summary
  GET /research/fake-breakout-history
  GET /research/volatility-patterns
  GET /research/persistence-analysis
  GET /research/sweep-history
  GET /research/failed-continuations

RESPONSE PHILOSOPHY:
  Every response describes what was historically observed.
  Nothing in any response should be interpreted as an instruction.

  Allowed: "Higher fake breakout frequency observed in compression phases."
  Never:   "Reduce confidence by 20%."
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.database.models import (
    StructureMemory, BoundaryTouchLog, PatternOutcome,
    FakeBreakoutEvent, LiquiditySweepEvent,
    VolatilityTrapEvent, FailedContinuationEvent,
    TacticalObservation,
)
from app.config import settings

logger = logging.getLogger(__name__)

_DISABLED_RESPONSE = {
    "status":  "disabled",
    "message": (
        "Research API is disabled. "
        "Set REFLEX_RESEARCH_API_ENABLED=true to enable."
    ),
}


class ResearchMetadataAPI:
    """
    Generates observational summaries for research consumption.
    All methods return plain dicts — no ORM objects exposed.
    All output is descriptive — no execution instructions.
    """

    def is_enabled(self) -> bool:
        return settings.research_api_enabled

    # ── Endpoints ─────────────────────────────────────────────────────────────

    def structure_summary(
        self, db: Session, symbol: str = "BTCUSDT", days_back: int = 30
    ) -> dict:
        """
        Summary of structure lifecycle activity over a time window.
        What structures have been active? How mature? What boundary behavior?
        """
        if not self.is_enabled():
            return _DISABLED_RESPONSE

        since    = datetime.now(timezone.utc) - timedelta(days=days_back)
        memories = db.query(StructureMemory).filter(
            StructureMemory.symbol      == symbol,
            StructureMemory.first_seen_at >= since,
        ).all()

        if not memories:
            return {
                "status":  "ok",
                "symbol":  symbol,
                "period":  f"last {days_back}d",
                "structures_observed": 0,
                "note": "No structure memory in this period.",
            }

        active = [m for m in memories if m.is_active]
        ended  = [m for m in memories if not m.is_active]

        type_counts: dict[str, int] = {}
        for m in memories:
            t = m.structure_type or "unknown"
            type_counts[t] = type_counts.get(t, 0) + 1

        avg_age = (
            sum(m.candles_alive or 0 for m in memories) / len(memories)
            if memories else 0
        )

        return {
            "status":                "ok",
            "symbol":                symbol,
            "period":                f"last {days_back}d",
            "structures_observed":   len(memories),
            "currently_active":      len(active),
            "ended_in_period":       len(ended),
            "by_structure_type":     type_counts,
            "avg_candles_alive":     round(avg_age, 1),
            "observation_note": (
                "Descriptive archive only. "
                "Not for execution decisions."
            ),
        }

    def fake_breakout_history(
        self, db: Session, symbol: str = "BTCUSDT", days_back: int = 30
    ) -> dict:
        """Summary of fake breakout event archive."""
        if not self.is_enabled():
            return _DISABLED_RESPONSE

        since  = datetime.now(timezone.utc) - timedelta(days=days_back)
        events = db.query(FakeBreakoutEvent).filter(
            FakeBreakoutEvent.symbol      == symbol,
            FakeBreakoutEvent.observed_at >= since,
        ).all()

        if not events:
            return {
                "status": "ok", "symbol": symbol,
                "period": f"last {days_back}d",
                "total": 0, "note": "No fake breakout events recorded.",
            }

        up_count   = sum(1 for e in events if e.breakout_direction == "up")
        down_count = sum(1 for e in events if e.breakout_direction == "down")
        imm_count  = sum(1 for e in events if e.rejection_speed == "immediate")
        choch_follow = sum(1 for e in events if e.choch_followed)
        avg_mag    = sum(e.breakout_magnitude_pct or 0 for e in events) / len(events)

        return {
            "status":              "ok",
            "symbol":              symbol,
            "period":              f"last {days_back}d",
            "total":               len(events),
            "upside_breakouts":    up_count,
            "downside_breakouts":  down_count,
            "immediate_rejections": imm_count,
            "choch_followed":      choch_follow,
            "avg_magnitude_pct":   round(avg_mag, 3),
            "observation_note": (
                "Historical fake breakout frequency. "
                "Does not predict future behavior."
            ),
        }

    def volatility_patterns(
        self, db: Session, symbol: str = "BTCUSDT", days_back: int = 60
    ) -> dict:
        """Summary of volatility trap archive."""
        if not self.is_enabled():
            return _DISABLED_RESPONSE

        since  = datetime.now(timezone.utc) - timedelta(days=days_back)
        events = db.query(VolatilityTrapEvent).filter(
            VolatilityTrapEvent.symbol      == symbol,
            VolatilityTrapEvent.observed_at >= since,
        ).all()

        if not events:
            return {
                "status": "ok", "symbol": symbol,
                "period": f"last {days_back}d",
                "total": 0, "note": "No volatility trap events recorded.",
            }

        avg_streak   = sum(e.compression_streak_candles or 0 for e in events) / len(events)
        avg_duration = sum(e.duration_candles or 0 for e in events) / len(events)
        by_recovery  = {}
        for e in events:
            k = e.recovery_type or "unknown"
            by_recovery[k] = by_recovery.get(k, 0) + 1

        return {
            "status":                  "ok",
            "symbol":                  symbol,
            "period":                  f"last {days_back}d",
            "total_traps":             len(events),
            "avg_compression_streak":  round(avg_streak, 1),
            "avg_trap_duration":       round(avg_duration, 1),
            "by_recovery_type":        by_recovery,
            "observation_note": (
                "Volatility trap frequency archive. "
                "Describes historical compression behavior only."
            ),
        }

    def persistence_analysis(
        self, db: Session, symbol: str = "BTCUSDT"
    ) -> dict:
        """
        Analysis of pattern outcome persistence from boundary touch archive.
        How do behavioral signatures correlate with subsequent price behavior?
        Descriptive only — no predictive claims.
        """
        if not self.is_enabled():
            return _DISABLED_RESPONSE

        patterns = db.query(PatternOutcome).filter(
            PatternOutcome.symbol            == symbol,
            PatternOutcome.total_occurrences >= 3,
        ).order_by(PatternOutcome.total_occurrences.desc()).limit(10).all()

        if not patterns:
            return {
                "status": "ok", "symbol": symbol,
                "total_patterns": 0,
                "note": "Insufficient pattern history. Archive building.",
            }

        pattern_list = []
        for p in patterns:
            total = p.total_occurrences or 1
            pattern_list.append({
                "structure_type":      p.structure_type,
                "boundary":            p.boundary,
                "occurrences":         p.total_occurrences,
                "behavioral_tendency": self._tendency_label(p.bounce_rate or 0),
                "volatility_context":  p.volatility_state,
            })

        return {
            "status":           "ok",
            "symbol":           symbol,
            "patterns_with_3plus_occurrences": len(patterns),
            "patterns":         pattern_list,
            "observation_note": (
                "Behavioral tendency descriptions only. "
                "Not confidence scores. Not trade signals."
            ),
        }

    def sweep_history(
        self, db: Session, symbol: str = "BTCUSDT", days_back: int = 30
    ) -> dict:
        """Summary of liquidity sweep archive."""
        if not self.is_enabled():
            return _DISABLED_RESPONSE

        since  = datetime.now(timezone.utc) - timedelta(days=days_back)
        events = db.query(LiquiditySweepEvent).filter(
            LiquiditySweepEvent.symbol      == symbol,
            LiquiditySweepEvent.observed_at >= since,
        ).all()

        if not events:
            return {
                "status": "ok", "symbol": symbol,
                "period": f"last {days_back}d",
                "total": 0, "note": "No sweep events recorded.",
            }

        by_dir     = {}
        by_recov   = {}
        cont_count = 0
        for e in events:
            d = e.sweep_direction or "unknown"
            by_dir[d] = by_dir.get(d, 0) + 1
            r = e.recovery_behavior or "unknown"
            by_recov[r] = by_recov.get(r, 0) + 1
            if e.continuation_after_sweep:
                cont_count += 1

        avg_mag = sum(e.sweep_magnitude_pct or 0 for e in events) / len(events)

        return {
            "status":                "ok",
            "symbol":                symbol,
            "period":                f"last {days_back}d",
            "total":                 len(events),
            "by_direction":          by_dir,
            "by_recovery_behavior":  by_recov,
            "continuation_count":    cont_count,
            "avg_magnitude_pct":     round(avg_mag, 3),
            "observation_note": (
                "Liquidity sweep behavioral archive. "
                "Historical observation only."
            ),
        }

    def failed_continuations(
        self, db: Session, symbol: str = "BTCUSDT", days_back: int = 30
    ) -> dict:
        """Summary of failed continuation archive."""
        if not self.is_enabled():
            return _DISABLED_RESPONSE

        since  = datetime.now(timezone.utc) - timedelta(days=days_back)
        events = db.query(FailedContinuationEvent).filter(
            FailedContinuationEvent.symbol      == symbol,
            FailedContinuationEvent.observed_at >= since,
        ).all()

        if not events:
            return {
                "status": "ok", "symbol": symbol,
                "period": f"last {days_back}d",
                "total": 0, "note": "No failed continuation events recorded.",
            }

        by_dir    = {}
        by_speed  = {}
        choch_cnt = sum(1 for e in events if e.choch_after_failure)
        for e in events:
            d = e.expected_direction or "unknown"
            by_dir[d] = by_dir.get(d, 0) + 1
            s = e.continuation_failure_speed or "unknown"
            by_speed[s] = by_speed.get(s, 0) + 1

        return {
            "status":                  "ok",
            "symbol":                  symbol,
            "period":                  f"last {days_back}d",
            "total":                   len(events),
            "by_expected_direction":   by_dir,
            "by_failure_speed":        by_speed,
            "choch_followed_count":    choch_cnt,
            "observation_note": (
                "Failed continuation behavioral archive. "
                "Historical observation only."
            ),
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _tendency_label(self, bounce_rate: float) -> str:
        """Behavioral description — no percentages, no predictions."""
        if bounce_rate >= 0.75: return "historically strong boundary persistence"
        if bounce_rate >= 0.55: return "historically mixed boundary behavior"
        if bounce_rate >= 0.35: return "historically weak boundary persistence"
        return "historically frequent boundary failure"
