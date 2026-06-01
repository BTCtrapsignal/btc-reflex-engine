"""
BTC Reflex Engine — Runtime State

Lightweight shared state updated by the scheduler after every cycle.
Read by the monitor status endpoint only.

ISOLATION RULES:
  - This module never imports from Brain, OPS, or any external system
  - It only stores safe, operational summary fields
  - No internal logic, no sensitive reasoning chains, no memory internals
  - If this module fails, scheduler continues unaffected

WHAT IS EXPOSED:
  - Operational status (mode, uptime, last sync)
  - Memory health (record counts)
  - Last observation summary (structure type, phase, weight)
  - Runtime health (cycle count, error count)

WHAT IS NEVER EXPOSED:
  - Raw candle data
  - Internal engine state
  - Memory structures in detail
  - Experimental logic
  - Execution capabilities
  - Brain Ops internals
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

# ── Singleton runtime state ───────────────────────────────────────────────────
# Updated by scheduler after every cycle.
# Read by monitor endpoint via get_status().
# Thread-safe for read — scheduler writes from one thread only.

_started_at: float = time.time()

@dataclass
class _RuntimeState:
    # Operational
    mode:           str   = "observer"
    adaptive_state: str   = "starting"    # starting | stable | degraded
    version:        str   = "reflex-observer-phase2"

    # Cycle health
    cycles_completed: int   = 0
    cycles_failed:    int   = 0
    last_cycle_ts:    float = 0.0
    last_cycle_secs:  float = 0.0

    # Last observation summary (safe surface fields only)
    last_structure_type:  str   = "unknown"
    last_structure_phase: str   = "unknown"
    last_location:        str   = "unknown"
    last_volatility:      str   = "unknown"
    last_weight:          float = 0.0
    last_price:           Optional[float] = None
    last_choch_detected:  bool  = False
    last_alert_priority:  str   = "LOW"

    # Memory health (counts only — no internals)
    memory_structure_records:    int = 0
    memory_touch_records:        int = 0
    memory_pattern_records:      int = 0
    memory_fake_breakout_records: int = 0
    memory_sweep_records:        int = 0

    # Brain connection
    brain_connected: bool = False
    brain_source:    str  = "fallback"


_state = _RuntimeState()


# ── Public write API (scheduler only) ────────────────────────────────────────

def update_after_cycle(
    *,
    success:         bool,
    cycle_secs:      float,
    structure_type:  str,
    structure_phase: str,
    location:        str,
    volatility:      str,
    weight:          float,
    price:           Optional[float],
    choch_detected:  bool,
    alert_priority:  str,
    brain_source:    str,
) -> None:
    """
    Called by scheduler after every observation cycle.
    Updates operational state — never modifies scheduler behavior.
    """
    _state.cycles_completed += 1 if success else 0
    _state.cycles_failed    += 0 if success else 1
    _state.last_cycle_ts     = time.time()
    _state.last_cycle_secs   = round(cycle_secs, 2)

    if success:
        _state.last_structure_type  = structure_type
        _state.last_structure_phase = structure_phase
        _state.last_location        = location
        _state.last_volatility      = volatility
        _state.last_weight          = round(weight, 3)
        _state.last_price           = price
        _state.last_choch_detected  = choch_detected
        _state.last_alert_priority  = alert_priority
        # W22 doctrine: Reflex is fully Brain-unaware.
        # Do not infer Brain connectivity from scheduler labels such as "disabled".
        _state.brain_connected      = False
        _state.brain_source         = "disabled"
        _state.adaptive_state       = "stable"
    else:
        _state.adaptive_state = "degraded"


def update_memory_counts(
    structure_records:     int,
    touch_records:         int,
    pattern_records:       int,
    fake_breakout_records: int,
    sweep_records:         int,
) -> None:
    """Update memory health counters. Called after DB operations."""
    _state.memory_structure_records     = structure_records
    _state.memory_touch_records         = touch_records
    _state.memory_pattern_records       = pattern_records
    _state.memory_fake_breakout_records = fake_breakout_records
    _state.memory_sweep_records         = sweep_records


# ── Public read API (monitor endpoint only) ───────────────────────────────────

def get_status() -> dict:
    """
    Build the monitor-visible status dict.

    Returns only safe operational fields.
    Never exposes internals, memory structures, or execution state.
    """
    now       = time.time()
    uptime    = now - _started_at
    last_sync = (
        datetime.fromtimestamp(_state.last_cycle_ts, tz=timezone.utc).isoformat()
        if _state.last_cycle_ts > 0 else None
    )
    secs_since_sync = round(now - _state.last_cycle_ts) if _state.last_cycle_ts > 0 else None

    # Total archive records across all memory tables
    total_memory_nodes = (
        _state.memory_structure_records
        + _state.memory_touch_records
        + _state.memory_pattern_records
        + _state.memory_fake_breakout_records
        + _state.memory_sweep_records
    )

    # Active reflections = cycles completed successfully in current session
    active_reflections = _state.cycles_completed

    return {
        # ── Operational ──────────────────────────────────────────────────────
        "status":              "observer_mode",
        "runtime_mode":        "passive",
        "adaptive_state":      _state.adaptive_state,
        "version":             _state.version,
        "uptime_seconds":      round(uptime),

        # ── Sync health ───────────────────────────────────────────────────────
        "last_sync":           last_sync,
        "seconds_since_sync":  secs_since_sync,
        "last_cycle_secs":     _state.last_cycle_secs,

        # ── Observation summary (safe surface only) ───────────────────────────
        "last_structure":      _state.last_structure_type,
        "last_phase":          _state.last_structure_phase,
        "last_location":       _state.last_location,
        "last_volatility":     _state.last_volatility,
        "last_weight":         _state.last_weight,
        "last_alert_priority": _state.last_alert_priority,

        # ── Memory health ─────────────────────────────────────────────────────
        "memory_nodes":        total_memory_nodes,
        "active_reflections":  active_reflections,

        # ── Brain connection ──────────────────────────────────────────────────
        # Always false by doctrine: Reflex must not depend on or report Brain connectivity.
        "brain_connected":     False,

        # ── Cycle health ──────────────────────────────────────────────────────
        "cycles_completed":    _state.cycles_completed,
        "cycles_failed":       _state.cycles_failed,
    }
