"""
BTC Reflex Engine — Alert Gate

Single decision point for all Telegram observation messages.
No observation message reaches Telegram without passing through here.

━━━ ALLOWED OUTSIDE THIS GATE ━━━
  send_startup_message()  — one-time boot notification
  send_error_alert()      — system errors (always surface)

━━━ EVERYTHING ELSE MUST PASS THROUGH evaluate() ━━━

━━━ PRIORITY TIERS ━━━

LOW — Railway logs only. Never Telegram.
  · Heartbeat / debug cycles
  · No meaningful state change
  · Tiny behavioral drift
  · Repeated observations

MEDIUM — Telegram allowed. Cooldown + state-change required.
  · Structural location transition
  · Volatility state change
  · Rotation boundary change
  · Brain regime / bias / risk_mode shift
  · Meaningful behavioral weight delta (±0.20)
  · Persistence reminder (after long silence, once per window)

HIGH — Telegram immediately. Bypass cooldown. Duplicate suppression still applies.
  ONLY these 4 cases:
    1. CHoCH confirmed (conviction >= 0.40)
    2. Structure type transition (quality >= 0.30, not first cycle)
    3. Brain risk deterioration (normal → reduced/off)
    4. Brain risk recovery (reduced/off → normal)

━━━ HASH DESIGN ━━━
  _hash_state()    — noise-immune, for duplicate suppression only
  _extract_state() — full state, for MEDIUM change detection only
  Never mix these two responsibilities.

━━━ WEIGHT BUCKETS ━━━
  0.00–0.19 → 0.1
  0.20–0.39 → 0.3
  0.40–0.59 → 0.5
  0.60–0.79 → 0.7
  0.80–1.00 → 0.9
  Prevents hash instability from float drift.
"""
from __future__ import annotations
import hashlib
import logging
import time
from dataclasses import dataclass
from app.engines.context_assembler import BehavioralContext
from app.config import settings

logger = logging.getLogger(__name__)

# ── Constants (ENV-driven) ────────────────────────────────────────────────────
COOLDOWN_MEDIUM_SECONDS    = settings.medium_cooldown_minutes * 60
PERSISTENCE_REMINDER_SECS  = settings.persistence_reminder_hours * 3600
WEIGHT_SIGNIFICANT_DELTA   = 0.20
CHOCH_MIN_CONVICTION       = 0.40
STRUCTURE_MIN_QUALITY      = 0.30

# ── In-memory gate state (per process, resets on restart) ────────────────────
_last_sent_ts:         float = 0.0   # timestamp of last Telegram send
_last_sent_hash:       str   = ""    # structural hash of last sent observation
_last_state_snapshot:  dict  = {}    # full state snapshot at last send
_last_reminder_ts:     float = 0.0   # timestamp of last persistence reminder


@dataclass
class GateDecision:
    should_send:        bool
    priority:           str    # "HIGH" | "MEDIUM" | "LOW"
    reason:             str    # logged to Railway every cycle
    is_persistence_reminder: bool = False


# ── Public API ────────────────────────────────────────────────────────────────

def evaluate(context: BehavioralContext) -> GateDecision:
    """
    Single entry point for all Telegram observation decisions.
    Called by scheduler before every potential send.
    """
    priority = _classify_priority(context)

    # ── LOW: heartbeat only ───────────────────────────────────────────────────
    if priority == "LOW":
        return GateDecision(
            should_send=False,
            priority="LOW",
            reason="Routine cycle — no structural event or meaningful state change.",
        )

    # ── Duplicate suppression (HIGH and MEDIUM) ───────────────────────────────
    obs_hash = _observation_hash(context)
    if obs_hash == _last_sent_hash:
        # Identical structural state — check persistence reminder before suppressing
        reminder = _check_persistence_reminder(context)
        if reminder:
            return reminder
        return GateDecision(
            should_send=False,
            priority=priority,
            reason="Duplicate — structural fingerprint unchanged since last send.",
        )

    # ── HIGH: bypass cooldown ─────────────────────────────────────────────────
    if priority == "HIGH":
        return GateDecision(
            should_send=True,
            priority="HIGH",
            reason=_high_reason(context),
        )

    # ── MEDIUM: state change + cooldown ──────────────────────────────────────
    state_changed, changed_fields = _state_has_changed(context)

    if not state_changed:
        # No structural change — check persistence reminder
        reminder = _check_persistence_reminder(context)
        if reminder:
            return reminder
        return GateDecision(
            should_send=False,
            priority="MEDIUM",
            reason="MEDIUM suppressed — no meaningful state change since last send.",
        )

    now     = time.time()
    elapsed = now - _last_sent_ts
    if elapsed < COOLDOWN_MEDIUM_SECONDS:
        remaining = (COOLDOWN_MEDIUM_SECONDS - elapsed) / 60
        return GateDecision(
            should_send=False,
            priority="MEDIUM",
            reason=(
                f"MEDIUM suppressed — cooldown active "
                f"({remaining:.0f}m remaining). "
                f"Changed: {', '.join(changed_fields)}."
            ),
        )

    return GateDecision(
        should_send=True,
        priority="MEDIUM",
        reason=f"MEDIUM approved — state changed: {', '.join(changed_fields)}.",
    )


