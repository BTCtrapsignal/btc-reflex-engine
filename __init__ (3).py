"""
BTC Reflex Engine — Rotation Intelligence Layer

Observes how price behaves near structural boundaries.
Interprets behavioral quality of boundary interactions.

PHILOSOPHY:
  A price touching a boundary is not a signal.
  HOW it touches the boundary is the observation.

  The engine asks:
  - Is sell/buy aggression weakening near this boundary?
  - Are rejection candles forming?
  - Is momentum decaying into the boundary?
  - Is there absorption behavior visible?
  - Did a prior sweep of this level occur?

  These are behavioral signatures — not trade commands.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from app.engines.structure_engine import StructureState

logger = logging.getLogger(__name__)


@dataclass
class RotationObservation:
    """
    Behavioral observation at a structural boundary.
    This is context — not a trade entry.
    """
    boundary: str                    # "lower", "upper", "none"
    proximity_pct: float             # how close price is to boundary (% of range)

    # Behavioral signatures
    momentum_decaying: bool
    aggression_weakening: bool
    absorption_visible: bool
    rejection_candle: bool
    prior_sweep: bool                # recent sweep of this level before current touch

    # Overall behavioral weight (0.0–1.0)
    # This is NOT a trade score. It reflects how behaviorally rich the boundary
    # interaction is. Low weight = thin/unconvincing interaction.
    rotation_weight: float

    notes: list[str] = field(default_factory=list)


class RotationEngine:
    """
    Observes boundary interaction behavior.

    Does not produce directional signals.
    Produces behavioral context about what is happening
    at structural boundaries.
    """

    def analyze(
        self,
        candles: list[dict],
        structure: StructureState,
        current_price: float | None = None,
    ) -> RotationObservation:
        """
        Analyze price behavior at structural boundaries.

        Args:
            candles:       1H or 4H OHLCV list.
            structure:     Output from StructureEngine.
            current_price: Latest price (from binance_feed).
        """
        if not candles or structure.upper_boundary is None:
            return self._empty()

        price = current_price or candles[-1]["close"]
        upper = structure.upper_boundary
        lower = structure.lower_boundary
        rng = upper - lower if lower else 0.0

        if rng == 0:
            return self._empty()

        # Determine which boundary we're near
        proximity_upper = abs(price - upper) / rng
        proximity_lower = abs(price - lower) / rng
        proximity_pct, boundary = self._nearest_boundary(
            proximity_upper, proximity_lower
        )

        if boundary == "none":
            return RotationObservation(
                boundary="none",
                proximity_pct=1.0,
                momentum_decaying=False,
                aggression_weakening=False,
                absorption_visible=False,
                rejection_candle=False,
                prior_sweep=False,
                rotation_weight=0.0,
                notes=["Price is mid-range — no boundary interaction to observe."],
            )

        # Behavioral observations
        momentum_decaying = self._detect_momentum_decay(candles, boundary)
        aggression_weakening = self._detect_aggression_weakening(candles, boundary)
        absorption_visible = self._detect_absorption(candles, boundary)
        rejection_candle = self._detect_rejection_candle(candles, boundary)
        prior_sweep = self._detect_prior_sweep(candles, upper, lower, boundary)

        weight = self._compute_weight(
            proximity_pct,
            momentum_decaying,
            aggression_weakening,
            absorption_visible,
            rejection_candle,
            prior_sweep,
        )

        notes = self._build_notes(
            boundary, proximity_pct,
            momentum_decaying, aggression_weakening,
            absorption_visible, rejection_candle, prior_sweep
        )

        logger.info(
            "[rotation_engine] boundary=%s proximity=%.2f%% weight=%.2f",
            boundary, proximity_pct * 100, weight
        )

        return RotationObservation(
            boundary=boundary,
            proximity_pct=round(proximity_pct, 3),
            momentum_decaying=momentum_decaying,
            aggression_weakening=aggression_weakening,
            absorption_visible=absorption_visible,
            rejection_candle=rejection_candle,
            prior_sweep=prior_sweep,
            rotation_weight=round(weight, 3),
            notes=notes,
        )

    # ── Boundary Proximity ────────────────────────────────────────────────────

    def _nearest_boundary(
        self, prox_upper: float, prox_lower: float, threshold: float = 0.15
    ) -> tuple[float, str]:
        """
        Returns (proximity_fraction, boundary_label).
        Only triggers if within threshold of a boundary.
        """
        if prox_upper < prox_lower and prox_upper < threshold:
            return prox_upper, "upper"
        if prox_lower <= prox_upper and prox_lower < threshold:
            return prox_lower, "lower"
        return 1.0, "none"

    # ── Behavioral Detectors ──────────────────────────────────────────────────

    def _detect_momentum_decay(self, candles: list[dict], boundary: str) -> bool:
        """
        Momentum is decaying when recent candle bodies are shrinking
        as price approaches a boundary.
        Shrinking bodies = sellers/buyers losing conviction near the level.
        """
        if len(candles) < 5:
            return False
        recent = candles[-5:]
        bodies = [abs(c["close"] - c["open"]) for c in recent]
        # Decay = each successive body smaller than the one before
        declines = sum(1 for i in range(1, len(bodies)) if bodies[i] < bodies[i - 1])
        return declines >= 3

    def _detect_aggression_weakening(self, candles: list[dict], boundary: str) -> bool:
        """
        Taker buy ratio measures directional aggression.
        At upper boundary: buy aggression should be weakening (ratio declining).
        At lower boundary: sell aggression should be weakening (ratio increasing).
        """
        if len(candles) < 6:
            return False
        recent_ratios = [c.get("taker_buy_ratio", 0.5) for c in candles[-6:]]

        if boundary == "upper":
            # Weakening buyers: ratio trending downward
            return recent_ratios[-1] < recent_ratios[-3] < recent_ratios[-5]
        else:
            # Weakening sellers: ratio trending upward
            return recent_ratios[-1] > recent_ratios[-3] > recent_ratios[-5]

    def _detect_absorption(self, candles: list[dict], boundary: str) -> bool:
        """
        Absorption: high volume candle with small body near a boundary.
        Suggests the boundary level is being defended (orders absorbing pressure).
        High volume + small body = activity without price movement = absorption.
        """
        if len(candles) < 3:
            return False
        recent = candles[-3:]
        avg_vol = sum(c["volume"] for c in candles[-20:]) / min(20, len(candles))

        for c in recent:
            body_pct = abs(c["close"] - c["open"]) / (c["high"] - c["low"] + 1e-9)
            high_vol = c["volume"] > avg_vol * 1.3
            small_body = body_pct < 0.35
            if high_vol and small_body:
                return True
        return False

    def _detect_rejection_candle(self, candles: list[dict], boundary: str) -> bool:
        """
        A rejection candle has a long wick toward the boundary
        and closes in the opposite direction.
        At upper boundary: long upper wick + bearish close.
        At lower boundary: long lower wick + bullish close.
        """
        if not candles:
            return False
        c = candles[-1]
        body = abs(c["close"] - c["open"])
        total = c["high"] - c["low"]
        if total == 0:
            return False

        if boundary == "upper":
            upper_wick = c["high"] - max(c["open"], c["close"])
            return upper_wick > body * 1.5 and c["close"] < c["open"]
        else:
            lower_wick = min(c["open"], c["close"]) - c["low"]
            return lower_wick > body * 1.5 and c["close"] > c["open"]

    def _detect_prior_sweep(
        self,
        candles: list[dict],
        upper: float,
        lower: float,
        boundary: str,
        lookback: int = 8,
        sweep_pct: float = 0.005,
    ) -> bool:
        """
        Did price recently spike beyond the boundary and then pull back?
        This is a liquidity sweep signature — price grabbed liquidity
        beyond the level before returning inside the structure.
        """
        if len(candles) < lookback + 1:
            return False

        prior = candles[-(lookback + 1):-1]
        current_close = candles[-1]["close"]

        if boundary == "upper":
            # Prior candle spiked above upper, current close is back inside
            swept = any(c["high"] > upper * (1 + sweep_pct) for c in prior)
            back_inside = current_close < upper
            return swept and back_inside
        else:
            # Prior candle spiked below lower, current close is back inside
            swept = any(c["low"] < lower * (1 - sweep_pct) for c in prior)
            back_inside = current_close > lower
            return swept and back_inside

    # ── Weight Assembly ───────────────────────────────────────────────────────

    def _compute_weight(
        self,
        proximity_pct: float,
        momentum_decaying: bool,
        aggression_weakening: bool,
        absorption_visible: bool,
        rejection_candle: bool,
        prior_sweep: bool,
    ) -> float:
        """
        Behavioral weight — how rich is the boundary interaction?

        This is NOT a trade probability.
        It reflects how many behavioral signatures are present.
        A high weight means the interaction is contextually significant.
        A low weight means the interaction is thin / unconvincing.

        Thresholds:
          0.0–0.3  Thin. Price near boundary, no behavioral confirmation.
          0.3–0.5  Developing. Some behavioral signals present.
          0.5–0.7  Significant. Multiple behavioral signatures aligning.
          0.7+     Rich. Strong behavioral confluence at boundary.
        """
        weight = 0.0

        # Proximity: the closer, the more relevant (up to 0.20)
        weight += max(0.0, (0.15 - proximity_pct)) / 0.15 * 0.20

        if momentum_decaying:      weight += 0.20
        if aggression_weakening:   weight += 0.20
        if absorption_visible:     weight += 0.15
        if rejection_candle:       weight += 0.15
        if prior_sweep:            weight += 0.10

        return round(min(weight, 1.0), 3)

    # ── Notes Builder ─────────────────────────────────────────────────────────

    def _build_notes(
        self,
        boundary: str,
        proximity_pct: float,
        momentum_decaying: bool,
        aggression_weakening: bool,
        absorption_visible: bool,
        rejection_candle: bool,
        prior_sweep: bool,
    ) -> list[str]:
        notes = []
        side = "upper boundary" if boundary == "upper" else "lower boundary"

        notes.append(
            f"Price is {proximity_pct * 100:.1f}% from {side}."
        )

        if momentum_decaying:
            notes.append("Candle body momentum decaying — conviction weakening near boundary.")
        if aggression_weakening:
            if boundary == "upper":
                notes.append("Buy aggression weakening — taker buy ratio declining at resistance.")
            else:
                notes.append("Sell aggression weakening — taker sell ratio declining at support.")
        if absorption_visible:
            notes.append("Absorption behavior visible — high volume, small body candles at level.")
        if rejection_candle:
            notes.append("Rejection candle present — wick extension with opposing close.")
        if prior_sweep:
            notes.append(
                "Prior sweep of this level detected — liquidity was grabbed before return."
            )

        if not any([momentum_decaying, aggression_weakening, absorption_visible,
                    rejection_candle, prior_sweep]):
            notes.append("No strong behavioral confirmation at boundary yet.")

        return notes

    def _empty(self) -> RotationObservation:
        return RotationObservation(
            boundary="none",
            proximity_pct=1.0,
            momentum_decaying=False,
            aggression_weakening=False,
            absorption_visible=False,
            rejection_candle=False,
            prior_sweep=False,
            rotation_weight=0.0,
            notes=["Insufficient data for rotation analysis."],
        )
