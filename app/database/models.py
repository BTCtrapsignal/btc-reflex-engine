"""
BTC Reflex Engine — Database Models
Completely separate from BTC Brain Ops schema.
Never references Brain Ops tables.
"""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import (
    Column, Integer, Float, String, Boolean,
    DateTime, Text, create_engine
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.config import settings


# ── Engine + Session ─────────────────────────────────────────────────────────

engine = create_engine(
    settings.reflex_database_url,
    connect_args={"check_same_thread": False}
    if "sqlite" in settings.reflex_database_url else {},
    echo=False,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


# ── Models ───────────────────────────────────────────────────────────────────

class StructureSnapshot(Base):
    """
    Records the structural state of BTC at a given timeframe and time.
    Captures behavioral context — not trade signals.
    """
    __tablename__ = "structure_snapshots"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    symbol = Column(String(20), default="BTCUSDT")
    timeframe = Column(String(10))            # "4H", "1H"

    # Structure type observed
    structure_type = Column(String(50))       # "descending_wedge", "range", "ascending_triangle", etc.
    phase = Column(String(50))                # "compression", "expansion", "bouncing", "breakout"
    location = Column(String(50))             # "at_lower_boundary", "at_upper_boundary", "mid_range"

    # Key price levels
    upper_boundary = Column(Float, nullable=True)
    lower_boundary = Column(Float, nullable=True)
    current_price = Column(Float, nullable=True)
    range_width_pct = Column(Float, nullable=True)  # structure width as % of price

    # Behavioral quality (0.0–1.0) — not a trade score, a structure clarity measure
    structure_quality = Column(Float, default=0.0)

    # Free-form behavioral notes
    notes = Column(Text, default="")


class CHoCHEvent(Base):
    """
    Records a detected Change of Character in market structure.
    A CHoCH is a behavioral shift — not a trade signal.
    """
    __tablename__ = "choch_events"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    symbol = Column(String(20), default="BTCUSDT")
    timeframe = Column(String(10))

    # What changed
    previous_character = Column(String(50))   # "bullish_swing_sequence", "bearish_swing_sequence"
    new_character = Column(String(50))         # "bearish_shift", "bullish_shift"
    trigger_price = Column(Float, nullable=True)

    # Confidence in the CHoCH observation (0.0–1.0)
    confidence = Column(Float, default=0.0)
    notes = Column(Text, default="")


class LiquidityEvent(Base):
    """
    Records observed liquidity behavior: sweeps, fake breakouts, trapped traders.
    Behavioral observation only.
    """
    __tablename__ = "liquidity_events"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    symbol = Column(String(20), default="BTCUSDT")
    timeframe = Column(String(10))

    event_type = Column(String(50))           # "sweep", "fake_breakout", "trapped_longs", "trapped_shorts"
    level_swept = Column(Float, nullable=True)
    follow_through = Column(Boolean, default=False)
    reversal_observed = Column(Boolean, default=False)
    notes = Column(Text, default="")


class RotationObservation(Base):
    """
    Records a boundary rotation observation.
    Captures behavioral context around structure boundary interactions.
    """
    __tablename__ = "rotation_observations"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    symbol = Column(String(20), default="BTCUSDT")
    timeframe = Column(String(10))

    boundary = Column(String(20))             # "lower", "upper"
    current_price = Column(Float, nullable=True)
    boundary_price = Column(Float, nullable=True)
    proximity_pct = Column(Float, nullable=True)   # % distance from boundary

    # Behavioral observations at boundary
    momentum_decaying = Column(Boolean, default=False)
    aggression_weakening = Column(Boolean, default=False)
    absorption_visible = Column(Boolean, default=False)
    rejection_candle = Column(Boolean, default=False)

    # Rotation weight (0.0–1.0) — behavioral strength, not a trade score
    rotation_weight = Column(Float, default=0.0)
    notes = Column(Text, default="")


class TacticalObservation(Base):
    """
    Master observation record — the output of a full Reflex Engine cycle.
    This is the paper-trade log and alert record.
    Observer mode only — no execution fields.
    """
    __tablename__ = "tactical_observations"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    symbol = Column(String(20), default="BTCUSDT")
    mode = Column(String(20), default="observer")  # always "observer" in Phase 1

    # Brain Ops context (read from /brain-state)
    brain_market_regime = Column(String(50), default="unknown")
    brain_macro_bias = Column(String(20), default="neutral")
    brain_confidence = Column(Float, default=0.0)
    brain_continuation_state = Column(String(50), default="unknown")
    brain_volatility_state = Column(String(50), default="unknown")
    brain_risk_mode = Column(String(20), default="normal")
    brain_source = Column(String(50), default="fallback")

    # 4H structural context
    structure_4h_type = Column(String(50), default="unknown")
    structure_4h_phase = Column(String(50), default="unknown")
    structure_4h_location = Column(String(50), default="unknown")
    structure_4h_quality = Column(Float, default=0.0)

    # 1H tactical context
    structure_1h_type = Column(String(50), default="unknown")
    structure_1h_phase = Column(String(50), default="unknown")
    structure_1h_location = Column(String(50), default="unknown")

    # Rotation context
    rotation_boundary = Column(String(20), default="none")   # "lower", "upper", "none"
    rotation_weight = Column(Float, default=0.0)
    momentum_decaying = Column(Boolean, default=False)

    # CHoCH context
    choch_detected = Column(Boolean, default=False)
    choch_direction = Column(String(20), default="none")

    # Liquidity context
    liquidity_event = Column(String(50), default="none")
    sweep_detected = Column(Boolean, default=False)

    # Volatility context
    volatility_state = Column(String(20), default="unknown")
    compression_score = Column(Float, default=0.0)
    expansion_score = Column(Float, default=0.0)

    # Overall behavioral weight (0.0–1.0) — not a trade score
    behavioral_weight = Column(Float, default=0.0)

    # Alert sent?
    alert_sent = Column(Boolean, default=False)

    # Full narrative summary (text delivered to Telegram)
    narrative = Column(Text, default="")


class StructureMemory(Base):
    """
    Tracks the full lifecycle of a structure from birth to death.

    A structure is "born" when first detected.
    It "lives" while the same type + boundaries persist across cycles.
    It "dies" when structure_type changes or boundaries shift significantly.

    This enables cross-time context:
    "This descending wedge is 18 candles old and has been touched 3 times."
    """
    __tablename__ = "structure_memory"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), default="BTCUSDT", index=True)
    timeframe = Column(String(10))

    # Structure identity
    structure_type = Column(String(50))
    upper_boundary = Column(Float, nullable=True)
    lower_boundary = Column(Float, nullable=True)

    # Lifecycle timestamps
    first_seen_at = Column(DateTime, default=datetime.utcnow, index=True)
    last_seen_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)     # null = still active

    # Lifecycle counters
    candles_alive = Column(Integer, default=1)     # how many cycles this structure has persisted
    lower_touches = Column(Integer, default=0)     # times price touched lower boundary
    upper_touches = Column(Integer, default=0)     # times price touched upper boundary
    lower_bounces = Column(Integer, default=0)     # touches that resulted in bounce
    upper_bounces = Column(Integer, default=0)
    lower_breaks = Column(Integer, default=0)      # touches that resulted in break
    upper_breaks = Column(Integer, default=0)

    # How did this structure end?
    # "lower_break", "upper_break", "choch", "dissolved", "active"
    end_reason = Column(String(50), default="active")

    is_active = Column(Boolean, default=True, index=True)


