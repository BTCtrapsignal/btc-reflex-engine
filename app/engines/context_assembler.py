"""
BTC Reflex Engine — Behavioral Context Assembler (W22)

Assembles all engine outputs into a unified behavioral observation narrative.

W22 CHANGES:
  - Brain Ops context section REMOVED (architecture correction)
  - Behavioral Interpretation section ADDED (W22 feature)
  - Behavioral Depth section ADDED (replaces Brain section)
  - BehavioralVerdict integrated into narrative and BehavioralContext

PHILOSOPHY:
  The assembler answers: "What is the market behaviorally doing?"
  Not: "Should I buy or sell?"

  The Interpretation Engine adds: "What does this behavior mean structurally?"
  Not: "What is the probability of X?"

  Verdicts are descriptive. Evidence is specific. Explanation is human-readable.
  Nothing in this output is an instruction, recommendation, or signal.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field

from app.engines.structure_engine import StructureState
from app.engines.rotation_engine import RotationObservation
from app.engines.choch_engine import CHoCHState
from app.engines.volatility_engine import VolatilityState
from app.engines.interpretation_engine import InterpretationEngine, BehavioralVerdict
from app.config import settings

logger = logging.getLogger(__name__)

_interp_engine = InterpretationEngine()


@dataclass
class BehavioralContext:
    """
    Complete assembled behavioral observation for one Reflex cycle.
    Logged to DB and sent as Telegram alert.
    Brain fields removed — W22 architecture correction.
    """
    symbol: str

    # Engine outputs
    structure_4h: StructureState
    structure_1h: StructureState
    rotation:     RotationObservation
    choch:        CHoCHState
    volatility:   VolatilityState

    # W22: Behavioral interpretation
    interpretation: BehavioralVerdict

    # Behavioral weight (0.0–1.0) — richness of observation, not trade probability
    behavioral_weight: float

    # Alert threshold gate
    alert_worthy: bool

    # Full narrative text sent to Telegram
    narrative: str

    # Memory context
    memory_ctx: dict = field(default_factory=dict)

    # Weight breakdown (for debugging)
    weight_breakdown: dict = field(default_factory=dict)


class BehavioralContextAssembler:
    """
    Assembles engine observations + interpretation into a coherent narrative.
    Brain dependency removed in W22.
    """

    def assemble(
        self,
        symbol:        str,
        structure_4h:  StructureState,
        structure_1h:  StructureState,
        rotation:      RotationObservation,
        choch:         CHoCHState,
        volatility:    VolatilityState,
        current_price: float | None,
        memory_ctx:    dict | None = None,
    ) -> BehavioralContext:

        mem = memory_ctx or {}

        # Run interpretation engine
        interpretation = _interp_engine.interpret(
            structure_4h, structure_1h, rotation, choch, volatility, mem
        )

        weight, breakdown = self._compute_weight(
            structure_4h, structure_1h, rotation, choch, volatility, interpretation
        )

        alert_worthy = weight >= settings.alert_threshold
        narrative = self._build_narrative(
            symbol, current_price,
            structure_4h, structure_1h, rotation, choch, volatility,
            interpretation, weight, mem
        )

        logger.info(
            "[context_assembler] %s | verdict=%s confidence=%s weight=%.2f",
            symbol, interpretation.verdict, interpretation.confidence, weight
        )

        return BehavioralContext(
            symbol         = symbol,
            structure_4h   = structure_4h,
            structure_1h   = structure_1h,
            rotation       = rotation,
            choch          = choch,
            volatility     = volatility,
            interpretation = interpretation,
            behavioral_weight = round(weight, 3),
            alert_worthy   = alert_worthy,
            narrative      = narrative,
            memory_ctx     = mem,
            weight_breakdown = breakdown,
        )

    # ── Weight Computation ────────────────────────────────────────────────────

    def _compute_weight(
        self,
        s4h:    StructureState,
        s1h:    StructureState,
        rot:    RotationObservation,
        choch:  CHoCHState,
        vol:    VolatilityState,
        interp: BehavioralVerdict,
    ) -> tuple[float, dict]:
        """
        Behavioral weight — reflects observation richness.
        NOT a trade probability. NOT a confidence score for execution.

        W22: interpretation verdict adds weight based on verdict strength.
        Brain risk filter removed.
        """
        breakdown = {}

        s4h_w  = s4h.structure_quality * 0.15
        s1h_w  = s1h.structure_quality * 0.10
        rot_w  = rot.rotation_weight   * 0.30
        choch_w = choch.conviction * 0.20 if choch.choch_detected else 0.0

        vol_w = 0.0
        if vol.state in ("compressed", "compressing") and rot.boundary != "none":
            vol_w = vol.compression_score * 0.08
        elif vol.state == "expanding":
            vol_w = vol.expansion_score   * 0.08

        # W22: interpretation adds weight based on verdict + confidence
        interp_w = 0.0
        if interp.verdict != "NO_CLEAR_VERDICT":
            base = {"HIGH": 0.17, "MEDIUM": 0.10, "LOW": 0.05}
            interp_w = base.get(interp.confidence, 0.0)

        breakdown = {
            "structure_4h":   round(s4h_w,   3),
            "structure_1h":   round(s1h_w,   3),
            "rotation":       round(rot_w,   3),
            "choch":          round(choch_w,  3),
            "volatility":     round(vol_w,   3),
            "interpretation": round(interp_w, 3),
        }

        raw = s4h_w + s1h_w + rot_w + choch_w + vol_w + interp_w
        return round(min(raw, 1.0), 3), breakdown

    # ── Narrative Builder ─────────────────────────────────────────────────────

    def _build_narrative(
        self,
        symbol:        str,
        price:         float | None,
        s4h:           StructureState,
        s1h:           StructureState,
        rotation:      RotationObservation,
        choch:         CHoCHState,
        vol:           VolatilityState,
        interp:        BehavioralVerdict,
        weight:        float,
        memory_ctx:    dict,
    ) -> str:
        lines = []
        price_str = f"${price:,.2f}" if price else "Unknown"

        lines.append("━━━ BTC REFLEX OBSERVATION ━━━")
        lines.append(f"Symbol: {symbol}  |  Price: {price_str}")
        lines.append("")

        # ── 4H Structure ──────────────────────────────────────────────────────
        lines.append("📊 4H STRUCTURAL CONTEXT")
        lines.append(f"  Structure:  {s4h.structure_type.replace('_', ' ').title()}")
        lines.append(f"  Phase:      {s4h.phase.replace('_', ' ').title()}")
        lines.append(f"  Location:   {s4h.location.replace('_', ' ').title()}")
        if s4h.upper_boundary and s4h.lower_boundary:
            lines.append(
                f"  Range:      ${s4h.lower_boundary:,.2f} — ${s4h.upper_boundary:,.2f} "
                f"({s4h.range_width_pct:.1f}%)"
            )
        lines.append(f"  Clarity:    {self._quality_label(s4h.structure_quality)}")
        lines.append("")

        # ── 1H Tactical ───────────────────────────────────────────────────────
        lines.append("⏱ 1H TACTICAL CONTEXT")
        lines.append(f"  Structure:  {s1h.structure_type.replace('_', ' ').title()}")
        lines.append(f"  Phase:      {s1h.phase.replace('_', ' ').title()}")
        lines.append(f"  Location:   {s1h.location.replace('_', ' ').title()}")
        lines.append("")

        # ── Rotation ──────────────────────────────────────────────────────────
        lines.append("🔄 ROTATION BEHAVIOR")
        if rotation.boundary != "none":
            boundary_label = "upper boundary" if rotation.boundary == "upper" else "lower boundary"
            lines.append(f"  Near {boundary_label} ({rotation.proximity_pct * 100:.1f}% from level)")
            behaviors = []
            if rotation.momentum_decaying:     behaviors.append("momentum decaying")
            if rotation.aggression_weakening:  behaviors.append("aggression weakening")
            if rotation.absorption_visible:    behaviors.append("absorption visible")
            if rotation.rejection_candle:      behaviors.append("rejection candle")
            if rotation.prior_sweep:           behaviors.append("prior sweep of level")
            lines.append(f"  Signals:    {', '.join(behaviors) if behaviors else 'none observed'}")
        else:
            lines.append("  Price is mid-range — no boundary interaction.")
        lines.append("")

        # ── CHoCH ─────────────────────────────────────────────────────────────
        lines.append("🔀 STRUCTURE CHARACTER")
        lines.append(f"  Sequence:   {choch.current_character.replace('_', ' ').title()}")
        if choch.choch_detected:
            direction = "bearish shift" if choch.choch_direction == "bearish_shift" else "bullish shift"
            level     = f"${choch.broken_level:,.2f}" if choch.broken_level else "unknown"
            lines.append(f"  ⚠️  CHoCH:  {direction} — level {level} broken")
            lines.append(f"  Conviction: {self._conviction_label(choch.conviction)}")
        else:
            lines.append("  CHoCH:      none — sequence intact")
        lines.append("")

        # ── Volatility ────────────────────────────────────────────────────────
        lines.append("📉 VOLATILITY STATE")
        lines.append(f"  State:      {vol.state.replace('_', ' ').title()}")
        lines.append(f"  ATR ratio:  {vol.atr_ratio:.2f}x baseline")
        if vol.candles_compressing >= 3:
            lines.append(f"  Streak:     {vol.candles_compressing} candles compressing")
        lines.append("")

        # ── W22: Behavioral Interpretation ───────────────────────────────────
        lines.append("🧠 BEHAVIORAL INTERPRETATION")
        lines.append(f"  Verdict:    {interp.verdict.replace('_', ' ')}")
        lines.append(f"  Confidence: {interp.confidence}")
        if interp.evidence:
            lines.append("  Evidence:")
            for e in interp.evidence:
                lines.append(f"    · {e}")
        lines.append(f"  Reading:    {interp.explanation}")
        if interp.secondary_verdict and interp.secondary_verdict != "NO_CLEAR_VERDICT":
            lines.append(
                f"  Also:       {interp.secondary_verdict.replace('_', ' ')} "
                f"({', '.join(interp.secondary_evidence[:2])})"
            )
        lines.append("")

        # ── W22: Behavioral Depth (replaces Brain section) ────────────────────
        mem = memory_ctx
        if mem.get("has_memory"):
            lines.append("📖 BEHAVIORAL DEPTH")
            age = mem.get("structure_age_candles", 0)
            lines.append(f"  Structure age:    {age} candles  {self._age_label(age)}")

            boundary = rotation.boundary
            if boundary in ("lower", "upper"):
                touches = mem.get(f"{boundary}_touches", 0)
                bounces = mem.get(f"{boundary}_bounces", 0)
                breaks  = mem.get(f"{boundary}_breaks",  0)
                if touches > 0:
                    lines.append(f"  Boundary tests:   {touches} prior interactions at this level")
                    lines.append(f"  Pressure history: {self._pressure_history_label(bounces, breaks, touches)}")

            last_outcome = mem.get("last_touch_outcome")
            last_pct     = mem.get("last_touch_pct")
            if last_outcome and last_pct is not None:
                lines.append(f"  Prior reaction:   {self._prior_reaction_label(last_outcome, last_pct)}")

            similar = mem.get("similar_pattern_count", 0)
            b_rate  = mem.get("similar_persistence_rate")
            if similar >= 3 and b_rate is not None:
                lines.append(f"  Pattern history:  {self._pattern_history_label(similar, b_rate)}")
            elif similar > 0:
                lines.append(f"  Pattern history:  {similar} similar observations — building history")
            else:
                lines.append("  Pattern history:  first observation of this behavioral signature")
            lines.append("")

        # ── Behavioral Weight ─────────────────────────────────────────────────
        lines.append("⚖️  BEHAVIORAL WEIGHT")
        lines.append(f"  Weight: {weight:.2f} / 1.00  — {self._weight_label(weight)}")
        lines.append("")

        # ── Footer ────────────────────────────────────────────────────────────
        lines.append("─── Observer Mode — No Execution ───")
        lines.append("Reflex observes. The trader decides.")

        return "\n".join(lines)

    # ── Label Helpers ─────────────────────────────────────────────────────────

    def _quality_label(self, q: float) -> str:
        if q >= 0.70: return "High"
        if q >= 0.45: return "Moderate"
        if q >= 0.20: return "Low"
        return "Weak"

    def _conviction_label(self, c: float) -> str:
        if c >= 0.70: return "High"
        if c >= 0.40: return "Moderate"
        return "Low — monitor for confirmation"

    def _weight_label(self, w: float) -> str:
        if w >= 0.70: return "Rich — strong behavioral confluence"
        if w >= 0.50: return "Significant — multiple observations aligning"
        if w >= 0.35: return "Developing — some behavioral context present"
        return "Thin — insufficient context to surface"

    def _age_label(self, candles: int) -> str:
        if candles >= 40: return "(mature — extended structure)"
        if candles >= 20: return "(established — repeated boundary tests expected)"
        if candles >= 10: return "(developing — boundaries forming)"
        return "(young — structure still defining itself)"

    def _pressure_history_label(self, bounces: int, breaks: int, touches: int) -> str:
        if touches == 0:
            return "no prior interaction at this level"
        if breaks == 0 and bounces >= 2:
            return (
                f"boundary has shown persistent defense across {touches} tests — "
                f"level has absorbed pressure without breaking"
            )
        if bounces == 0 and breaks >= 1:
            return (
                f"boundary has failed to hold across prior tests — "
                f"level has shown limited defensive capacity"
            )
        if breaks >= 1 and bounces >= 1:
            return (
                f"boundary has shown mixed behavior — "
                f"held {bounces}x, failed {breaks}x — level reliability uncertain"
            )
        if touches == 1:
            return "first recorded interaction — no behavioral baseline yet"
        return f"{touches} prior interactions — behavioral character developing"

    def _prior_reaction_label(self, outcome: str, pct: float) -> str:
        magnitude = "sharp" if abs(pct) >= 2.0 else "moderate" if abs(pct) >= 0.8 else "mild"
        if outcome == "bounce":
            return f"prior touch showed {magnitude} rejection ({pct:+.2f}%) — level defended"
        if outcome == "break":
            return f"prior touch led to {magnitude} breakdown ({pct:+.2f}%) — level failed"
        return "prior touch showed neutral reaction — no clear directional follow-through"

    def _pattern_history_label(self, count: int, bounce_rate: float) -> str:
        if bounce_rate >= 75:
            return (
                f"across {count} similar observations, strong boundary persistence historically. "
                f"Current interaction warrants independent evaluation."
            )
        if bounce_rate >= 55:
            return (
                f"across {count} similar observations, mixed boundary behavior. "
                f"Level reliability context-dependent."
            )
        if bounce_rate >= 35:
            return (
                f"across {count} similar observations, boundary weakness more frequent. "
                f"Prior pressure has tended to accumulate."
            )
        return (
            f"across {count} similar observations, boundary defense historically weak. "
            f"Continuation pressure has dominated."
        )
