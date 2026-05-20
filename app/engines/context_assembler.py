"""
BTC Reflex Engine — Behavioral Context Assembler

THIS IS NOT A SIGNAL ENGINE.
THIS IS NOT A SCORE SYSTEM.
THIS IS NOT A TRADE RECOMMENDER.

This module assembles all engine outputs into a unified behavioral
observation — a narrative context that a trader can read and interpret.

PHILOSOPHY:
  The assembler asks:
    "What is the market behaviorally doing right now?"
  
  Not:
    "Should I buy or sell?"

  Output structure:
    - What structural environment is present? (4H)
    - What is the tactical behavior? (1H)  
    - Where is price relative to structural boundaries?
    - What boundary interaction behavior is visible?
    - Has structure character changed (CHoCH)?
    - What is the volatility state?
    - What is Brain Ops macro context saying?
    - What is the overall behavioral weight of these observations?

  A high behavioral weight means many observations are coherent and 
  aligned — the structural picture is rich with context.
  It does NOT mean "trade now."

  A low weight means observations are thin, mixed, or unclear.
  Thin context = no observation worth surfacing.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field

from app.engines.structure_engine import StructureState
from app.engines.rotation_engine import RotationObservation
from app.engines.choch_engine import CHoCHState
from app.engines.volatility_engine import VolatilityState
from app.integrations.brain_reader import BrainState
from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class BehavioralContext:
    """
    The assembled behavioral observation for one Reflex cycle.
    This is what gets logged to the DB and sent as a Telegram alert.
    """
    symbol: str

    # Brain context
    brain: BrainState

    # Engine outputs
    structure_4h: StructureState
    structure_1h: StructureState
    rotation: RotationObservation
    choch: CHoCHState
    volatility: VolatilityState

    # Assembled weight (0.0–1.0)
    # Reflects behavioral richness, NOT trade probability
    behavioral_weight: float

    # Whether this observation clears the alert threshold
    alert_worthy: bool

    # Full narrative text — what gets sent to Telegram
    narrative: str

    # Memory context — historical depth from memory layer
    memory_ctx: dict = field(default_factory=dict)

    # Individual factor weights (for transparency/debugging)
    weight_breakdown: dict = field(default_factory=dict)


class BehavioralContextAssembler:
    """
    Assembles all engine observations into a single coherent narrative.

    Weighting is used only to decide whether an observation is
    rich enough to surface as an alert. It is never presented
    as a directional probability or trade recommendation.
    """

    def assemble(
        self,
        symbol: str,
        brain: BrainState,
        structure_4h: StructureState,
        structure_1h: StructureState,
        rotation: RotationObservation,
        choch: CHoCHState,
        volatility: VolatilityState,
        current_price: float | None,
        memory_ctx: dict | None = None,
    ) -> BehavioralContext:

        weight, breakdown = self._compute_weight(
            structure_4h, structure_1h, rotation, choch, volatility
        )

        alert_worthy = weight >= settings.alert_threshold
        mem = memory_ctx or {}
        narrative = self._build_narrative(
            symbol, current_price, brain,
            structure_4h, structure_1h, rotation, choch, volatility, weight, mem
        )

        logger.info(
            "[context_assembler] %s | weight=%.2f alert=%s",
            symbol, weight, alert_worthy
        )

        return BehavioralContext(
            symbol=symbol,
            brain=brain,
            structure_4h=structure_4h,
            structure_1h=structure_1h,
            rotation=rotation,
            choch=choch,
            volatility=volatility,
            behavioral_weight=round(weight, 3),
            alert_worthy=alert_worthy,
            narrative=narrative,
            memory_ctx=mem,
            weight_breakdown=breakdown,
        )

    # ── Weight Assembly ───────────────────────────────────────────────────────

    def _compute_weight(
        self,
        s4h: StructureState,
        s1h: StructureState,
        rotation: RotationObservation,
        choch: CHoCHState,
        vol: VolatilityState,
    ) -> tuple[float, dict]:
        """
        Behavioral weight computation.

        Each factor contributes based on how behaviorally significant it is.
        Weight reflects observation richness, not directional probability.

        Max possible weight per factor:
          Structure quality 4H:    0.15
          Structure quality 1H:    0.10
          Rotation weight:         0.30
          CHoCH detected:          0.25
          Volatility state:        0.10
          Brain risk filter:       0.10 (reduces if risk_mode = "off")
        Total:                     1.00
        """
        breakdown = {}

        # 4H structure quality
        s4h_weight = s4h.structure_quality * 0.15
        breakdown["structure_4h"] = round(s4h_weight, 3)

        # 1H structure quality  
        s1h_weight = s1h.structure_quality * 0.10
        breakdown["structure_1h"] = round(s1h_weight, 3)

        # Rotation behavioral weight (most important for range-rotation focus)
        rot_weight = rotation.rotation_weight * 0.30
        breakdown["rotation"] = round(rot_weight, 3)

        # CHoCH contribution
        choch_weight = 0.0
        if choch.choch_detected:
            choch_weight = choch.conviction * 0.25
        breakdown["choch"] = round(choch_weight, 3)

        # Volatility context
        vol_weight = 0.0
        if vol.state in ("compressed", "compressing"):
            # Compression at boundary = more behaviorally significant
            if rotation.boundary != "none":
                vol_weight = vol.compression_score * 0.10
        elif vol.state == "expanding":
            vol_weight = vol.expansion_score * 0.10
        breakdown["volatility"] = round(vol_weight, 3)

        raw = s4h_weight + s1h_weight + rot_weight + choch_weight + vol_weight

        # Brain risk filter: reduce weight if Brain Ops says risk is off
        brain_mult = 1.0
        # (brain is passed separately to avoid over-coupling here)
        breakdown["subtotal_before_brain"] = round(raw, 3)

        return round(min(raw, 1.0), 3), breakdown

    # ── Narrative Builder ─────────────────────────────────────────────────────

    def _build_narrative(
        self,
        symbol: str,
        price: float | None,
        brain: BrainState,
        s4h: StructureState,
        s1h: StructureState,
        rotation: RotationObservation,
        choch: CHoCHState,
        vol: VolatilityState,
        weight: float,
        memory_ctx: dict | None = None,
    ) -> str:
        """
        Build the full behavioral observation narrative.
        This is what the trader reads. It explains context — not commands.
        """
        lines = []
        price_str = f"${price:,.2f}" if price else "Unknown"

        lines.append(f"━━━ BTC REFLEX OBSERVATION ━━━")
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

        # ── Rotation Behavior ─────────────────────────────────────────────────
        lines.append("🔄 ROTATION BEHAVIOR")
        if rotation.boundary != "none":
            boundary_label = "upper boundary" if rotation.boundary == "upper" else "lower boundary"
            lines.append(f"  Near {boundary_label} ({rotation.proximity_pct * 100:.1f}% from level)")
            behaviors = []
            if rotation.momentum_decaying:      behaviors.append("momentum decaying")
            if rotation.aggression_weakening:   behaviors.append("aggression weakening")
            if rotation.absorption_visible:     behaviors.append("absorption visible")
            if rotation.rejection_candle:       behaviors.append("rejection candle")
            if rotation.prior_sweep:            behaviors.append("prior sweep of level")
            if behaviors:
                lines.append(f"  Signals:    {', '.join(behaviors)}")
            else:
                lines.append("  Signals:    none observed")
        else:
            lines.append("  Price is mid-range — no boundary interaction.")
        lines.append("")

        # ── CHoCH ─────────────────────────────────────────────────────────────
        lines.append("🔀 STRUCTURE CHARACTER")
        lines.append(f"  Sequence:   {choch.current_character.replace('_', ' ').title()}")
        if choch.choch_detected:
            direction = "bearish shift" if choch.choch_direction == "bearish_shift" else "bullish shift"
            level = f"${choch.broken_level:,.2f}" if choch.broken_level else "unknown"
            lines.append(f"  ⚠️ CHoCH:   {direction} — level {level} broken")
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

        # ── Brain Context ─────────────────────────────────────────────────────
        lines.append("🧠 BRAIN OPS CONTEXT")
        lines.append(f"  Regime:     {brain.market_regime.replace('_', ' ').title()}")
        lines.append(f"  Bias:       {brain.macro_bias.title()}")
        lines.append(f"  Confidence: {brain.confidence:.0%}")
        lines.append(f"  Continuation: {brain.continuation_state.replace('_', ' ').title()}")
        lines.append(f"  Risk mode:  {brain.risk_mode.title()}")
        lines.append(f"  Source:     {brain.source}")
        lines.append("")

        # ── Behavioral Weight ─────────────────────────────────────────────────
        lines.append("⚖️  BEHAVIORAL WEIGHT")
        lines.append(f"  Weight: {weight:.2f} / 1.00  — {self._weight_label(weight)}")
        lines.append("")

        # ── Memory Context ────────────────────────────────────────────────────
        # MEMORY PHILOSOPHY:
        # Memory provides behavioral depth — not predictive certainty.
        # Raw percentages (e.g. "75% bounced") must NEVER appear in the narrative.
        # They would be read as directional confidence by any trader.
        # Instead: describe structural maturity, pressure accumulation, 
        # behavioral persistence — and let the trader interpret.
        mem = memory_ctx or {}
        if mem.get("has_memory"):
            lines.append("\U0001f5c4  STRUCTURAL MEMORY")
            age = mem.get("structure_age_candles", 0)
            lines.append(f"  Structure age:    {age} candles  {self._age_label(age)}")

            boundary = rotation.boundary
            if boundary == "lower":
                touches = mem.get("lower_touches", 0)
                bounces = mem.get("lower_bounces", 0)
                breaks  = mem.get("lower_breaks",  0)
            elif boundary == "upper":
                touches = mem.get("upper_touches", 0)
                bounces = mem.get("upper_bounces", 0)
                breaks  = mem.get("upper_breaks",  0)
            else:
                touches = (mem.get("lower_touches", 0) + mem.get("upper_touches", 0))
                bounces = (mem.get("lower_bounces", 0) + mem.get("upper_bounces", 0))
                breaks  = (mem.get("lower_breaks",  0) + mem.get("upper_breaks",  0))

            if touches > 0:
                lines.append(
                    f"  Boundary tests:   {touches} prior interactions at this level"
                )
                # Describe behavioral pattern in words — never as a percentage
                lines.append(
                    f"  Pressure history: {self._pressure_history_label(bounces, breaks, touches)}"
                )

            last_outcome = mem.get("last_touch_outcome")
            last_pct     = mem.get("last_touch_pct")
            if last_outcome and last_pct is not None:
                lines.append(
                    f"  Prior reaction:   {self._prior_reaction_label(last_outcome, last_pct)}"
                )

            similar = mem.get("similar_pattern_count", 0)
            b_rate  = mem.get("similar_persistence_rate")
            if similar >= 3 and b_rate is not None:
                lines.append(
                    f"  Pattern history:  {self._pattern_history_label(similar, b_rate)}"
                )
            elif similar > 0:
                lines.append(
                    f"  Pattern history:  {similar} similar observations recorded — "
                    f"insufficient data for behavioral characterization"
                )
            else:
                lines.append(
                    "  Pattern history:  first observation of this behavioral signature"
                )
            lines.append("")

        # ── Observer Note (always present) ───────────────────────────────────
        lines.append("─── Observer Mode — No Execution ───")
        lines.append("Reflex observes. The trader decides.")

        return "\n".join(lines)

    # ── Label Helpers ─────────────────────────────────────────────────────────

    def _quality_label(self, q: float) -> str:
        if q >= 0.7:  return "High"
        if q >= 0.45: return "Moderate"
        if q >= 0.20: return "Low"
        return "Weak"

    def _conviction_label(self, c: float) -> str:
        if c >= 0.7:  return "High"
        if c >= 0.4:  return "Moderate"
        return "Low — monitor for confirmation"

    def _weight_label(self, w: float) -> str:
        if w >= 0.70: return "Rich — strong behavioral confluence"
        if w >= 0.50: return "Significant — multiple observations aligning"
        if w >= 0.35: return "Developing — some behavioral context present"
        return "Thin — insufficient context to surface"

    def _age_label(self, candles: int) -> str:
        """Describe structural maturity — not predictive confidence."""
        if candles >= 40: return "(mature — extended structure)"
        if candles >= 20: return "(established — repeated boundary tests expected)"
        if candles >= 10: return "(developing — boundaries forming)"
        return "(young — structure still defining itself)"

    def _pressure_history_label(self, bounces: int, breaks: int, touches: int) -> str:
        """
        Describe the behavioral character of prior boundary interactions.
        Never as a percentage. Always as behavioral description.
        """
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
                f"held {bounces}x, failed {breaks}x — "
                f"level reliability is uncertain"
            )
        if touches == 1:
            return "first recorded interaction at this level — no behavioral baseline yet"

        return f"{touches} prior interactions — behavioral character still developing"

    def _prior_reaction_label(self, outcome: str, pct: float) -> str:
        """Describe the most recent boundary reaction behaviorally."""
        abs_pct = abs(pct)
        magnitude = (
            "sharp" if abs_pct >= 2.0 else
            "moderate" if abs_pct >= 0.8 else
            "mild"
        )
        if outcome == "bounce":
            return (
                f"prior touch showed {magnitude} rejection ({pct:+.2f}%) — "
                f"level defended with follow-through"
            )
        if outcome == "break":
            return (
                f"prior touch led to {magnitude} breakdown ({pct:+.2f}%) — "
                f"level failed to provide support"
            )
        return "prior touch showed neutral reaction — no clear directional follow-through"

    def _pattern_history_label(self, count: int, bounce_rate: float) -> str:
        """
        Describe behavioral pattern character — never as a prediction.
        bounce_rate is used only to characterize persistence vs weakness,
        never as a forward probability.
        """
        if bounce_rate >= 75:
            return (
                f"across {count} similar observations, this structure has historically "
                f"shown strong boundary persistence — absorption behavior has been "
                f"the dominant response. Current interaction should still be evaluated "
                f"on its own behavioral merits."
            )
        if bounce_rate >= 55:
            return (
                f"across {count} similar observations, boundary behavior has been mixed — "
                f"roughly balanced between persistence and failure. "
                f"Level reliability remains context-dependent."
            )
        if bounce_rate >= 35:
            return (
                f"across {count} similar observations, this structure has more frequently "
                f"shown boundary weakness than persistence. "
                f"Prior pressure has tended to accumulate rather than dissipate."
            )
        return (
            f"across {count} similar observations, boundary defense has been weak — "
            f"this behavioral signature has historically preceded level failure "
            f"more often than rejection. Continuation pressure has dominated."
        )