def record_sent(context: BehavioralContext, is_reminder: bool = False) -> None:
    """
    Record a successful Telegram send.
    Must be called immediately after confirmed delivery.
    """
    global _last_sent_ts, _last_sent_hash, _last_state_snapshot, _last_reminder_ts
    _last_sent_ts        = time.time()
    _last_sent_hash      = _observation_hash(context)
    _last_state_snapshot = _extract_state(context)
    if is_reminder:
        _last_reminder_ts = time.time()


def build_persistence_narrative(context: BehavioralContext) -> str:
    """
    Compact persistence reminder narrative.
    Calmer and shorter than a full observation.
    Describes structural continuity — not a new event.
    """
    s4h      = context.structure_4h
    vol      = context.volatility
    rotation = context.rotation
    hours    = (time.time() - _last_sent_ts) / 3600

    lines = [
        "━━━ STRUCTURAL PERSISTENCE UPDATE ━━━",
        f"Structure:  {s4h.structure_type.replace('_', ' ').title()} "
        f"| {s4h.phase.replace('_', ' ').title()}",
        f"Location:   {s4h.location.replace('_', ' ').title()}",
        f"Volatility: {vol.state.replace('_', ' ').title()}",
    ]

    if rotation.boundary != "none":
        lines.append(
            f"Boundary:   {rotation.boundary} boundary interaction ongoing"
        )

    lines.append(
        f"No confirmed structural character change in past {hours:.0f}h."
    )
    lines.append("─── Observer Mode — No Execution ───")
    return "\n".join(lines)


# ── Priority Classification ───────────────────────────────────────────────────

def _classify_priority(context: BehavioralContext) -> str:
    """
    Strict HIGH criteria — true structural events only.
    Behavioral weight alone does NOT qualify as HIGH.
    """
    choch     = context.choch
    s4h       = context.structure_4h
    brain     = context.brain
    weight    = context.behavioral_weight
    prev_risk = _last_state_snapshot.get("brain_risk_mode", brain.risk_mode)
    prev_type = _last_state_snapshot.get("structure_type", s4h.structure_type)

    # ── HIGH (strict — 4 cases only) ─────────────────────────────────────────
    if choch.choch_detected and choch.conviction >= CHOCH_MIN_CONVICTION:
        return "HIGH"

    if (
        _last_state_snapshot                        # not first cycle
        and s4h.structure_type != prev_type
        and s4h.structure_type != "unknown"
        and s4h.structure_quality >= STRUCTURE_MIN_QUALITY
    ):
        return "HIGH"

    if brain.risk_mode in ("off", "reduced") and prev_risk == "normal":
        return "HIGH"

    if brain.risk_mode == "normal" and prev_risk in ("off", "reduced"):
        return "HIGH"

    # ── MEDIUM ───────────────────────────────────────────────────────────────
    if weight >= 0.35:
        return "MEDIUM"

    # ── LOW ──────────────────────────────────────────────────────────────────
    return "LOW"


def _high_reason(context: BehavioralContext) -> str:
    parts = []

    if context.choch.choch_detected:
        parts.append(
            f"CHoCH confirmed: {context.choch.choch_direction} "
            f"(conviction {context.choch.conviction:.2f})"
        )

    prev_type = _last_state_snapshot.get("structure_type", "")
    if context.structure_4h.structure_type != prev_type and prev_type:
        parts.append(
            f"Structure transition: "
            f"{prev_type} → {context.structure_4h.structure_type}"
        )

    prev_risk = _last_state_snapshot.get("brain_risk_mode", "")
    if context.brain.risk_mode != prev_risk and prev_risk:
        parts.append(
            f"Brain risk mode: {prev_risk} → {context.brain.risk_mode}"
        )

    return " | ".join(parts) if parts else "HIGH structural event"


# ── Persistence Reminder ──────────────────────────────────────────────────────