class BoundaryTouchLog(Base):
    """
    Records every time price touches a structural boundary.
    Then tracks outcome: did it bounce or break?

    This is the raw data that builds edge over time.
    "At lower boundary with these behavioral signatures → what happened next?"
    """
    __tablename__ = "boundary_touch_log"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), default="BTCUSDT", index=True)
    timeframe = Column(String(10))
    touched_at = Column(DateTime, default=datetime.utcnow, index=True)

    # Link to structure lifecycle
    structure_memory_id = Column(Integer, nullable=True)   # FK to structure_memory.id
    structure_type = Column(String(50))
    boundary = Column(String(10))        # "lower" or "upper"
    boundary_price = Column(Float)
    touch_price = Column(Float)
    touch_number = Column(Integer)       # which touch is this (1st, 2nd, 3rd...)

    # Behavioral context AT the time of touch
    # (same fields as rotation engine — snapshot of conditions)
    momentum_decaying = Column(Boolean, default=False)
    aggression_weakening = Column(Boolean, default=False)
    absorption_visible = Column(Boolean, default=False)
    rejection_candle = Column(Boolean, default=False)
    prior_sweep = Column(Boolean, default=False)
    rotation_weight = Column(Float, default=0.0)
    volatility_state = Column(String(20), default="unknown")
    compression_score = Column(Float, default=0.0)

    # ── OUTCOME (filled in by outcome tracker, 4 candles later) ──────────────
    outcome_resolved = Column(Boolean, default=False)
    outcome_type = Column(String(20), nullable=True)   # "bounce", "break", "neutral"
    outcome_candles = Column(Integer, nullable=True)   # how many candles until outcome clear
    outcome_price_change_pct = Column(Float, nullable=True)  # % move after touch
    outcome_resolved_at = Column(DateTime, nullable=True)


