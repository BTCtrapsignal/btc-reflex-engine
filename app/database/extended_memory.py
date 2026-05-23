"""
BTC Reflex Engine — Extended Memory Writer (Phase 2)

Detects and archives behavioral events from engine outputs.

PHILOSOPHY:
  This module OBSERVES and RECORDS — nothing else.
  It does not modify signals, confidence, or production behavior.
  It does not generate trade decisions.

  Every method in this module:
    - reads engine output
    - decides if a behavioral event occurred
    - writes one record to an archive table
    - returns nothing that influences live behavior

EVENTS TRACKED:
  - Fake breakout events
  - Liquidity sweep events
  - Volatility trap events
  - Failed continuation events

All detection is conservative — better to miss an event
than to misclassify and corrupt the archive.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.database.models import (
    FakeBreakoutEvent,
    LiquiditySweepEvent,
    VolatilityTrapEvent,
    FailedContinuationEvent,
)
from app.engines.structure_engine import StructureState
from app.engines.rotation_engine import RotationObservation
from app.engines.choch_engine import CHoCHState
from app.engines.volatility_engine import VolatilityState
from app.integrations.brain_reader import BrainState

logger = logging.getLogger(__name__)

# Detection thresholds
_FAKE_BREAKOUT_RETURN_CANDLES = 3    # price must return inside within this many candles
_SWEEP_MIN_MAGNITUDE_PCT      = 0.003 # minimum sweep size to record (0.3%)
_TRAP_MIN_COMPRESSION_STREAK  = 4    # candles of compression before a trap qualifies
_CONTINUATION_FAIL_CANDLES    = 5    # continuation must stall within this many candles


class ExtendedMemoryWriter:
    """
    Writes to Phase 2 observational archive tables.
    Called from the scheduler after every engine cycle.
    All methods are safe to call — they never raise, never modify live state.
    """

    # ── Fake Breakout Detection ───────────────────────────────────────────────

    def detect_and_record_fake_breakout(
        self,
        db: Session,
        symbol: str,
        timeframe: str,
        candles: list[dict],
        structure: StructureState,
        volatility: VolatilityState,
        brain: BrainState,
    ) -> Optional[FakeBreakoutEvent]:
        """
        Detect a fake breakout from recent candle behavior.

        Detection logic:
          A candle spiked beyond a structural boundary AND
          the close is back inside the structure.
          This is the behavioral signature of a fake breakout.
        """
        try:
            if (
                not candles
                or structure.upper_boundary is None
                or structure.lower_boundary is None
                or len(candles) < 3
            ):
                return None

            upper = structure.upper_boundary
            lower = structure.lower_boundary
            rng   = upper - lower
            if rng <= 0:
                return None

            # Check recent candles for spike-beyond + return pattern
            for i in range(min(3, len(candles) - 1), 0, -1):
                c    = candles[-i]
                prev = candles[-i - 1]

                # Upper fake breakout: wick above upper, close back inside
                if c["high"] > upper and c["close"] < upper:
                    magnitude = (c["high"] - upper) / upper * 100
                    candles_outside = self._count_candles_outside(
                        candles[-i:], upper, lower, "up"
                    )
                    event = FakeBreakoutEvent(
                        observed_at         = datetime.now(timezone.utc),
                        symbol              = symbol,
                        timeframe           = timeframe,
                        breakout_direction  = "up",
                        breakout_level      = round(upper, 2),
                        breakout_magnitude_pct = round(magnitude, 3),
                        rejection_speed     = self._rejection_speed(candles_outside),
                        candles_outside     = candles_outside,
                        volatility_state    = volatility.state,
                        structure_type      = structure.structure_type,
                        structure_phase     = structure.phase,
                        regime_context      = brain.market_regime,
                        liquidity_behavior  = "sweep_then_reverse",
                    )
                    db.add(event)
                    logger.info(
                        "[ext_memory] Fake breakout UP recorded: level=%.2f mag=%.2f%%",
                        upper, magnitude
                    )
                    return event

                # Lower fake breakout: wick below lower, close back inside
                if c["low"] < lower and c["close"] > lower:
                    magnitude = (lower - c["low"]) / lower * 100
                    candles_outside = self._count_candles_outside(
                        candles[-i:], upper, lower, "down"
                    )
                    event = FakeBreakoutEvent(
                        observed_at         = datetime.now(timezone.utc),
                        symbol              = symbol,
                        timeframe           = timeframe,
                        breakout_direction  = "down",
                        breakout_level      = round(lower, 2),
                        breakout_magnitude_pct = round(magnitude, 3),
                        rejection_speed     = self._rejection_speed(candles_outside),
                        candles_outside     = candles_outside,
                        volatility_state    = volatility.state,
                        structure_type      = structure.structure_type,
                        structure_phase     = structure.phase,
                        regime_context      = brain.market_regime,
                        liquidity_behavior  = "sweep_then_reverse",
                    )
                    db.add(event)
                    logger.info(
                        "[ext_memory] Fake breakout DOWN recorded: level=%.2f mag=%.2f%%",
                        lower, magnitude
                    )
                    return event

            return None

        except Exception as exc:
            logger.error("[ext_memory] fake_breakout detection error: %s", exc)
            return None

    # ── Liquidity Sweep Detection ─────────────────────────────────────────────

    def detect_and_record_liquidity_sweep(
        self,
        db: Session,
        symbol: str,
        timeframe: str,
        candles: list[dict],
        rotation: RotationObservation,
        volatility: VolatilityState,
        brain: BrainState,
        structure: StructureState,
    ) -> Optional[LiquiditySweepEvent]:
        """
        Detect a liquidity sweep from rotation engine's prior_sweep signal.
        Records only if sweep magnitude meets minimum threshold.
        """
        try:
            if not rotation.prior_sweep or not candles:
                return None
            if structure.upper_boundary is None or structure.lower_boundary is None:
                return None

            upper = structure.upper_boundary
            lower = structure.lower_boundary
            price = candles[-1]["close"]

            # Determine sweep direction from current boundary
            if rotation.boundary == "lower":
                sweep_level = lower
                sweep_direction = "down"
                magnitude = abs(min(c["low"] for c in candles[-5:]) - lower) / lower * 100
                recovery_pct = (price - sweep_level) / sweep_level * 100
            else:
                sweep_level = upper
                sweep_direction = "up"
                magnitude = abs(max(c["high"] for c in candles[-5:]) - upper) / upper * 100
                recovery_pct = (sweep_level - price) / sweep_level * 100

            if magnitude < _SWEEP_MIN_MAGNITUDE_PCT * 100:
                return None

            event = LiquiditySweepEvent(
                observed_at          = datetime.now(timezone.utc),
                symbol               = symbol,
                timeframe            = timeframe,
                sweep_direction      = sweep_direction,
                sweep_level          = round(sweep_level, 2),
                sweep_magnitude_pct  = round(magnitude, 3),
                recovery_behavior    = "reversed_slowly" if not rotation.rejection_candle else "reversed_strongly",
                candles_to_recovery  = 3,  # approximate from prior_sweep lookback
                recovery_pct         = round(recovery_pct, 3),
                continuation_after_sweep = False,  # resolved on next cycle
                volatility_state     = volatility.state,
                structure_type       = structure.structure_type,
                regime_context       = brain.market_regime,
            )
            db.add(event)
            logger.info(
                "[ext_memory] Liquidity sweep %s recorded: level=%.2f mag=%.3f%%",
                sweep_direction, sweep_level, magnitude
            )
            return event

        except Exception as exc:
            logger.error("[ext_memory] sweep detection error: %s", exc)
            return None

    # ── Volatility Trap Detection ─────────────────────────────────────────────

    def detect_and_record_volatility_trap(
        self,
        db: Session,
        symbol: str,
        timeframe: str,
        candles: list[dict],
        volatility: VolatilityState,
        structure: StructureState,
        brain: BrainState,
    ) -> Optional[VolatilityTrapEvent]:
        """
        Detect a volatility trap:
          Was compression building (streak >= threshold)?
          Did expansion attempt fail (current ATR ratio < prior compression)?

        Conservative detection — only records clear traps.
        """
        try:
            if not candles or len(candles) < 10:
                return None

            # Trap condition: had meaningful compression streak
            # AND current volatility is not actually expanding
            streak = volatility.candles_compressing
            if streak < _TRAP_MIN_COMPRESSION_STREAK:
                return None

            # Trap: compression streak built up but NOT followed by expansion
            if volatility.state in ("normal", "compressing", "compressed"):
                # Check if recent candle tried to expand then failed
                if len(candles) >= 3:
                    recent_ranges = [c["high"] - c["low"] for c in candles[-3:]]
                    # Attempted expansion: middle candle larger, latest smaller
                    if recent_ranges[1] > recent_ranges[0] * 1.3 and recent_ranges[2] < recent_ranges[1] * 0.8:
                        trap_dir = "up" if candles[-2]["close"] > candles[-2]["open"] else "down"
                        max_exp  = recent_ranges[1] / (candles[-2]["close"] + 1e-9) * 100

                        event = VolatilityTrapEvent(
                            observed_at              = datetime.now(timezone.utc),
                            symbol                   = symbol,
                            timeframe                = timeframe,
                            pre_trap_volatility      = "compressing",
                            pre_trap_atr_ratio       = round(volatility.atr_ratio, 4),
                            compression_streak_candles = streak,
                            trap_direction           = trap_dir,
                            failed_expansion_type    = "immediate_reversal",
                            max_expansion_pct        = round(max_exp, 3),
                            recovery_type            = "returned_to_range",
                            duration_candles         = 2,
                            structure_type           = structure.structure_type,
                            regime_context           = brain.market_regime,
                        )
                        db.add(event)
                        logger.info(
                            "[ext_memory] Volatility trap recorded: streak=%d dir=%s",
                            streak, trap_dir
                        )
                        return event

            return None

        except Exception as exc:
            logger.error("[ext_memory] volatility_trap detection error: %s", exc)
            return None

    # ── Failed Continuation Detection ─────────────────────────────────────────

    def detect_and_record_failed_continuation(
        self,
        db: Session,
        symbol: str,
        timeframe: str,
        candles: list[dict],
        choch: CHoCHState,
        structure: StructureState,
        volatility: VolatilityState,
        brain: BrainState,
    ) -> Optional[FailedContinuationEvent]:
        """
        Detect a failed continuation:
          CHoCH after a prior directional phase suggests
          the continuation attempt broke down.

        Only records when CHoCH is detected with meaningful conviction.
        """
        try:
            if not choch.choch_detected or choch.conviction < 0.25:
                return None
            if not candles:
                return None

            # Direction that was expected to continue (opposite of CHoCH shift)
            if choch.choch_direction == "bearish_shift":
                expected = "up"   # bullish continuation that failed
            elif choch.choch_direction == "bullish_shift":
                expected = "down"  # bearish continuation that failed
            else:
                return None

            event = FailedContinuationEvent(
                observed_at                 = datetime.now(timezone.utc),
                symbol                      = symbol,
                timeframe                   = timeframe,
                expected_direction          = expected,
                continuation_failure_speed  = self._failure_speed(choch.conviction),
                candles_before_failure      = _CONTINUATION_FAIL_CANDLES,
                choch_after_failure         = True,
                volatility_shift            = volatility.state in ("expanding", "elevated"),
                structure_transition        = structure.phase,
                volatility_state            = volatility.state,
                structure_type              = structure.structure_type,
                regime_context              = brain.market_regime,
                brain_continuation_state    = brain.continuation_state,
            )
            db.add(event)
            logger.info(
                "[ext_memory] Failed continuation recorded: expected=%s choch=%s conviction=%.2f",
                expected, choch.choch_direction, choch.conviction
            )
            return event

        except Exception as exc:
            logger.error("[ext_memory] failed_continuation detection error: %s", exc)
            return None

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _rejection_speed(self, candles_outside: int) -> str:
        if candles_outside <= 1:  return "immediate"
        if candles_outside <= 3:  return "fast"
        return "slow"

    def _failure_speed(self, conviction: float) -> str:
        if conviction >= 0.7:  return "immediate"
        if conviction >= 0.4:  return "fast"
        return "gradual"

    def _count_candles_outside(
        self,
        candles: list[dict],
        upper: float,
        lower: float,
        direction: str,
    ) -> int:
        count = 0
        for c in candles:
            if direction == "up" and c["close"] > upper:
                count += 1
            elif direction == "down" and c["close"] < lower:
                count += 1
            else:
                break
        return max(count, 1)
