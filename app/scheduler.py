"""
BTC Reflex Engine — Scheduler

Drives the observation cycle.
Polls on candle-close intervals (4H and 1H).

Phase 1: Observer mode only.
No execution. No exchange connections. Observation and alerting only.
"""
from __future__ import annotations
import logging
import time
import schedule
from datetime import datetime, timezone

from app.config import settings
from app.data.binance_feed import get_market_snapshot
from app.engines.structure_engine import StructureEngine
from app.engines.rotation_engine import RotationEngine
from app.engines.choch_engine import CHoCHEngine
from app.engines.volatility_engine import VolatilityEngine
from app.engines.context_assembler import BehavioralContextAssembler
# Brain reader removed — W22 architecture correction
from app.notifiers.telegram_reflex_bot import send_observation, send_error_alert
from app.notifiers import alert_gate
from app.database.db import get_db
from app.database.models import TacticalObservation
from app.database.memory_layer import MemoryLayer
from app.database.extended_memory import ExtendedMemoryWriter
from app.monitor import runtime_state
from app.journal.reflex_journal_exporter import ReflexJournalExporter  # Sprint 3A
from app.engines.composite_breakdown_detector import CompositeBreakdownDetector  # Sprint 3B-P1

logger = logging.getLogger(__name__)

# Engine instances (stateless — safe to reuse)
_structure_engine = StructureEngine(swing_lookback=settings.swing_lookback)
_rotation_engine = RotationEngine()
_choch_engine = CHoCHEngine(swing_lookback=settings.swing_lookback)
_volatility_engine = VolatilityEngine()
_assembler = BehavioralContextAssembler()
_memory  = MemoryLayer()
_ext_mem = ExtendedMemoryWriter()
_journal_exporter = ReflexJournalExporter()  # Sprint 3A
_breakdown_detector = CompositeBreakdownDetector(          # Sprint 3B-P1
    cooldown_secs        = settings.breakdown_cooldown_secs,
    signals_watch        = settings.breakdown_signals_watch,
    signals_high         = settings.breakdown_signals_high,
    volume_expansion_min = settings.breakdown_volume_expansion_min,
)