class PatternOutcome(Base):
    """
    Aggregated outcome statistics for recurring behavioral patterns.

    After enough BoundaryTouchLog entries are resolved, this table
    answers: "When I see THIS behavioral signature at THIS structure
    boundary, what has historically happened?"

    This is where the system starts developing its own edge from real data.
    Not backtest. Not theory. Actual observed behavior in this market.
    """
    __tablename__ = "pattern_outcomes"

    id = Column(Integer, primary_key=True)
    last_updated = Column(DateTime, default=datetime.utcnow)
    symbol = Column(String(20), default="BTCUSDT", index=True)

    # Pattern signature (what conditions were present)
    structure_type = Column(String(50))
    boundary = Column(String(10))
    momentum_decaying = Column(Boolean)
    aggression_weakening = Column(Boolean)
    absorption_visible = Column(Boolean)
    rejection_candle = Column(Boolean)
    prior_sweep = Column(Boolean)
    volatility_state = Column(String(20))

    # Outcome statistics
    total_occurrences = Column(Integer, default=0)
    bounce_count = Column(Integer, default=0)
    break_count = Column(Integer, default=0)
    neutral_count = Column(Integer, default=0)

    # Derived rates (computed, stored for fast lookup)
    bounce_rate = Column(Float, default=0.0)    # bounce_count / total
    break_rate = Column(Float, default=0.0)
    avg_price_change_pct = Column(Float, default=0.0)   # avg move after touch


def init_db() -> None:
    """Create all tables if they don't exist. Safe to call on every startup."""
    Base.metadata.create_all(bind=engine)


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2 — EXTENDED OBSERVATIONAL ARCHIVES
# Append-only behavioral event records.
# OBSERVATIONAL ONLY — no signal authority, no execution influence.
# ══════════════════════════════════════════════════════════════════════════════

class FakeBreakoutEvent(Base):
    """
    Archive of observed fake breakout events.

    A fake breakout is detected when price moves beyond a structural
    boundary but fails to sustain the move and reverses back inside.

    This is OBSERVATION data only.
    It does not generate signals or modify production confidence.
    """
    __tablename__ = "fake_breakout_events"

    id = Column(Integer, primary_key=True)
    observed_at = Column(DateTime, default=datetime.utcnow, index=True)
    symbol = Column(String(20), default="BTCUSDT", index=True)
    timeframe = Column(String(10))

    # Breakout characteristics
    breakout_direction = Column(String(10))      # "up", "down"
    breakout_level = Column(Float, nullable=True)
    breakout_magnitude_pct = Column(Float, default=0.0)  # how far it went beyond level

    # Rejection speed — how quickly price returned inside structure
    # "immediate" (1 candle), "fast" (2-3 candles), "slow" (4+ candles)
    rejection_speed = Column(String(20), default="unknown")
    candles_outside = Column(Integer, default=0)

    # Context at time of event
    volatility_state = Column(String(20), default="unknown")
    structure_type = Column(String(50), default="unknown")
    structure_phase = Column(String(50), default="unknown")
    regime_context = Column(String(50), default="unknown")  # from Brain if available

    # Liquidity behavior during fake breakout
    # "sweep_then_reverse", "volume_spike_no_follow", "absorption", "unknown"
    liquidity_behavior = Column(String(50), default="unknown")

    # Was a CHoCH detected shortly after?
    choch_followed = Column(Boolean, default=False)

    notes = Column(Text, default="")