def _check_persistence_reminder(context: BehavioralContext) -> GateDecision | None:
    """
    If the same structural state has persisted for PERSISTENCE_REMINDER_SECS
    without a Telegram message, allow ONE compact reminder.

    Rules:
      - Only fires if silence has lasted >= PERSISTENCE_REMINDER_SECS
      - Only fires if last reminder was also >= PERSISTENCE_REMINDER_SECS ago
      - Maximum priority: MEDIUM (never HIGH)
      - Never repeats every cycle — fires once per window then resets
      - Must not behave like a heartbeat
    """
    now = time.time()

    # No prior send yet — nothing to remind about
    if _last_sent_ts == 0.0:
        return None

    silence = now - _last_sent_ts
    since_reminder = now - _last_reminder_ts if _last_reminder_ts > 0 else float("inf")

    if silence >= PERSISTENCE_REMINDER_SECS and since_reminder >= PERSISTENCE_REMINDER_SECS:
        hours = silence / 3600
        return GateDecision(
            should_send=True,
            priority="MEDIUM",
            reason=(
                f"Persistence reminder — same structural state for {hours:.1f}h. "
                f"One compact update allowed."
            ),
            is_persistence_reminder=True,
        )
    return None


# ── State Change Detection ────────────────────────────────────────────────────

def _state_has_changed(context: BehavioralContext) -> tuple[bool, list[str]]:
    """
    Compare current observation against last sent state.
    Used for MEDIUM filtering only — separate from hash logic.
    """
    if not _last_state_snapshot:
        return True, ["first observation"]

    current = _extract_state(context)
    changed = []

    discrete = [
        "structure_location",
        "rotation_boundary",
        "volatility_state",
        "brain_regime",
        "brain_bias",
        "brain_risk_mode",
        "choch_detected",
    ]
    for field in discrete:
        prev = _last_state_snapshot.get(field)
        curr = current.get(field)
        if prev is not None and curr != prev:
            changed.append(field.replace("_", " "))

    prev_w = float(_last_state_snapshot.get("behavioral_weight", 0.0))
    curr_w = float(current.get("behavioral_weight", 0.0))
    if abs(curr_w - prev_w) >= WEIGHT_SIGNIFICANT_DELTA:
        changed.append(f"weight {prev_w:.2f}→{curr_w:.2f}")

    return bool(changed), changed


def _extract_state(context: BehavioralContext) -> dict:
    """
    Full state snapshot for MEDIUM change detection.
    Separate from _hash_state — do not merge.
    """
    return {
        "structure_type":     context.structure_4h.structure_type,
        "structure_phase":    context.structure_4h.phase,
        "structure_location": context.structure_4h.location,
        "choch_detected":     context.choch.choch_detected,
        "choch_conviction":   round(context.choch.conviction, 2),
        "volatility_state":   context.volatility.state,
        "rotation_boundary":  context.rotation.boundary,
        "brain_regime":       context.brain.market_regime,
        "brain_bias":         context.brain.macro_bias,
        "brain_risk_mode":    context.brain.risk_mode,
        "behavioral_weight":  round(context.behavioral_weight, 2),
    }


# ── Hash State (noise-immune) ─────────────────────────────────────────────────

def _bucket_weight(weight: float) -> float:
    """
    Map behavioral weight to a coarse bucket.
    Prevents hash instability from float drift between cycles.

    0.00–0.19 → 0.1
    0.20–0.39 → 0.3
    0.40–0.59 → 0.5
    0.60–0.79 → 0.7
    0.80–1.00 → 0.9
    """
    if weight < 0.20: return 0.1
    if weight < 0.40: return 0.3
    if weight < 0.60: return 0.5
    if weight < 0.80: return 0.7
    return 0.9


def _hash_state(context: BehavioralContext) -> dict:
    """
    Minimal noise-immune fields for duplicate suppression.

    Excludes:
      - raw floats (conviction, weight, ATR, scores)
      - timestamps
      - prices
      - micro-ATR movement
      - brain_bias (changes too frequently from model variation)
      - structure_quality (float noise)

    Includes only:
      - discrete string labels
      - bool fields
      - weight_bucket (coarse)
    """
    return {
        "structure_type":     context.structure_4h.structure_type,
        "structure_phase":    context.structure_4h.phase,
        "structure_location": context.structure_4h.location,
        "volatility_state":   context.volatility.state,
        "rotation_boundary":  context.rotation.boundary,
        "choch_detected":     context.choch.choch_detected,
        "choch_direction":    (
            context.choch.choch_direction
            if context.choch.choch_detected else "none"
        ),
        "brain_regime":       context.brain.market_regime,
        "brain_risk_mode":    context.brain.risk_mode,
        "weight_bucket":      _bucket_weight(context.behavioral_weight),
    }


def _observation_hash(context: BehavioralContext) -> str:
    """Stable structural fingerprint. Uses _hash_state only."""
    state   = _hash_state(context)
    content = "|".join(f"{k}={v}" for k, v in sorted(state.items()))
    return hashlib.md5(content.encode()).hexdigest()[:16]