def run_observation_cycle() -> None:
    """
    One full Reflex observation cycle.

    Steps:
      1. Fetch market data (Binance)
      2. [REMOVED] Brain Ops context — W22 architecture correction
      3. Run all behavioral engines
      4. Update memory layer (structure lifecycle + boundary touches)
      5. Resolve pending outcomes from prior touches
      6. Build memory context for narrative enrichment
      7. Assemble behavioral context + narrative
      8. Log to database
      8a. Reflex Observation Journal export — Sprint 3A
      8b. Composite Breakdown Detector — Sprint 3B-P1
      9. Send Telegram alert if weight >= threshold
    """
    cycle_start = datetime.now(timezone.utc)
    logger.info("[scheduler] ── Observation cycle started %s ──", cycle_start.isoformat())

    try:
        # ── 1. Market Data ────────────────────────────────────────────────────
        snapshot = get_market_snapshot(settings.symbol)
        candles_4h = snapshot["candles_4h"]
        candles_1h = snapshot["candles_1h"]
        current_price = snapshot["current_price"]

        if not candles_4h or not candles_1h:
            logger.warning("[scheduler] Empty candle data — skipping cycle.")
            return

        # Brain Ops context removed — W22 (Reflex is fully independent)

        # ── 3. Behavioral Engines ─────────────────────────────────────────────
        structure_4h = _structure_engine.analyze(candles_4h, timeframe="4H")
        structure_1h = _structure_engine.analyze(candles_1h, timeframe="1H")
        rotation    = _rotation_engine.analyze(candles_1h, structure_4h, current_price)
        choch       = _choch_engine.analyze(candles_1h, timeframe="1H")
        volatility  = _volatility_engine.analyze(candles_4h, timeframe="4H")

        # ── 4 & 5 & 6. Memory Layer ───────────────────────────────────────────
        memory_ctx = {}
        with get_db() as db:
            # Update structure lifecycle — is this structure new or continuing?
            structure_mem = _memory.update_structure_lifecycle(
                db, settings.symbol, "4H", structure_4h, current_price or 0.0
            )

            # Record boundary touch if price is at a boundary
            if rotation.boundary != "none":
                _memory.record_boundary_touch(
                    db, settings.symbol, "4H",
                    structure_mem, rotation, volatility,
                    current_price or 0.0
                )

            # Resolve outcomes for touches that are old enough
            resolved = _memory.resolve_pending_outcomes(
                db, settings.symbol, candles_4h
            )
            if resolved:
                logger.info("[scheduler] Resolved %d pending outcomes.", resolved)

            # Build memory context for narrative
            memory_ctx = _memory.get_memory_context(
                db, settings.symbol, "4H", structure_4h, rotation
            )

            # ── Phase 2: Extended observational archives ───────────────────
            # Detect and record behavioral events — append-only, never modifies
            # production state, never influences live behavior.
            _ext_mem.detect_and_record_fake_breakout(
                db, settings.symbol, "4H", candles_4h,
                structure_4h, volatility
            )
            _ext_mem.detect_and_record_liquidity_sweep(
                db, settings.symbol, "4H", candles_4h,
                rotation, volatility, structure_4h
            )
            _ext_mem.detect_and_record_volatility_trap(
                db, settings.symbol, "4H", candles_4h,
                volatility, structure_4h
            )
            _ext_mem.detect_and_record_failed_continuation(
                db, settings.symbol, "4H", candles_4h,
                choch, structure_4h, volatility
            )

        # ── 7. Assemble Behavioral Context ────────────────────────────────────
        context = _assembler.assemble(
            symbol=settings.symbol,
            structure_4h=structure_4h,
            structure_1h=structure_1h,
            rotation=rotation,
            choch=choch,
            volatility=volatility,
            current_price=current_price,
            memory_ctx=memory_ctx,
        )

        # ── 8. Log to Database ────────────────────────────────────────────────
        _log_observation(context, current_price)

        # ── 8a. Reflex Observation Journal — Sprint 3A ────────────────────────
        # Independent of alert gate. Evaluates C1/C2 triggers directly on context.
        # Failure never propagates — exporter contains its own error boundary.
        _journal_exporter.maybe_export(context)

        # ── 8b. Composite Breakdown Detector — Sprint 3B-P1 ──────────────────
        # Pure evaluation: BehavioralContext → BreakdownResult.
        # Detector owns NO actions. Scheduler owns surfacing decisions.
        # Failure never propagates — detector contains its own error boundary.
        _breakdown_result = _breakdown_detector.evaluate(context)
        if _breakdown_result.fired:
            _surface_breakdown_alert(_breakdown_result)

        # ── 9. Alert Gate — event-driven, no spam ─────────────────────────────
        # All Telegram decisions go through alert_gate.
        # Heartbeat / unchanged state / low weight → Railway log only.
        # Only meaningful state changes or HIGH priority → Telegram.
        decision = alert_gate.evaluate(context)

        logger.info(
            "[scheduler] Gate: priority=%s send=%s | %s",
            decision.priority, decision.should_send, decision.reason
        )

        if decision.should_send:
            # Use compact persistence narrative for reminders
            # Full narrative for all other alerts
            if decision.is_persistence_reminder:
                from app.notifiers.telegram_reflex_bot import send_raw
                reminder_text = alert_gate.build_persistence_narrative(context)
                sent = send_raw(reminder_text)
            else:
                sent = send_observation(context)

            if sent:
                alert_gate.record_sent(context, is_reminder=decision.is_persistence_reminder)
                logger.info(
                    "[scheduler] Alert delivered (priority=%s weight=%.2f reminder=%s)",
                    decision.priority, context.behavioral_weight,
                    decision.is_persistence_reminder,
                )
        else:
            # Heartbeat — Railway log only, never Telegram
            price_str = f"{current_price:,.2f}" if current_price else "unknown"
            logger.info(
                "[HEARTBEAT] price=%s structure=%s phase=%s weight=%.2f | %s",
                price_str,
                context.structure_4h.structure_type,
                context.structure_4h.phase,
                context.behavioral_weight,
                decision.reason,
            )

        elapsed = (datetime.now(timezone.utc) - cycle_start).total_seconds()
        logger.info("[scheduler] ── Cycle complete in %.1fs ──", elapsed)

        # Update monitor runtime state — non-blocking, never affects cycle
        try:
            runtime_state.update_after_cycle(
                success         = True,
                cycle_secs      = elapsed,
                structure_type  = context.structure_4h.structure_type,
                structure_phase = context.structure_4h.phase,
                location        = context.structure_4h.location,
                volatility      = context.volatility.state,
                weight          = context.behavioral_weight,
                price           = current_price,
                choch_detected  = context.choch.choch_detected,
                alert_priority  = decision.priority,
                brain_source    = "disabled",  # Brain removed W22
            )
            _update_memory_counts()
        except Exception as state_exc:
            logger.debug("[scheduler] runtime_state update skipped: %s", state_exc)

    except Exception as exc:
        logger.exception("[scheduler] Cycle failed: %s", exc)
        try:
            runtime_state.update_after_cycle(
                success=False, cycle_secs=0, structure_type="unknown",
                structure_phase="unknown", location="unknown",
                volatility="unknown", weight=0.0, price=None,
                choch_detected=False, alert_priority="LOW",
                brain_source="disabled",
            )
        except Exception:
            pass
        send_error_alert(f"Reflex cycle error: {exc}")