class LiquiditySweepEvent(Base):
    """
    Archive of observed liquidity sweep events.

    A sweep occurs when price briefly moves beyond a key level
    (liquidating stops/orders there) before returning.

    OBSERVATIONAL ONLY.
    """
    __tablename__ = "liquidity_sweep_events"

    id = Column(Integer, primary_key=True)
    observed_at = Column(DateTime, default=datetime.utcnow, index=True)
    symbol = Column(String(20), default="BTCUSDT", index=True)
    timeframe = Column(String(10))

    # Sweep characteristics
    sweep_direction = Column(String(10))         # "up" (swept highs), "down" (swept lows)
    sweep_level = Column(Float, nullable=True)   # price level swept
    sweep_magnitude_pct = Column(Float, default=0.0)

    # What happened after the sweep
    # "reversed_strongly", "reversed_slowly", "continued", "ranging", "unknown"
    recovery_behavior = Column(String(50), default="unknown")
    candles_to_recovery = Column(Integer, nullable=True)
    recovery_pct = Column(Float, nullable=True)  # how much price recovered

    # Did price continue in sweep direction after recovery failed?
    continuation_after_sweep = Column(Boolean, default=False)

    # Context
    volatility_state = Column(String(20), default="unknown")
    structure_type = Column(String(50), default="unknown")
    regime_context = Column(String(50), default="unknown")

    notes = Column(Text, default="")


class VolatilityTrapEvent(Base):
    """
    Archive of volatility trap events.

    A volatility trap is when a compression/expansion signal forms
    but the expected expansion fails — price returns to range
    without meaningful directional follow-through.

    OBSERVATIONAL ONLY.
    """
    __tablename__ = "volatility_trap_events"

    id = Column(Integer, primary_key=True)
    observed_at = Column(DateTime, default=datetime.utcnow, index=True)
    symbol = Column(String(20), default="BTCUSDT", index=True)
    timeframe = Column(String(10))

    # Pre-trap state
    pre_trap_volatility = Column(String(20), default="unknown")  # "compressed", "compressing"
    pre_trap_atr_ratio = Column(Float, nullable=True)
    compression_streak_candles = Column(Integer, default=0)

    # Trap direction — which way the failed expansion went
    trap_direction = Column(String(10), default="unknown")  # "up", "down"

    # How badly it failed
    # "immediate_reversal", "slow_fade", "range_return", "unknown"
    failed_expansion_type = Column(String(50), default="unknown")
    max_expansion_pct = Column(Float, nullable=True)  # how far it got before failing

    # Recovery
    # "returned_to_range", "new_compression", "breakdown", "unknown"
    recovery_type = Column(String(50), default="unknown")
    duration_candles = Column(Integer, default=0)  # how long trap lasted

    # Context
    structure_type = Column(String(50), default="unknown")
    regime_context = Column(String(50), default="unknown")

    notes = Column(Text, default="")


class FailedContinuationEvent(Base):
    """
    Archive of failed continuation events.

    A failed continuation is when a trend or directional move that
    appeared to be continuing instead stalls and reverses.
    Common in ranging markets disguised as trending.

    OBSERVATIONAL ONLY.
    """
    __tablename__ = "failed_continuation_events"

    id = Column(Integer, primary_key=True)
    observed_at = Column(DateTime, default=datetime.utcnow, index=True)
    symbol = Column(String(20), default="BTCUSDT", index=True)
    timeframe = Column(String(10))

    # What direction was expected to continue
    expected_direction = Column(String(10), default="unknown")  # "up", "down"

    # How quickly it failed
    # "immediate" (1-2 candles), "fast" (3-5), "gradual" (6+)
    continuation_failure_speed = Column(String(20), default="unknown")
    candles_before_failure = Column(Integer, default=0)

    # What followed the failure
    choch_after_failure = Column(Boolean, default=False)
    volatility_shift = Column(Boolean, default=False)
    # "compression", "expansion", "ranging", "reversal", "unknown"
    structure_transition = Column(String(50), default="unknown")

    # How much of the expected continuation happened before failure (%)
    continuation_progress_pct = Column(Float, nullable=True)

    # Context
    volatility_state = Column(String(20), default="unknown")
    structure_type = Column(String(50), default="unknown")
    regime_context = Column(String(50), default="unknown")
    brain_continuation_state = Column(String(50), default="unknown")

    notes = Column(Text, default="")


# ── Phase 2 init (called alongside existing init_db) ──────────────────────────
def init_phase2_tables() -> None:
    """
    Create Phase 2 observational archive tables.
    Safe to call on startup — creates only if not exists.
    Does not modify existing Phase 1 tables.
    """
    Base.metadata.create_all(bind=engine)
