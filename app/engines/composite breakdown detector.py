"""
BTC Reflex Engine — Composite Breakdown Detector
Reflex Sprint 3B-P1

Pure evaluation engine. Transforms BehavioralContext → BreakdownResult.

RESPONSIBILITY (exactly one):
  BehavioralContext → evaluate() → BreakdownResult

NO execution. NO Telegram. NO scheduling. NO production side effects.
The caller (scheduler) owns all decisions about what to do with the result.

ARCHITECTURE:
  - Observer mode only. Never modifies Signal Bot state.
  - No execution, no trade decisions, no threshold changes.
  - All data sourced from already-computed BehavioralContext fields.
  - Zero new API calls per evaluation.
  - All logging routed through BreakdownEventLogger (single log interface).

CLASSIFICATION:
  HIGH_RISK_BEARISH_BREAKDOWN — strongest confluence detected
  BEARISH_BREAKDOWN_WATCH     — moderate confluence, monitoring warranted
  none                        — below threshold

TRIGGER LOGIC (W25-04 gap analysis — approved):
  bearish_count = sum of non-trend signals (trend is a gate, not a scorer):
    s_verdict  : interpretation.verdict in BEARISH_ALIGNED_VERDICTS
    s_volume   : volatility.expansion_score >= VOLUME_EXPANSION_MIN
                 OR volatility.state == "expanding"
    s_choch    : choch.choch_detected AND choch_direction == "bearish_shift"
    s_rotation : rotation.boundary == "upper" AND rotation.momentum_decaying

  Classification rules:
    trend_bearish AND count >= 3                     → HIGH_RISK
    trend_bearish AND post_expansion AND count >= 2  → HIGH_RISK (amplified)
    trend_bearish AND count >= 2                     → WATCH
    else                                             → none

ISOLATION GUARANTEES:
  - Never writes to alert_gate state
  - Never writes to journal exporter state
  - Never modifies BehavioralContext
  - Never calls Telegram
  - Never imports or references scheduler
  - Exception boundary: all failures return BreakdownResult(fired=False)

RUNTIME LOG SIGNATURES (emitted by BreakdownEventLogger):
  [breakdown] eval level=HIGH_RISK_BEARISH_BREAKDOWN signals=3 ...
  [breakdown] eval level=BEARISH_BREAKDOWN_WATCH signals=2 ...
  [breakdown] eval level=none signals=1 ...
  [breakdown] cooldown_active remaining=Nmin
  [breakdown] exception (non-fatal): ...
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Optional

from app.engines.breakdown_event_logger import BreakdownEventLogger

# ── Classification thresholds ─────────────────────────────────────────────────
BREAKDOWN_SIGNALS_WATCH = 2    # trend + 2 non-trend signals → WATCH
BREAKDOWN_SIGNALS_HIGH  = 3    # trend + 3 non-trend signals → HIGH_RISK

# ── Signal flag thresholds ────────────────────────────────────────────────────
VOLUME_EXPANSION_MIN    = 0.55  # expansion_score threshold for s_volume flag

# ── Cooldown ──────────────────────────────────────────────────────────────────
BREAKDOWN_COOLDOWN_SECS = 1800  # 30 min — matches existing emergency cadence

# ── Level constants ───────────────────────────────────────────────────────────
LEVEL_HIGH_RISK = "HIGH_RISK_BEARISH_BREAKDOWN"
LEVEL_WATCH     = "BEARISH_BREAKDOWN_WATCH"
LEVEL_NONE      = "none"

# ── Bearish-aligned verdicts (sourced from interpretation_engine.py) ──────────
_BEARISH_ALIGNED_VERDICTS = frozenset({
    "PRESSURE_ACCUMULATING",
    "FAILED_CONTINUATION",
    "EXPANSION_INITIATING",
    "TRAPPED_POSITIONING",
})

# ── Post-expansion regime states ──────────────────────────────────────────────
_POST_EXPANSION_STATES = frozenset({"post_expansion", "expanding"})

# ── Sentinel for safe float extraction ───────────────────────────────────────
_SAFE_FLOAT_FALLBACK = 0.0


def _safe_float(value: object, fallback: float = _SAFE_FLOAT_FALLBACK) -> float:
    """
    Safely extract a finite float from any value.
    Returns fallback for None, NaN, Inf, or any non-numeric type.
    """
    try:
        f = float(value)  # type: ignore[arg-type]
        return f if math.isfinite(f) else fallback
    except (TypeError, ValueError):
        return fallback


def _safe_str(value: object, fallback: str = "") -> str:
    """Return str(value) if value is a non-empty string, else fallback."""
    if isinstance(value, str) and value:
        return value
    return fallback


def _safe_bool(value: object, fallback: bool = False) -> bool:
    """Return bool(value) safely — never raises."""
    try:
        return bool(value)
    except Exception:
        return fallback


# ════════════════════════════════════════════════════════════════════════════════
# Data classes — pure data, no logic
# ════════════════════════════════════════════════════════════════════════════════

@dataclass
class BreakdownSignals:
    """
    Immutable-style signal flag set produced by _score_signals().
    Describes which bearish conditions were detected this cycle.
    """
    trend_bearish:    bool = False  # gate — classification aborts if False
    s_verdict:        bool = False  # behavioral verdict is bearish-aligned
    s_volume:         bool = False  # volatility expansion above threshold
    s_choch:          bool = False  # bearish CHoCH confirmed
    s_rotation:       bool = False  # upper boundary + momentum decaying
    s_post_expansion: bool = False  # regime amplifier

    @property
    def bearish_count(self) -> int:
        """Non-trend signal count. Trend is a gate, not a scorer."""
        return sum([self.s_verdict, self.s_volume, self.s_choch, self.s_rotation])

    def as_tags(self) -> list[str]:
        tags = []
        if self.s_verdict:        tags.append("verdict_bearish")
        if self.s_volume:         tags.append("vol_expansion")
        if self.s_choch:          tags.append("bearish_choch")
        if self.s_rotation:       tags.append("upper_boundary_decay")
        if self.s_post_expansion: tags.append("post_expansion")
        return tags


@dataclass
class BreakdownResult:
    """
    Pure data output of CompositeBreakdownDetector.evaluate().

    The detector produces this. The scheduler consumes it and decides
    what to do — surface via Telegram, write to journal, log only.

    Invariants:
      fired=True  → level is LEVEL_HIGH_RISK or LEVEL_WATCH
      fired=False → level is LEVEL_NONE or cooldown_active=True
    """
    # Classification outcome
    level:           str             = LEVEL_NONE
    fired:           bool            = False
    cooldown_active: bool            = False

    # Context snapshot at evaluation time (read-only copy of inputs)
    signals:         BreakdownSignals = field(default_factory=BreakdownSignals)
    verdict:         str             = ""
    confidence:      str             = "LOW"
    weight:          float           = 0.0
    structure_type:  str             = "unknown"

    # Optional: pre-formatted narrative text for the caller to use.
    # Empty string if level == LEVEL_NONE or cooldown_active.
    # Caller is responsible for all Telegram/output decisions.
    narrative:       str             = ""


# ════════════════════════════════════════════════════════════════════════════════
# CompositeBreakdownDetector
# ════════════════════════════════════════════════════════════════════════════════

class CompositeBreakdownDetector:
    """
    Pure evaluation engine — Reflex Sprint 3B-P1.

    Single public method: evaluate(context) → BreakdownResult

    Contract:
      - Never raises. Always returns BreakdownResult.
      - Never calls Telegram, alert_gate, journal, or scheduler.
      - Never modifies context or any shared state except _last_alert_ts.
      - All logging routed through BreakdownEventLogger.

    Usage (in scheduler):
        result = detector.evaluate(context)
        if result.fired:
            send_raw(result.narrative)   # scheduler owns this decision
    """

    def __init__(
        self,
        cooldown_secs: int          = BREAKDOWN_COOLDOWN_SECS,
        signals_watch: int          = BREAKDOWN_SIGNALS_WATCH,
        signals_high: int           = BREAKDOWN_SIGNALS_HIGH,
        volume_expansion_min: float = VOLUME_EXPANSION_MIN,
        event_logger: Optional[BreakdownEventLogger] = None,
    ) -> None:
        self._cooldown_secs        = cooldown_secs
        self._signals_watch        = signals_watch
        self._signals_high         = signals_high
        self._volume_expansion_min = volume_expansion_min
        self._last_alert_ts        = 0.0
        self._log                  = event_logger or BreakdownEventLogger()

    # ── Public API ─────────────────────────────────────────────────────────────

    def evaluate(self, context: object) -> BreakdownResult:
        """
        Evaluate context for composite breakdown conditions.

        Args:
            context: BehavioralContext — expected but not type-checked.
                     Defensively extracted. Any missing field → safe fallback.

        Returns:
            BreakdownResult — never raises.
        """
        try:
            return self._evaluate_inner(context)
        except Exception as exc:
            self._log.exception(exc)
            # Extract fields defensively — context itself may be the source
            # of the exception, so every access here must be guarded.
            try:
                verdict    = self._extract_verdict(context)
                confidence = self._extract_confidence(context)
                weight     = self._extract_weight(context)
            except Exception:
                verdict    = "unknown"
                confidence = "LOW"
                weight     = 0.0
            return BreakdownResult(
                level=LEVEL_NONE,
                fired=False,
                verdict=verdict,
                confidence=confidence,
                weight=weight,
            )

    def reset_cooldown(self) -> None:
        """Reset cooldown state. Used in tests and post-restart scenarios."""
        self._last_alert_ts = 0.0

    # ── Internal flow ──────────────────────────────────────────────────────────

    def _evaluate_inner(self, context: object) -> BreakdownResult:
        now     = time.time()
        elapsed = now - self._last_alert_ts
        remaining_min = max(0, int((self._cooldown_secs - elapsed) / 60))

        # ── Cooldown check ─────────────────────────────────────────────────────
        if elapsed < self._cooldown_secs:
            self._log.cooldown_skipped(remaining_min)
            return BreakdownResult(
                level=LEVEL_NONE,
                fired=False,
                cooldown_active=True,
                signals=self._score_signals(context),
                verdict=self._extract_verdict(context),
                confidence=self._extract_confidence(context),
                weight=self._extract_weight(context),
                structure_type=self._extract_structure_type(context),
            )

        # ── Score ──────────────────────────────────────────────────────────────
        signals = self._score_signals(context)

        # ── Classify ──────────────────────────────────────────────────────────
        level = self._classify(signals)

        # ── Emit log signature on every evaluation ─────────────────────────────
        self._log.evaluation(
            level=level,
            signals=signals,
            verdict=self._extract_verdict(context),
            confidence=self._extract_confidence(context),
            weight=self._extract_weight(context),
        )

        if level == LEVEL_NONE:
            return BreakdownResult(
                level=LEVEL_NONE,
                fired=False,
                signals=signals,
                verdict=self._extract_verdict(context),
                confidence=self._extract_confidence(context),
                weight=self._extract_weight(context),
                structure_type=self._extract_structure_type(context),
            )

        # ── Build narrative text (data only — caller decides output) ───────────
        narrative = _build_narrative(level, context, signals)

        # ── Advance cooldown ONLY after successful classification ──────────────
        self._last_alert_ts = now

        return BreakdownResult(
            level=level,
            fired=True,
            signals=signals,
            verdict=self._extract_verdict(context),
            confidence=self._extract_confidence(context),
            weight=self._extract_weight(context),
            structure_type=self._extract_structure_type(context),
            narrative=narrative,
        )

    # ── Signal Scoring ─────────────────────────────────────────────────────────

    def _score_signals(self, context: object) -> BreakdownSignals:
        """
        Defensively extract and evaluate all bearish signal flags.

        Every field access uses safe helpers. Missing, None, NaN, or
        malformed fields return safe fallbacks — never raise.
        """
        signals = BreakdownSignals()

        # ── Interpretation verdict ─────────────────────────────────────────────
        verdict = _safe_str(
            self._deep_get(context, "interpretation", "verdict"), ""
        )
        signals.trend_bearish = verdict in _BEARISH_ALIGNED_VERDICTS
        signals.s_verdict     = verdict in _BEARISH_ALIGNED_VERDICTS

        # ── Volatility expansion ───────────────────────────────────────────────
        exp_score = _safe_float(
            self._deep_get(context, "volatility", "expansion_score"), 0.0
        )
        vol_state = _safe_str(
            self._deep_get(context, "volatility", "state"), ""
        )
        signals.s_volume = (
            exp_score >= self._volume_expansion_min
            or vol_state == "expanding"
        )

        # ── Bearish CHoCH ─────────────────────────────────────────────────────
        choch_detected  = _safe_bool(self._deep_get(context, "choch", "choch_detected"))
        choch_direction = _safe_str(self._deep_get(context, "choch", "choch_direction"), "")
        signals.s_choch = choch_detected and choch_direction == "bearish_shift"

        # ── Upper boundary + momentum decaying ────────────────────────────────
        boundary         = _safe_str(self._deep_get(context, "rotation", "boundary"), "none")
        momentum_decaying = _safe_bool(self._deep_get(context, "rotation", "momentum_decaying"))
        signals.s_rotation = boundary == "upper" and momentum_decaying

        # ── Post-expansion regime amplifier ───────────────────────────────────
        signals.s_post_expansion = vol_state in _POST_EXPANSION_STATES

        return signals

    # ── Classification ─────────────────────────────────────────────────────────

    def _classify(self, signals: BreakdownSignals) -> str:
        """Approved W25-04 classification rules. Pure logic — no I/O."""
        if not signals.trend_bearish:
            return LEVEL_NONE

        count = signals.bearish_count

        if count >= self._signals_high:
            return LEVEL_HIGH_RISK

        if signals.s_post_expansion and count >= self._signals_watch:
            return LEVEL_HIGH_RISK

        if count >= self._signals_watch:
            return LEVEL_WATCH

        return LEVEL_NONE

    # ── Safe extractors ────────────────────────────────────────────────────────

    @staticmethod
    def _deep_get(obj: object, *attrs: str) -> object:
        """
        Safely traverse nested attributes.
        Returns None if any attribute is missing or raises.
        """
        current = obj
        for attr in attrs:
            try:
                current = getattr(current, attr)
            except (AttributeError, TypeError):
                return None
        return current

    def _extract_verdict(self, ctx: object) -> str:
        return _safe_str(self._deep_get(ctx, "interpretation", "verdict"), "unknown")

    def _extract_confidence(self, ctx: object) -> str:
        raw = _safe_str(self._deep_get(ctx, "interpretation", "confidence"), "LOW")
        return raw if raw in ("HIGH", "MEDIUM", "LOW") else "LOW"

    def _extract_weight(self, ctx: object) -> float:
        return _safe_float(self._deep_get(ctx, "behavioral_weight"), 0.0)

    def _extract_structure_type(self, ctx: object) -> str:
        return _safe_str(self._deep_get(ctx, "structure_4h", "structure_type"), "unknown")


# ════════════════════════════════════════════════════════════════════════════════
# Narrative builder — pure function, no I/O, no side effects
# ════════════════════════════════════════════════════════════════════════════════

def _build_narrative(
    level: str,
    context: object,
    signals: BreakdownSignals,
) -> str:
    """
    Build a formatted Reflex-style observation narrative.
    Pure function. No logging. No Telegram. No imports at call time.
    Caller decides how to surface this text.
    """
    from datetime import datetime, timezone
    now_str = datetime.now(timezone.utc).strftime("%H:%M UTC")

    is_high = (level == LEVEL_HIGH_RISK)
    icon    = "🚨" if is_high else "⚠"
    title   = "HIGH RISK BEARISH BREAKDOWN" if is_high else "BEARISH BREAKDOWN WATCH"

    def _get(obj: object, *attrs: str, default: str = "") -> str:
        cur = obj
        for a in attrs:
            try:
                cur = getattr(cur, a)
            except (AttributeError, TypeError):
                return default
        return str(cur) if cur is not None else default

    verdict_str    = _get(context, "interpretation", "verdict", default="unknown").replace("_", " ")
    confidence_str = _get(context, "interpretation", "confidence", default="LOW")
    weight_val     = _safe_float(getattr(context, "behavioral_weight", None), 0.0)
    exp_score      = _safe_float(_CompositeBreakdownDetector_deep_get(context, "volatility", "expansion_score"), 0.0)
    vol_state      = _get(context, "volatility", "state", default="unknown")
    proximity      = _safe_float(_CompositeBreakdownDetector_deep_get(context, "rotation", "proximity_pct"), 0.0)
    s4h_type       = _get(context, "structure_4h", "structure_type", default="unknown").replace("_", " ").title()
    s4h_phase      = _get(context, "structure_4h", "phase", default="unknown").replace("_", " ").title()
    s1h_type       = _get(context, "structure_1h", "structure_type", default="unknown").replace("_", " ").title()
    s1h_phase      = _get(context, "structure_1h", "phase", default="unknown").replace("_", " ").title()
    choch_level    = getattr(getattr(context, "choch", None), "broken_level", None)
    choch_str      = f"${choch_level:,.2f}" if choch_level else "confirmed"

    lines = [
        f"━━━ {icon} {title} ━━━",
        f"BTC  |  {now_str}",
        "",
        "🧠 COMPOSITE SIGNAL",
        f"  Verdict:    {verdict_str}",
        f"  Confidence: {confidence_str}",
        f"  Weight:     {weight_val:.3f}",
        "",
        "📊 SIGNALS DETECTED",
    ]
    if signals.s_verdict:
        lines.append(f"  · Behavioral verdict: {verdict_str}")
    if signals.s_volume:
        lines.append(f"  · Volatility expanding: score={exp_score:.2f}  state={vol_state}")
    if signals.s_choch:
        lines.append(f"  · Bearish CHoCH detected: {choch_str}")
    if signals.s_rotation:
        lines.append(f"  · Upper boundary pressure: momentum decaying  ({proximity*100:.1f}% from level)")
    if signals.s_post_expansion:
        lines.append(f"  · Regime: {vol_state} (amplified)")

    lines += [
        "",
        "📖 STRUCTURE",
        f"  4H: {s4h_type}  {s4h_phase}",
        f"  1H: {s1h_type}  {s1h_phase}",
        "",
    ]

    if is_high:
        lines += [
            "📌 CONTEXT (In position): Review SL — structural risk elevated",
            "🚫 CONTEXT (No position): HIGH RISK — bearish confluence active",
        ]
    else:
        lines += [
            "📌 CONTEXT (In position): Review SL — breakdown conditions forming",
            "🚫 CONTEXT (No position): Monitor — await structural confirmation",
        ]

    lines += [
        "",
        "─── Observer Mode — No Execution ───",
        "Reflex observes. The trader decides.",
    ]
    return "\n".join(lines)


def _CompositeBreakdownDetector_deep_get(obj: object, *attrs: str) -> object:
    """Module-level deep_get for use in pure functions outside the class."""
    cur = obj
    for a in attrs:
        try:
            cur = getattr(cur, a)
        except (AttributeError, TypeError):
            return None
    return cur
