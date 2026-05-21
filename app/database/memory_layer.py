"""
BTC Reflex Engine — Memory Layer

Tracks structural memory across observation cycles.
This is what separates a system that "sees" from one that "remembers."

Three responsibilities:

1. Structure Lifecycle Tracking
   - Detect when a structure is new vs ongoing
   - Count how many cycles it has persisted
   - Track boundary touches and their outcomes

2. Boundary Touch Logging
   - Record every boundary interaction with full behavioral context
   - Schedule outcome resolution 4 candles later

3. Outcome Resolution
   - After each touch, check what actually happened
   - Bounce, break, or neutral?
   - Feed results into PatternOutcomes for long-term learning

PHILOSOPHY:
  Memory is not about predicting the future.
  It's about knowing what THIS structure has done before
  so the current observation has historical depth.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.database.models import (
    StructureMemory,
    BoundaryTouchLog,
    PatternOutcome,
)
from app.engines.structure_engine import StructureState
from app.engines.rotation_engine import RotationObservation
from app.engines.volatility_engine import VolatilityState

logger = logging.getLogger(__name__)

# How similar do boundaries need to be to count as "same structure"?
# 2% tolerance — if boundaries shift less than this, it's the same structure
_BOUNDARY_TOLERANCE_PCT = 0.02

# How many candles after a touch before we resolve the outcome?
_OUTCOME_RESOLUTION_CANDLES = 4

# Minimum price move to call it a "bounce" or "break" (not neutral)
_OUTCOME_MOVE_THRESHOLD_PCT = 0.008   # 0.8%


class MemoryLayer:
    """
    Manages all memory operations for one observation cycle.

    Called from the scheduler after engines run,
    before the context assembler builds the narrative.
    """

    # ── Structure Lifecycle ───────────────────────────────────────────────────

    def update_structure_lifecycle(
        self,
        db: Session,
        symbol: str,
        timeframe: str,
        structure: StructureState,
        current_price: float,
    ) -> StructureMemory:
        """
        Find the active structure memory for this symbol/timeframe,
        or create a new one if structure has changed.

        Returns the current (possibly new) StructureMemory record.
        """
        active = self._get_active_structure(db, symbol, timeframe)

        if active and self._is_same_structure(active, structure):
            # Structure continues — update lifecycle counters
            # Guard against None from DB reads (schema migration safety)
            active.last_seen_at = datetime.now(timezone.utc)
            active.candles_alive = (active.candles_alive or 0) + 1
            logger.debug(
                "[memory] Structure continues: %s %s | age=%d candles",
                timeframe, active.structure_type, active.candles_alive
            )
            return active

        # Structure changed — close old, open new
        if active:
            self._close_structure(db, active, reason="dissolved")
            logger.info(
                "[memory] Structure ended: %s → %s",
                active.structure_type, structure.structure_type
            )

        new_mem = StructureMemory(
            symbol=symbol,
            timeframe=timeframe,
            structure_type=structure.structure_type,
            upper_boundary=structure.upper_boundary,
            lower_boundary=structure.lower_boundary,
            first_seen_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
            candles_alive=1,
            is_active=True,
        )
        db.add(new_mem)
        db.flush()   # get the id before returning

        logger.info(
            "[memory] New structure: %s %s | upper=%.2f lower=%.2f",
            timeframe, structure.structure_type,
            structure.upper_boundary or 0,
            structure.lower_boundary or 0,
        )
        return new_mem

    def record_boundary_touch(
        self,
        db: Session,
        symbol: str,
        timeframe: str,
        structure_mem: StructureMemory,
        rotation: RotationObservation,
        volatility: VolatilityState,
        current_price: float,
    ) -> Optional[BoundaryTouchLog]:
        """
        Record a boundary touch event when rotation engine detects
        price is at a boundary.

        Only records if rotation.boundary != "none".
        """
        if rotation.boundary == "none":
            return None

        # Increment touch counter on structure memory
        boundary_price = (
            structure_mem.upper_boundary
            if rotation.boundary == "upper"
            else structure_mem.lower_boundary
        )
        if boundary_price is None:
            return None

        # Which touch number is this?
        # Guard against None — SQLAlchemy may return None for default=0 columns
        # if the row was written before the column existed.
        if rotation.boundary == "lower":
            structure_mem.lower_touches = (structure_mem.lower_touches or 0) + 1
            touch_number = structure_mem.lower_touches
        else:
            structure_mem.upper_touches = (structure_mem.upper_touches or 0) + 1
            touch_number = structure_mem.upper_touches

        touch = BoundaryTouchLog(
            symbol=symbol,
            timeframe=timeframe,
            touched_at=datetime.now(timezone.utc),
            structure_memory_id=structure_mem.id,
            structure_type=structure_mem.structure_type,
            boundary=rotation.boundary,
            boundary_price=boundary_price,
            touch_price=current_price,
            touch_number=touch_number,

            # Behavioral context snapshot
            momentum_decaying=rotation.momentum_decaying,
            aggression_weakening=rotation.aggression_weakening,
            absorption_visible=rotation.absorption_visible,
            rejection_candle=rotation.rejection_candle,
            prior_sweep=rotation.prior_sweep,
            rotation_weight=rotation.rotation_weight,
            volatility_state=volatility.state,
            compression_score=volatility.compression_score,

            outcome_resolved=False,
        )
        db.add(touch)

        logger.info(
            "[memory] Boundary touch #%d recorded: %s %s | weight=%.2f",
            touch_number, rotation.boundary, structure_mem.structure_type,
            rotation.rotation_weight
        )
        return touch

    # ── Outcome Resolution ────────────────────────────────────────────────────

    def resolve_pending_outcomes(
        self,
        db: Session,
        symbol: str,
        candles: list[dict],
    ) -> int:
        """
        Check all unresolved boundary touches and determine outcome.

        Called every cycle. Looks at touches that are old enough
        (_OUTCOME_RESOLUTION_CANDLES) and measures what price did
        after the touch.

        Returns number of outcomes resolved this cycle.
        """
        pending = (
            db.query(BoundaryTouchLog)
            .filter(
                BoundaryTouchLog.symbol == symbol,
                BoundaryTouchLog.outcome_resolved == False,
            )
            .all()
        )

        if not pending or not candles:
            return 0

        current_price = candles[-1]["close"]
        resolved = 0

        for touch in pending:
            # Check if enough candles have passed since the touch
            candles_since = self._estimate_candles_since(touch.touched_at, candles)
            if candles_since < _OUTCOME_RESOLUTION_CANDLES:
                continue

            # Measure the price move from touch to now
            price_change_pct = (current_price - touch.touch_price) / touch.touch_price

            # Classify outcome
            outcome = self._classify_outcome(
                price_change_pct, touch.boundary
            )

            touch.outcome_resolved = True
            touch.outcome_type = outcome
            touch.outcome_candles = candles_since
            touch.outcome_price_change_pct = round(price_change_pct * 100, 3)
            touch.outcome_resolved_at = datetime.now(timezone.utc)

            # Update structure memory bounce/break counters
            self._update_structure_outcome_counters(db, touch, outcome)

            # Update pattern outcome statistics
            self._update_pattern_outcomes(db, touch, outcome, price_change_pct)

            resolved += 1
            logger.info(
                "[memory] Outcome resolved: %s %s touch → %s (%.2f%%)",
                touch.boundary, touch.structure_type,
                outcome, price_change_pct * 100
            )

        return resolved

    # ── Memory Context Reader ─────────────────────────────────────────────────

    def get_memory_context(
        self,
        db: Session,
        symbol: str,
        timeframe: str,
        structure: StructureState,
        rotation: RotationObservation,
    ) -> dict:
        """
        Build the memory context dict that gets injected into the narrative.

        This is what adds behavioral depth to every observation.
        Not: "75% bounced → long"
        But: "This level has absorbed pressure across 3 tests without breaking —
        current interaction exists within an established defensive structure."
        Memory enriches context. It never replaces behavioral judgment.
        """
        ctx = {
            "structure_age_candles": 0,
            "lower_touches": 0,
            "upper_touches": 0,
            "lower_bounces": 0,
            "upper_bounces": 0,
            "lower_breaks": 0,
            "upper_breaks": 0,
            "last_touch_outcome": None,
            "last_touch_pct": None,
            "similar_pattern_count": 0,
            "similar_persistence_rate": None,
            "has_memory": False,
        }

        # Current structure memory
        active = self._get_active_structure(db, symbol, timeframe)
        if active:
            ctx["structure_age_candles"] = active.candles_alive
            ctx["lower_touches"] = active.lower_touches
            ctx["upper_touches"] = active.upper_touches
            ctx["lower_bounces"] = active.lower_bounces
            ctx["upper_bounces"] = active.upper_bounces
            ctx["lower_breaks"] = active.lower_breaks
            ctx["upper_breaks"] = active.upper_breaks
            ctx["has_memory"] = True

            # Last resolved touch on this boundary
            last_touch = self._get_last_resolved_touch(
                db, active.id, rotation.boundary
            )
            if last_touch:
                ctx["last_touch_outcome"] = last_touch.outcome_type
                ctx["last_touch_pct"] = last_touch.outcome_price_change_pct

        # Similar pattern historical stats
        if rotation.boundary != "none":
            pattern = self._get_pattern_outcome(db, symbol, structure, rotation)
            if pattern and pattern.total_occurrences >= 3:
                ctx["similar_pattern_count"] = pattern.total_occurrences
                ctx["similar_persistence_rate"] = round(pattern.bounce_rate * 100, 1)

        return ctx

    # ── Internal Helpers ──────────────────────────────────────────────────────

    def _get_active_structure(
        self, db: Session, symbol: str, timeframe: str
    ) -> Optional[StructureMemory]:
        return (
            db.query(StructureMemory)
            .filter(
                StructureMemory.symbol == symbol,
                StructureMemory.timeframe == timeframe,
                StructureMemory.is_active == True,
            )
            .order_by(StructureMemory.first_seen_at.desc())
            .first()
        )

    def _is_same_structure(
        self, mem: StructureMemory, structure: StructureState
    ) -> bool:
        """
        Same structure = same type + boundaries within tolerance.
        Allows slight boundary drift without creating a new structure record.
        """
        if mem.structure_type != structure.structure_type:
            return False
        if structure.upper_boundary is None or structure.lower_boundary is None:
            return False
        if mem.upper_boundary is None or mem.lower_boundary is None:
            return False

        upper_drift = abs(mem.upper_boundary - structure.upper_boundary) / mem.upper_boundary
        lower_drift = abs(mem.lower_boundary - structure.lower_boundary) / mem.lower_boundary

        return upper_drift < _BOUNDARY_TOLERANCE_PCT and lower_drift < _BOUNDARY_TOLERANCE_PCT

    def _close_structure(
        self, db: Session, mem: StructureMemory, reason: str
    ) -> None:
        mem.is_active = False
        mem.ended_at = datetime.now(timezone.utc)
        mem.end_reason = reason

    def _estimate_candles_since(
        self, touch_time: datetime, candles: list[dict]
    ) -> int:
        """
        Estimate how many candles have closed since the touch.
        Uses candle close_time timestamps from Binance data.
        """
        if not candles:
            return 0
        touch_ts = touch_time.timestamp() * 1000  # ms
        count = sum(1 for c in candles if c["close_time"] > touch_ts)
        return count

    def _classify_outcome(self, price_change_pct: float, boundary: str) -> str:
        """
        Classify what happened after a boundary touch.

        At lower boundary:
          bounce = price went UP by threshold
          break  = price went DOWN further by threshold
        At upper boundary:
          bounce = price went DOWN by threshold
          break  = price went UP further by threshold
        """
        threshold = _OUTCOME_MOVE_THRESHOLD_PCT
        if boundary == "lower":
            if price_change_pct >= threshold:
                return "bounce"
            if price_change_pct <= -threshold:
                return "break"
        else:
            if price_change_pct <= -threshold:
                return "bounce"
            if price_change_pct >= threshold:
                return "break"
        return "neutral"

    def _update_structure_outcome_counters(
        self, db: Session, touch: BoundaryTouchLog, outcome: str
    ) -> None:
        if not touch.structure_memory_id:
            return
        mem = db.query(StructureMemory).get(touch.structure_memory_id)
        if not mem:
            return
        if touch.boundary == "lower":
            if outcome == "bounce":
                mem.lower_bounces = (mem.lower_bounces or 0) + 1
            elif outcome == "break":
                mem.lower_breaks = (mem.lower_breaks or 0) + 1
                self._close_structure(db, mem, reason="lower_break")
        else:
            if outcome == "bounce":
                mem.upper_bounces = (mem.upper_bounces or 0) + 1
            elif outcome == "break":
                mem.upper_breaks = (mem.upper_breaks or 0) + 1
                self._close_structure(db, mem, reason="upper_break")

    def _update_pattern_outcomes(
        self,
        db: Session,
        touch: BoundaryTouchLog,
        outcome: str,
        price_change_pct: float,
    ) -> None:
        """
        Update the aggregated pattern outcome stats.
        Finds or creates the pattern record that matches
        this exact behavioral signature.
        """
        pattern = (
            db.query(PatternOutcome)
            .filter(
                PatternOutcome.symbol == touch.symbol,
                PatternOutcome.structure_type == touch.structure_type,
                PatternOutcome.boundary == touch.boundary,
                PatternOutcome.momentum_decaying == touch.momentum_decaying,
                PatternOutcome.aggression_weakening == touch.aggression_weakening,
                PatternOutcome.absorption_visible == touch.absorption_visible,
                PatternOutcome.rejection_candle == touch.rejection_candle,
                PatternOutcome.prior_sweep == touch.prior_sweep,
                PatternOutcome.volatility_state == touch.volatility_state,
            )
            .first()
        )

        if not pattern:
            pattern = PatternOutcome(
                symbol=touch.symbol,
                structure_type=touch.structure_type,
                boundary=touch.boundary,
                momentum_decaying=touch.momentum_decaying,
                aggression_weakening=touch.aggression_weakening,
                absorption_visible=touch.absorption_visible,
                rejection_candle=touch.rejection_candle,
                prior_sweep=touch.prior_sweep,
                volatility_state=touch.volatility_state,
            )
            db.add(pattern)

        # Guard all counter fields against None from DB reads
        pattern.total_occurrences = (pattern.total_occurrences or 0) + 1
        if outcome == "bounce":
            pattern.bounce_count = (pattern.bounce_count or 0) + 1
        elif outcome == "break":
            pattern.break_count = (pattern.break_count or 0) + 1
        else:
            pattern.neutral_count = (pattern.neutral_count or 0) + 1

        # Recalculate rates — guard against None denominators
        total = pattern.total_occurrences or 1
        pattern.bounce_rate = round((pattern.bounce_count or 0) / total, 4)
        pattern.break_rate  = round((pattern.break_count  or 0) / total, 4)

        # Running average of price change magnitude
        prev_avg = pattern.avg_price_change_pct or 0.0
        pattern.avg_price_change_pct = round(
            (prev_avg * (total - 1) + abs(price_change_pct) * 100) / total, 3
        )
        pattern.last_updated = datetime.now(timezone.utc)

    def _get_last_resolved_touch(
        self, db: Session, structure_memory_id: int, boundary: str
    ) -> Optional[BoundaryTouchLog]:
        if boundary == "none":
            return None
        return (
            db.query(BoundaryTouchLog)
            .filter(
                BoundaryTouchLog.structure_memory_id == structure_memory_id,
                BoundaryTouchLog.boundary == boundary,
                BoundaryTouchLog.outcome_resolved == True,
            )
            .order_by(BoundaryTouchLog.touched_at.desc())
            .first()
        )

    def _get_pattern_outcome(
        self,
        db: Session,
        symbol: str,
        structure: StructureState,
        rotation: RotationObservation,
    ) -> Optional[PatternOutcome]:
        return (
            db.query(PatternOutcome)
            .filter(
                PatternOutcome.symbol == symbol,
                PatternOutcome.structure_type == structure.structure_type,
                PatternOutcome.boundary == rotation.boundary,
                PatternOutcome.momentum_decaying == rotation.momentum_decaying,
                PatternOutcome.aggression_weakening == rotation.aggression_weakening,
                PatternOutcome.absorption_visible == rotation.absorption_visible,
                PatternOutcome.rejection_candle == rotation.rejection_candle,
                PatternOutcome.prior_sweep == rotation.prior_sweep,
            )
            .first()
        )
