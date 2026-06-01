"""
BTC Reflex Engine — Behavioral Interpretation Engine (W22)

Transforms behavioral observations into interpreted verdicts.

PHILOSOPHY:
  This engine answers "what is the market behaviorally doing?"
  NOT "what should the trader do?"

  Every verdict is:
    - descriptive (explains observed behavior)
    - observational (grounded in detected signals)
    - non-directional (never says buy/sell/long/short)
    - non-predictive (never assigns probability to future price)
    - evidence-based (lists specific signals that support verdict)

  A verdict is NOT:
    - a trade signal
    - an entry trigger
    - a confidence score for execution
    - a recommendation of any kind

OUTPUT FORMAT per verdict:
    verdict:     BOUNDARY_DEFENDING
    confidence:  HIGH | MEDIUM | LOW
    evidence:    list of observed signals
    explanation: human-readable behavioral description
    no_verdict_reason: populated only when verdict = NO_CLEAR_VERDICT

VERDICT CATEGORIES:
    BOUNDARY_DEFENDING      — level absorbing pressure, character intact
    PRESSURE_ACCUMULATING   — boundary weakening under repeated stress
    COMPRESSION_COILING     — volatility tightening, structure narrowing
    FAILED_CONTINUATION     — directional move breaking down (CHoCH)
    TRAPPED_POSITIONING     — sweep completed, participants caught outside
    STRUCTURE_MATURING      — extended structure with accumulating boundary tests
    EXPANSION_INITIATING    — volatility breaking above baseline after compression
    NO_CLEAR_VERDICT        — insufficient or conflicting signals
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field

from app.engines.structure_engine import StructureState
from app.engines.rotation_engine import RotationObservation
from app.engines.choch_engine import CHoCHState
from app.engines.volatility_engine import VolatilityState

logger = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────────────────────
_MIN_STRUCTURE_QUALITY    = 0.25   # structure must be this clear to support verdicts
_CHOCH_MIN_CONVICTION     = 0.35   # CHoCH must be this convincing for FAILED_CONTINUATION
_COMPRESSION_MIN_STREAK   = 4      # candles of compression for COMPRESSION_COILING
_MATURE_STRUCTURE_CANDLES = 20     # structure age for STRUCTURE_MATURING
_EXPANSION_MIN_RATIO      = 1.35   # ATR ratio for EXPANSION_INITIATING
_BOUNDARY_PROXIMITY_MAX   = 0.12   # price must be within 12% of range for boundary verdicts

# No-verdict reasons
REASON_MIXED_BEHAVIOR         = "mixed_behavior"
REASON_CONFLICTING_SIGNALS    = "conflicting_signals"
REASON_INSUFFICIENT_MEMORY    = "insufficient_memory"
REASON_INSUFFICIENT_CONFLUENCE = "insufficient_confluence"
REASON_UNKNOWN                = "unknown"


@dataclass
class BehavioralVerdict:
    """
    Interpreted behavioral verdict for one observation cycle.

    This is an interpretation — not a signal, not a recommendation.
    The trader reads this as context for their own decision-making.
    """
    verdict:          str            # one of the 8 verdict categories
    confidence:       str            # "HIGH" | "MEDIUM" | "LOW"
    evidence:         list[str]      # specific observed signals supporting the verdict
    explanation:      str            # human-readable behavioral description
    no_verdict_reason: str = ""      # populated only when verdict = NO_CLEAR_VERDICT

    # Secondary verdicts — additional behavioral context (max 1)
    secondary_verdict: str = ""
    secondary_evidence: list[str] = field(default_factory=list)


class InterpretationEngine:
    """
    Derives behavioral verdicts from engine outputs.

    Evaluation order (priority):
      1. FAILED_CONTINUATION  — CHoCH with conviction (structure character changed)
      2. TRAPPED_POSITIONING  — sweep + return (strongest behavioral signal)
      3. BOUNDARY_DEFENDING   — absorption at boundary, sequence intact
      4. PRESSURE_ACCUMULATING — boundary weakening under repeated stress
      5. EXPANSION_INITIATING — volatility breaking above baseline
      6. COMPRESSION_COILING  — sustained compression, energy building
      7. STRUCTURE_MATURING   — extended age, accumulating tests
      8. NO_CLEAR_VERDICT     — insufficient confluence

    Only one primary verdict is assigned per cycle.
    A secondary verdict may be added if clearly supported.
    """

    def interpret(
        self,
        structure_4h: StructureState,
        structure_1h: StructureState,
        rotation: RotationObservation,
        choch: CHoCHState,
        volatility: VolatilityState,
        memory_ctx: dict,
    ) -> BehavioralVerdict:
        """
        Evaluate all behavioral signals and assign a verdict.

        Args:
            structure_4h: 4H structural context
            structure_1h: 1H tactical context
            rotation:     Boundary interaction observation
            choch:        Change of character state
            volatility:   Volatility state
            memory_ctx:   Historical memory context dict

        Returns:
            BehavioralVerdict — descriptive, non-directional interpretation
        """

        # ── 1. FAILED_CONTINUATION — highest priority ─────────────────────────
        verdict = self._check_failed_continuation(choch, structure_4h)
        if verdict:
            secondary = self._check_secondary(
                structure_4h, rotation, volatility, memory_ctx,
                exclude="FAILED_CONTINUATION"
            )
            verdict.secondary_verdict  = secondary.verdict if secondary else ""
            verdict.secondary_evidence = secondary.evidence if secondary else []
            self._log(verdict)
            return verdict

        # ── 2. TRAPPED_POSITIONING ────────────────────────────────────────────
        verdict = self._check_trapped_positioning(rotation, structure_4h)
        if verdict:
            secondary = self._check_secondary(
                structure_4h, rotation, volatility, memory_ctx,
                exclude="TRAPPED_POSITIONING"
            )
            verdict.secondary_verdict  = secondary.verdict if secondary else ""
            verdict.secondary_evidence = secondary.evidence if secondary else []
            self._log(verdict)
            return verdict

        # ── 3. BOUNDARY_DEFENDING ─────────────────────────────────────────────
        verdict = self._check_boundary_defending(rotation, choch, structure_4h, memory_ctx)
        if verdict:
            secondary = self._check_secondary(
                structure_4h, rotation, volatility, memory_ctx,
                exclude="BOUNDARY_DEFENDING"
            )
            verdict.secondary_verdict  = secondary.verdict if secondary else ""
            verdict.secondary_evidence = secondary.evidence if secondary else []
            self._log(verdict)
            return verdict

        # ── 4. PRESSURE_ACCUMULATING ──────────────────────────────────────────
        verdict = self._check_pressure_accumulating(rotation, structure_4h, memory_ctx)
        if verdict:
            self._log(verdict)
            return verdict

        # ── 5. EXPANSION_INITIATING ───────────────────────────────────────────
        verdict = self._check_expansion_initiating(volatility, structure_4h)
        if verdict:
            self._log(verdict)
            return verdict

        # ── 6. COMPRESSION_COILING ────────────────────────────────────────────
        verdict = self._check_compression_coiling(volatility, structure_4h)
        if verdict:
            self._log(verdict)
            return verdict

        # ── 7. STRUCTURE_MATURING ─────────────────────────────────────────────
        verdict = self._check_structure_maturing(structure_4h, memory_ctx)
        if verdict:
            self._log(verdict)
            return verdict

        # ── 8. NO_CLEAR_VERDICT ───────────────────────────────────────────────
        no_verdict = self._build_no_verdict(
            structure_4h, rotation, choch, volatility, memory_ctx
        )
        self._log(no_verdict)
        return no_verdict

    # ── Verdict Checkers ──────────────────────────────────────────────────────

    def _check_failed_continuation(
        self, choch: CHoCHState, structure: StructureState
    ) -> BehavioralVerdict | None:
        """
        FAILED_CONTINUATION:
        CHoCH detected with sufficient conviction.
        Prior swing sequence has been structurally invalidated.
        """
        if not choch.choch_detected:
            return None
        if choch.conviction < _CHOCH_MIN_CONVICTION:
            return None

        evidence = [
            f"CHoCH detected: {choch.choch_direction.replace('_', ' ')}",
            f"Conviction: {self._conviction_label(choch.conviction)}",
            f"Prior swing sequence invalidated at ${choch.broken_level:,.2f}"
            if choch.broken_level else "Prior swing sequence invalidated",
        ]
        if choch.conviction >= 0.65:
            evidence.append("Clean close beyond broken level — high-conviction structural shift")
        else:
            evidence.append("Marginal break — monitor for confirmation across next candles")

        confidence = "HIGH" if choch.conviction >= 0.65 else "MEDIUM"

        explanation = (
            f"The prior {'bullish' if choch.choch_direction == 'bearish_shift' else 'bearish'} "
            f"swing sequence has been structurally invalidated. "
            f"Price has closed beyond the last "
            f"{'higher low' if choch.choch_direction == 'bearish_shift' else 'lower high'}, "
            f"breaking the sequence character. "
            f"This is a structural behavioral transition — "
            f"continuation of the prior directional move is no longer intact."
        )

        return BehavioralVerdict(
            verdict="FAILED_CONTINUATION",
            confidence=confidence,
            evidence=evidence,
            explanation=explanation,
        )

    def _check_trapped_positioning(
        self, rotation: RotationObservation, structure: StructureState
    ) -> BehavioralVerdict | None:
        """
        TRAPPED_POSITIONING:
        A prior sweep of a structural level occurred and price has
        returned inside the structure. Participants who entered on
        the sweep are now positioned outside their expected range.
        """
        if not rotation.prior_sweep:
            return None
        if rotation.boundary == "none":
            return None
        if structure.structure_quality < _MIN_STRUCTURE_QUALITY:
            return None

        boundary_side = "upper boundary" if rotation.boundary == "upper" else "lower boundary"
        evidence = [
            f"Prior sweep of {boundary_side} detected",
            "Price has returned inside structural range after sweep",
            f"Distance from swept level: {rotation.proximity_pct * 100:.1f}% of range",
        ]
        if rotation.rejection_candle:
            evidence.append("Rejection candle visible following sweep")
        if rotation.momentum_decaying:
            evidence.append("Momentum decaying after sweep reversal")
        if rotation.absorption_visible:
            evidence.append("Absorption visible at post-sweep level")

        confidence = "HIGH" if len(evidence) >= 4 else "MEDIUM"

        explanation = (
            f"A liquidity sweep of the {boundary_side} has occurred — price moved "
            f"beyond the structural level, triggering stops and orders positioned "
            f"at that level, then reversed back inside the structure. "
            f"Participants who entered in the direction of the sweep "
            f"are now in adverse territory. "
            f"This behavioral pattern frequently precedes rotation "
            f"toward the opposite boundary, but requires independent confirmation."
        )

        return BehavioralVerdict(
            verdict="TRAPPED_POSITIONING",
            confidence=confidence,
            evidence=evidence,
            explanation=explanation,
        )

    def _check_boundary_defending(
        self,
        rotation: RotationObservation,
        choch: CHoCHState,
        structure: StructureState,
        memory_ctx: dict,
    ) -> BehavioralVerdict | None:
        """
        BOUNDARY_DEFENDING:
        Price is at a structural boundary showing absorption/rejection behavior.
        Swing sequence is intact — no character change yet.
        """
        if rotation.boundary == "none":
            return None
        if rotation.proximity_pct > _BOUNDARY_PROXIMITY_MAX:
            return None
        if choch.choch_detected:
            return None  # character already changed — use FAILED_CONTINUATION

        # Need at least 2 behavioral signals
        signals = [
            rotation.momentum_decaying,
            rotation.aggression_weakening,
            rotation.absorption_visible,
            rotation.rejection_candle,
        ]
        signal_count = sum(signals)
        if signal_count < 2:
            return None

        boundary_side = "lower" if rotation.boundary == "lower" else "upper"
        evidence = []
        if rotation.momentum_decaying:
            evidence.append("Candle body momentum decaying — conviction weakening at boundary")
        if rotation.aggression_weakening:
            direction = "buy" if rotation.boundary == "lower" else "sell"
            evidence.append(f"{direction.title()} aggression weakening at level")
        if rotation.absorption_visible:
            evidence.append("Absorption behavior visible — high volume, small body candles")
        if rotation.rejection_candle:
            evidence.append("Rejection candle present — wick extension with opposing close")

        # Memory enrichment
        touches = memory_ctx.get(f"{boundary_side}_touches", 0)
        if touches > 0:
            evidence.append(
                f"Memory: {touches} prior interaction(s) at this boundary"
            )

        confidence = "HIGH" if signal_count >= 3 else "MEDIUM"

        explanation = (
            f"Price is interacting with the {boundary_side} structural boundary "
            f"({rotation.proximity_pct * 100:.1f}% from level) "
            f"with visible defensive behavior. "
            f"{'Multiple' if signal_count >= 3 else 'Some'} absorption and momentum signals "
            f"suggest the level is currently being defended. "
            f"Swing sequence character remains intact — no CHoCH has occurred. "
            f"This is a behavioral observation of current boundary interaction, "
            f"not a directional prediction."
        )

        return BehavioralVerdict(
            verdict="BOUNDARY_DEFENDING",
            confidence=confidence,
            evidence=evidence,
            explanation=explanation,
        )

    def _check_pressure_accumulating(
        self,
        rotation: RotationObservation,
        structure: StructureState,
        memory_ctx: dict,
    ) -> BehavioralVerdict | None:
        """
        PRESSURE_ACCUMULATING:
        Boundary is being tested repeatedly with weakening defense.
        Each touch showing less conviction than the prior.
        """
        if rotation.boundary == "none":
            return None

        boundary_side = "lower" if rotation.boundary == "lower" else "upper"
        touches   = memory_ctx.get(f"{boundary_side}_touches", 0)
        bounces   = memory_ctx.get(f"{boundary_side}_bounces", 0)
        breaks    = memory_ctx.get(f"{boundary_side}_breaks", 0)

        # Need multiple touches with at least one failure OR weakening defense
        if touches < 2:
            return None

        weakening_defense = (
            not rotation.absorption_visible
            and not rotation.rejection_candle
            and rotation.rotation_weight < 0.35
        )

        has_prior_failure = breaks >= 1
        repeated_stress   = touches >= 3

        if not (weakening_defense or has_prior_failure or repeated_stress):
            return None

        evidence = [
            f"{touches} boundary interactions recorded at this level",
        ]
        if has_prior_failure:
            evidence.append(f"Prior break recorded — level has failed to hold before")
        if repeated_stress:
            evidence.append(f"Repeated testing ({touches}x) — structural stress accumulating")
        if weakening_defense:
            evidence.append("Current touch showing weak defensive signals")
        if not rotation.absorption_visible:
            evidence.append("No absorption visible — boundary not actively defended this touch")

        confidence = "MEDIUM" if touches >= 3 or has_prior_failure else "LOW"

        explanation = (
            f"The {boundary_side} boundary is experiencing accumulated structural pressure. "
            f"With {touches} recorded interaction(s) and "
            f"{'prior failure' if has_prior_failure else 'weakening defense'}, "
            f"the boundary's defensive capacity appears to be deteriorating. "
            f"This does not predict a break — it describes behavioral deterioration "
            f"at this structural level."
        )

        return BehavioralVerdict(
            verdict="PRESSURE_ACCUMULATING",
            confidence=confidence,
            evidence=evidence,
            explanation=explanation,
        )

    def _check_expansion_initiating(
        self, volatility: VolatilityState, structure: StructureState
    ) -> BehavioralVerdict | None:
        """
        EXPANSION_INITIATING:
        Volatility is breaking above baseline after a compression period.
        Structure boundaries are under stress from increasing range.
        """
        if volatility.state not in ("expanding", "elevated"):
            return None
        if volatility.atr_ratio < _EXPANSION_MIN_RATIO:
            return None

        evidence = [
            f"ATR ratio {volatility.atr_ratio:.2f}x baseline — above normal range",
            f"Volatility state: {volatility.state}",
            f"Expansion score: {volatility.expansion_score:.2f}",
        ]
        if volatility.compression_score > 0.3:
            evidence.append("Prior compression detected — expansion follows coiling period")
        if structure.phase == "expansion":
            evidence.append("Structure phase confirmed as expansion")

        confidence = "HIGH" if volatility.atr_ratio >= 1.6 else "MEDIUM"

        explanation = (
            f"Volatility is expanding above baseline (ATR {volatility.atr_ratio:.2f}x). "
            f"Candle ranges are increasing relative to the prior baseline period. "
            f"This behavioral transition from compression to expansion "
            f"indicates structural boundaries are under increasing stress. "
            f"The direction of expansion is a separate behavioral question "
            f"requiring independent evaluation."
        )

        return BehavioralVerdict(
            verdict="EXPANSION_INITIATING",
            confidence=confidence,
            evidence=evidence,
            explanation=explanation,
        )

    def _check_compression_coiling(
        self, volatility: VolatilityState, structure: StructureState
    ) -> BehavioralVerdict | None:
        """
        COMPRESSION_COILING:
        Sustained volatility contraction inside a tightening structure.
        Energy building — not yet released.
        """
        if volatility.state not in ("compressing", "compressed"):
            return None
        if volatility.candles_compressing < _COMPRESSION_MIN_STREAK:
            return None
        if structure.structure_quality < _MIN_STRUCTURE_QUALITY:
            return None

        evidence = [
            f"ATR compressing for {volatility.candles_compressing} consecutive candles",
            f"ATR ratio: {volatility.atr_ratio:.2f}x baseline (contracting)",
            f"Compression score: {volatility.compression_score:.2f}",
            f"Structure phase: {structure.phase}",
        ]
        if structure.range_width_pct < 3.0:
            evidence.append(
                f"Structure range width {structure.range_width_pct:.1f}% — "
                f"very tight consolidation"
            )

        confidence = (
            "HIGH" if volatility.candles_compressing >= 8 and volatility.compression_score >= 0.6
            else "MEDIUM" if volatility.candles_compressing >= 5
            else "LOW"
        )

        explanation = (
            f"Volatility has been contracting for {volatility.candles_compressing} candles "
            f"inside a {structure.structure_type.replace('_', ' ')} structure. "
            f"The ATR ratio of {volatility.atr_ratio:.2f}x indicates candle ranges "
            f"are well below the baseline period. "
            f"This behavioral state describes energy accumulating within a tightening range. "
            f"The direction and timing of any subsequent expansion "
            f"cannot be determined from compression alone."
        )

        return BehavioralVerdict(
            verdict="COMPRESSION_COILING",
            confidence=confidence,
            evidence=evidence,
            explanation=explanation,
        )

    def _check_structure_maturing(
        self, structure: StructureState, memory_ctx: dict
    ) -> BehavioralVerdict | None:
        """
        STRUCTURE_MATURING:
        Structure has persisted beyond typical duration with
        multiple boundary tests recorded in memory.
        """
        age = memory_ctx.get("structure_age_candles", 0)
        if age < _MATURE_STRUCTURE_CANDLES:
            return None
        if structure.structure_quality < _MIN_STRUCTURE_QUALITY:
            return None

        total_touches = (
            memory_ctx.get("lower_touches", 0)
            + memory_ctx.get("upper_touches", 0)
        )
        if total_touches < 2:
            return None

        evidence = [
            f"Structure age: {age} candles — extended persistence",
            f"Total boundary interactions: {total_touches}",
            f"Structure type: {structure.structure_type.replace('_', ' ')}",
            f"Structural clarity: {self._quality_label(structure.structure_quality)}",
        ]
        if total_touches >= 4:
            evidence.append(
                f"High boundary test frequency — structural tension elevated"
            )

        confidence = "MEDIUM" if age >= 30 else "LOW"

        explanation = (
            f"This {structure.structure_type.replace('_', ' ')} structure "
            f"has persisted for {age} candles with {total_touches} boundary "
            f"interaction(s) recorded. Extended structural persistence typically "
            f"indicates the market is in a prolonged behavioral state — "
            f"boundaries are well-defined and repeatedly tested. "
            f"Structural resolution (breakout, breakdown, or CHoCH) "
            f"has not yet occurred."
        )

        return BehavioralVerdict(
            verdict="STRUCTURE_MATURING",
            confidence=confidence,
            evidence=evidence,
            explanation=explanation,
        )

    def _check_secondary(
        self,
        structure: StructureState,
        rotation: RotationObservation,
        volatility: VolatilityState,
        memory_ctx: dict,
        exclude: str,
    ) -> BehavioralVerdict | None:
        """
        Check for a supporting secondary behavioral context.
        Only COMPRESSION_COILING and STRUCTURE_MATURING are eligible as secondary.
        Never returns the same verdict as primary.
        """
        if exclude != "COMPRESSION_COILING":
            v = self._check_compression_coiling(volatility, structure)
            if v:
                return v

        if exclude != "STRUCTURE_MATURING":
            v = self._check_structure_maturing(structure, memory_ctx)
            if v:
                return v

        return None

    def _build_no_verdict(
        self,
        structure: StructureState,
        rotation: RotationObservation,
        choch: CHoCHState,
        volatility: VolatilityState,
        memory_ctx: dict,
    ) -> BehavioralVerdict:
        """Build NO_CLEAR_VERDICT with appropriate reason."""
        reason = self._determine_no_verdict_reason(
            structure, rotation, choch, volatility, memory_ctx
        )
        return BehavioralVerdict(
            verdict           = "NO_CLEAR_VERDICT",
            confidence        = "LOW",
            evidence          = [f"Reason: {reason.replace('_', ' ')}"],
            explanation       = (
                "Behavioral signals are insufficient or conflicting "
                "to assign a clear structural interpretation this cycle. "
                "Observation continues — no verdict issued."
            ),
            no_verdict_reason = reason,
        )

    def _determine_no_verdict_reason(
        self,
        structure: StructureState,
        rotation: RotationObservation,
        choch: CHoCHState,
        volatility: VolatilityState,
        memory_ctx: dict,
    ) -> str:
        if structure.structure_type == "unknown":
            return REASON_INSUFFICIENT_CONFLUENCE
        if structure.structure_quality < _MIN_STRUCTURE_QUALITY:
            return REASON_INSUFFICIENT_CONFLUENCE
        if rotation.boundary != "none" and not any([
            rotation.momentum_decaying,
            rotation.absorption_visible,
            rotation.rejection_candle,
            rotation.prior_sweep,
        ]):
            return REASON_MIXED_BEHAVIOR
        if choch.choch_detected and choch.conviction < _CHOCH_MIN_CONVICTION:
            return REASON_CONFLICTING_SIGNALS
        if not memory_ctx.get("has_memory"):
            return REASON_INSUFFICIENT_MEMORY
        return REASON_UNKNOWN

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _conviction_label(self, c: float) -> str:
        if c >= 0.70: return "High"
        if c >= 0.45: return "Moderate"
        return "Low"

    def _quality_label(self, q: float) -> str:
        if q >= 0.70: return "High"
        if q >= 0.45: return "Moderate"
        if q >= 0.20: return "Low"
        return "Weak"

    def _log(self, v: BehavioralVerdict) -> None:
        logger.info(
            "[interpretation_engine] verdict=%s confidence=%s evidence_count=%d",
            v.verdict, v.confidence, len(v.evidence)
        )