def _surface_breakdown_alert(result) -> None:
    """
    Surface a fired BreakdownResult to Telegram.

    The detector owns evaluation only.
    This function owns the surfacing decision — keeping them separate
    means the detector can be tested and replaced without touching I/O.

    Observer mode only. Never modifies Signal Bot state.
    Failure here never affects scheduler, alert gate, or DB writes.
    """
    try:
        from app.notifiers.telegram_reflex_bot import send_raw
        sent = send_raw(result.narrative)
        if sent:
            logger.info(
                "[breakdown] surfaced | level=%s signals=%d weight=%.3f",
                result.level,
                result.signals.bearish_count,
                result.weight,
            )
        else:
            logger.warning(
                "[breakdown] narrative not delivered (Telegram returned False) "
                "level=%s", result.level
            )
    except Exception as exc:
        logger.error(
            "[breakdown] surface failed (non-fatal): %s", exc
        )


def _update_memory_counts() -> None:
    """Pull memory record counts and push to runtime state for monitor."""
    try:
        from app.database.models import (
            StructureMemory, BoundaryTouchLog, PatternOutcome,
            FakeBreakoutEvent, LiquiditySweepEvent,
        )
        with get_db() as db:
            runtime_state.update_memory_counts(
                structure_records     = db.query(StructureMemory).count(),
                touch_records         = db.query(BoundaryTouchLog).count(),
                pattern_records       = db.query(PatternOutcome).count(),
                fake_breakout_records = db.query(FakeBreakoutEvent).count(),
                sweep_records         = db.query(LiquiditySweepEvent).count(),
            )
    except Exception as exc:
        logger.debug("[scheduler] memory count update skipped: %s", exc)


def _log_observation(context, current_price: float | None) -> None:
    """Persist the observation to the Reflex database."""
    try:
        with get_db() as db:
            obs = TacticalObservation(
                symbol=context.symbol,
                mode=settings.mode,

                # Brain context removed — W22 (stop writing to these columns)
                brain_market_regime="disabled",
                brain_macro_bias="disabled",
                brain_confidence=0.0,
                brain_continuation_state="disabled",
                brain_volatility_state="disabled",
                brain_risk_mode="disabled",
                brain_source="disabled",

                # 4H structure
                structure_4h_type=context.structure_4h.structure_type,
                structure_4h_phase=context.structure_4h.phase,
                structure_4h_location=context.structure_4h.location,
                structure_4h_quality=context.structure_4h.structure_quality,

                # 1H structure
                structure_1h_type=context.structure_1h.structure_type,
                structure_1h_phase=context.structure_1h.phase,
                structure_1h_location=context.structure_1h.location,

                # Rotation
                rotation_boundary=context.rotation.boundary,
                rotation_weight=context.rotation.rotation_weight,
                momentum_decaying=context.rotation.momentum_decaying,

                # CHoCH
                choch_detected=context.choch.choch_detected,
                choch_direction=context.choch.choch_direction,

                # Volatility
                volatility_state=context.volatility.state,
                compression_score=context.volatility.compression_score,
                expansion_score=context.volatility.expansion_score,

                # Overall
                behavioral_weight=context.behavioral_weight,
                alert_sent=context.alert_worthy,
                narrative=context.narrative,
            )
            db.add(obs)
        logger.debug("[scheduler] Observation logged to DB.")
    except Exception as exc:
        logger.error("[scheduler] DB log failed: %s", exc)


def start_scheduler() -> None:
    """
    Start the observation scheduler.

    Runs an observation cycle every hour (configurable).
    All cycles are observer-mode only in Phase 1.
    """
    logger.info(
        "[scheduler] Starting BTC Reflex Engine | mode=%s | symbol=%s",
        settings.mode, settings.symbol
    )

    # Run immediately on startup
    run_observation_cycle()

    # Schedule recurring cycles
    interval_minutes = settings.poll_interval_1h // 60
    schedule.every(interval_minutes).minutes.do(run_observation_cycle)

    logger.info(
        "[scheduler] Scheduled every %d minutes. Running...", interval_minutes
    )

    while True:
        schedule.run_pending()
        time.sleep(30)
