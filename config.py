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
