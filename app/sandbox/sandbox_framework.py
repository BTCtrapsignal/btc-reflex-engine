"""
BTC Reflex Engine — Sandbox / Replay Framework (Phase 2)

Isolated experimental environment for replaying and analyzing
historical observations from the Reflex archive.

ISOLATION GUARANTEE:
  - Reads only from Reflex DB (never Brain, never OPS)
  - Writes only to sandbox_* tables (never production tables)
  - Never executes trades
  - Never modifies live state
  - Never calls exchange APIs
  - Disabled by default (REFLEX_SANDBOX_ENABLED=false)

PURPOSE:
  - Replay historical behavioral observations
  - Compare structural patterns across time
  - Analyze recurring behavioral signatures
  - Test observational hypotheses offline
  - Measure archive quality

PHILOSOPHY:
  The sandbox is a research environment.
  Insights from sandbox analysis are for human interpretation.
  The sandbox never feeds decisions back into production.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.orm import Session
from app.database.models import (
    StructureMemory, BoundaryTouchLog, PatternOutcome,
    FakeBreakoutEvent, LiquiditySweepEvent,
    VolatilityTrapEvent, FailedContinuationEvent,
)
from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ReplayResult:
    """Result of a sandbox replay session. Read-only research output."""
    query_description: str
    total_events:      int
    time_range_start:  Optional[datetime]
    time_range_end:    Optional[datetime]
    summary:           dict = field(default_factory=dict)
    observations:      list[dict] = field(default_factory=list)
    researcher_notes:  str = ""


class SandboxFramework:
    """
    Isolated research and replay framework.

    All methods are read-only from the DB perspective.
    No method modifies any production table.
    Returns ReplayResult objects for human interpretation only.
    """

    def __init__(self):
        if not settings.sandbox_enabled:
            logger.info(
                "[sandbox] Sandbox is disabled. "
                "Set REFLEX_SANDBOX_ENABLED=true to enable."
            )

    def is_enabled(self) -> bool:
        return settings.sandbox_enabled

    # ── Replay Queries ────────────────────────────────────────────────────────

    def replay_fake_breakouts(
        self,
        db: Session,
        symbol: str = "BTCUSDT",
        days_back: int = 30,
        structure_type: Optional[str] = None,
        direction: Optional[str] = None,
    ) -> ReplayResult:
        """
        Replay fake breakout events from the archive.
        Analyze frequency, speed, and structural context.
        """
        if not self.is_enabled():
            return self._disabled_result("fake_breakouts")

        since = datetime.now(timezone.utc) - timedelta(days=days_back)
        q = db.query(FakeBreakoutEvent).filter(
            FakeBreakoutEvent.symbol == symbol,
            FakeBreakoutEvent.observed_at >= since,
        )
        if structure_type:
            q = q.filter(FakeBreakoutEvent.structure_type == structure_type)
        if direction:
            q = q.filter(FakeBreakoutEvent.breakout_direction == direction)

        events = q.order_by(FakeBreakoutEvent.observed_at.desc()).all()

        if not events:
            return ReplayResult(
                query_description="Fake breakout replay",
                total_events=0,
                time_range_start=since,
                time_range_end=datetime.now(timezone.utc),
                researcher_notes="No fake breakout events recorded in this period.",
            )

        # Build summary statistics
        by_direction  = self._count_by(events, "breakout_direction")
        by_speed      = self._count_by(events, "rejection_speed")
        by_volatility = self._count_by(events, "volatility_state")
        by_structure  = self._count_by(events, "structure_type")
        avg_magnitude = sum(e.breakout_magnitude_pct or 0 for e in events) / len(events)
        choch_count   = sum(1 for e in events if e.choch_followed)

        return ReplayResult(
            query_description=f"Fake breakout replay — {days_back}d",
            total_events=len(events),
            time_range_start=since,
            time_range_end=datetime.now(timezone.utc),
            summary={
                "by_direction":        by_direction,
                "by_rejection_speed":  by_speed,
                "by_volatility_state": by_volatility,
                "by_structure_type":   by_structure,
                "avg_magnitude_pct":   round(avg_magnitude, 3),
                "choch_followed_count": choch_count,
                "choch_followed_rate": round(choch_count / len(events), 3),
            },
            researcher_notes=self._fake_breakout_notes(events, by_direction, by_speed),
        )

    def replay_compression_regimes(
        self,
        db: Session,
        symbol: str = "BTCUSDT",
        days_back: int = 60,
    ) -> ReplayResult:
        """
        Replay volatility trap events to study compression regime behavior.
        How often does compression lead to a trap vs genuine expansion?
        """
        if not self.is_enabled():
            return self._disabled_result("compression_regimes")

        since  = datetime.now(timezone.utc) - timedelta(days=days_back)
        events = db.query(VolatilityTrapEvent).filter(
            VolatilityTrapEvent.symbol     == symbol,
            VolatilityTrapEvent.observed_at >= since,
        ).order_by(VolatilityTrapEvent.observed_at.desc()).all()

        if not events:
            return ReplayResult(
                query_description="Compression regime replay",
                total_events=0,
                time_range_start=since,
                time_range_end=datetime.now(timezone.utc),
                researcher_notes="No volatility trap events in this period.",
            )

        by_direction    = self._count_by(events, "trap_direction")
        by_recovery     = self._count_by(events, "recovery_type")
        by_structure    = self._count_by(events, "structure_type")
        avg_streak      = sum(e.compression_streak_candles or 0 for e in events) / len(events)
        avg_duration    = sum(e.duration_candles or 0 for e in events) / len(events)

        return ReplayResult(
            query_description=f"Compression regime replay — {days_back}d",
            total_events=len(events),
            time_range_start=since,
            time_range_end=datetime.now(timezone.utc),
            summary={
                "by_trap_direction":      by_direction,
                "by_recovery_type":       by_recovery,
                "by_structure_type":      by_structure,
                "avg_compression_streak": round(avg_streak, 1),
                "avg_trap_duration_candles": round(avg_duration, 1),
            },
            researcher_notes=(
                f"Compression traps most common in: "
                f"{max(by_structure, key=by_structure.get, default='unknown')} structures. "
                f"Average streak before trap: {avg_streak:.1f} candles."
            ),
        )

    def replay_liquidity_sweeps(
        self,
        db: Session,
        symbol: str = "BTCUSDT",
        days_back: int = 30,
    ) -> ReplayResult:
        """
        Replay liquidity sweep archive.
        Analyze sweep frequency, magnitude, and recovery behavior.
        """
        if not self.is_enabled():
            return self._disabled_result("liquidity_sweeps")

        since  = datetime.now(timezone.utc) - timedelta(days=days_back)
        events = db.query(LiquiditySweepEvent).filter(
            LiquiditySweepEvent.symbol      == symbol,
            LiquiditySweepEvent.observed_at >= since,
        ).order_by(LiquiditySweepEvent.observed_at.desc()).all()

        if not events:
            return ReplayResult(
                query_description="Liquidity sweep replay",
                total_events=0,
                time_range_start=since,
                time_range_end=datetime.now(timezone.utc),
                researcher_notes="No liquidity sweep events in this period.",
            )

        by_direction  = self._count_by(events, "sweep_direction")
        by_recovery   = self._count_by(events, "recovery_behavior")
        cont_count    = sum(1 for e in events if e.continuation_after_sweep)
        avg_magnitude = sum(e.sweep_magnitude_pct or 0 for e in events) / len(events)

        return ReplayResult(
            query_description=f"Liquidity sweep replay — {days_back}d",
            total_events=len(events),
            time_range_start=since,
            time_range_end=datetime.now(timezone.utc),
            summary={
                "by_direction":              by_direction,
                "by_recovery_behavior":      by_recovery,
                "continuation_after_count":  cont_count,
                "continuation_rate":         round(cont_count / len(events), 3),
                "avg_magnitude_pct":         round(avg_magnitude, 3),
            },
            researcher_notes=(
                f"Of {len(events)} sweeps: {cont_count} continued in sweep direction "
                f"({cont_count/len(events)*100:.0f}%), "
                f"{len(events)-cont_count} reversed."
            ),
        )

    def compare_pattern_persistence(
        self,
        db: Session,
        symbol: str = "BTCUSDT",
        min_occurrences: int = 3,
    ) -> ReplayResult:
        """
        Compare behavioral pattern outcomes from the pattern_outcomes archive.
        Surface patterns with the most observations for research.
        """
        if not self.is_enabled():
            return self._disabled_result("pattern_persistence")

        patterns = db.query(PatternOutcome).filter(
            PatternOutcome.symbol          == symbol,
            PatternOutcome.total_occurrences >= min_occurrences,
        ).order_by(PatternOutcome.total_occurrences.desc()).limit(20).all()

        if not patterns:
            return ReplayResult(
                query_description="Pattern persistence comparison",
                total_events=0,
                time_range_start=None,
                time_range_end=datetime.now(timezone.utc),
                researcher_notes=(
                    f"No patterns with >= {min_occurrences} occurrences yet. "
                    "Archive building."
                ),
            )

        observations = []
        for p in patterns:
            observations.append({
                "structure_type":       p.structure_type,
                "boundary":             p.boundary,
                "total_occurrences":    p.total_occurrences,
                "bounce_count":         p.bounce_count,
                "break_count":          p.break_count,
                "behavioral_character": self._behavioral_character(p.bounce_rate),
                "conditions": {
                    "momentum_decaying":     p.momentum_decaying,
                    "aggression_weakening":  p.aggression_weakening,
                    "absorption_visible":    p.absorption_visible,
                    "rejection_candle":      p.rejection_candle,
                    "prior_sweep":           p.prior_sweep,
                    "volatility_state":      p.volatility_state,
                },
            })

        return ReplayResult(
            query_description="Pattern persistence comparison",
            total_events=sum(p.total_occurrences for p in patterns),
            time_range_start=None,
            time_range_end=datetime.now(timezone.utc),
            summary={"patterns_analyzed": len(patterns)},
            observations=observations,
            researcher_notes=(
                f"Analyzed {len(patterns)} behavioral patterns "
                f"with >= {min_occurrences} occurrences."
            ),
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _count_by(self, events: list, field: str) -> dict:
        counts: dict[str, int] = {}
        for e in events:
            val = str(getattr(e, field, "unknown"))
            counts[val] = counts.get(val, 0) + 1
        return counts

    def _behavioral_character(self, bounce_rate: float) -> str:
        """Describe pattern character — no percentages, no predictions."""
        if bounce_rate >= 0.75:
            return "historically strong boundary persistence"
        if bounce_rate >= 0.55:
            return "mixed boundary behavior"
        if bounce_rate >= 0.35:
            return "historically weak boundary persistence"
        return "historically frequent boundary failure"

    def _fake_breakout_notes(
        self, events: list, by_dir: dict, by_speed: dict
    ) -> str:
        dominant_dir   = max(by_dir,   key=by_dir.get,   default="unknown")
        dominant_speed = max(by_speed, key=by_speed.get, default="unknown")
        return (
            f"Most fake breakouts observed in {dominant_dir} direction. "
            f"Dominant rejection speed: {dominant_speed}. "
            f"Archive covers {len(events)} events."
        )

    def _disabled_result(self, query: str) -> ReplayResult:
        return ReplayResult(
            query_description=query,
            total_events=0,
            time_range_start=None,
            time_range_end=None,
            researcher_notes=(
                "Sandbox is disabled. "
                "Set REFLEX_SANDBOX_ENABLED=true in Railway ENV to enable."
            ),
        )
