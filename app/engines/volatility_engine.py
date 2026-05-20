"""
BTC Reflex Engine — Volatility Intelligence Layer

Observes the volatility state of the market.
Detects compression → expansion transitions.

PHILOSOPHY:
  Volatility state is behavioral context.
  Compression does not mean "breakout imminent."
  It means "energy is building inside a tightening structure."

  The engine observes:
  - Is ATR tightening over recent candles?
  - Are candle bodies shrinking?
  - Is the range of recent candles narrowing?
  - Has volatility been expanding (potentially after breakout)?

  This informs the structural picture.
  Low compression + boundary touch + rejection = richer rotation context.
  Expansion after compression = structure potentially breaking down or out.

  The engine never says "trade this."
  It says "the market is in compression — behavior is coiling."
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class VolatilityState:
    state: str            # "compressing", "compressed", "expanding", "normal", "unknown"
    atr_current: float    # ATR of most recent N candles
    atr_prior: float      # ATR of prior baseline period
    atr_ratio: float      # current / prior — < 1.0 = compressing, > 1.0 = expanding
    compression_score: float   # 0.0–1.0, degree of compression
    expansion_score: float     # 0.0–1.0, degree of expansion
    candles_compressing: int   # how many consecutive candles ATR has been declining
    notes: list[str] = field(default_factory=list)


class VolatilityEngine:
    """
    Detects volatility behavioral state from OHLCV candles.

    Produces:
    - Current volatility state label
    - ATR ratio (directional context)
    - Compression / expansion scores
    - Number of consecutive candles in compression

    All output is behavioral context — not a trade trigger.
    """

    def __init__(
        self,
        short_period: int = 5,
        baseline_period: int = 20,
    ):
        self.short_period = short_period
        self.baseline_period = baseline_period

    def analyze(self, candles: list[dict], timeframe: str = "4H") -> VolatilityState:
        """
        Analyze candles for volatility state.

        Args:
            candles:   OHLCV list.
            timeframe: For logging context.
        """
        min_required = self.baseline_period + self.short_period
        if len(candles) < min_required:
            return VolatilityState(
                state="unknown",
                atr_current=0.0,
                atr_prior=0.0,
                atr_ratio=1.0,
                compression_score=0.0,
                expansion_score=0.0,
                candles_compressing=0,
                notes=["Insufficient candles for volatility analysis."],
            )

        atr_current = self._atr(candles[-self.short_period:])
        atr_prior = self._atr(candles[-(self.baseline_period + self.short_period):-self.short_period])

        if atr_prior == 0:
            ratio = 1.0
        else:
            ratio = round(atr_current / atr_prior, 4)

        state = self._classify_state(ratio, candles)
        compression_score = self._compression_score(ratio, candles)
        expansion_score = self._expansion_score(ratio)
        candles_compressing = self._count_compressing(candles)

        notes = self._build_notes(
            state, ratio, compression_score, expansion_score, candles_compressing, timeframe
        )

        logger.info(
            "[volatility_engine] %s | state=%s ratio=%.3f compress=%.2f expand=%.2f streak=%d",
            timeframe, state, ratio, compression_score, expansion_score, candles_compressing
        )

        return VolatilityState(
            state=state,
            atr_current=round(atr_current, 2),
            atr_prior=round(atr_prior, 2),
            atr_ratio=ratio,
            compression_score=round(compression_score, 3),
            expansion_score=round(expansion_score, 3),
            candles_compressing=candles_compressing,
            notes=notes,
        )

    # ── ATR ───────────────────────────────────────────────────────────────────

    def _atr(self, candles: list[dict]) -> float:
        """Average True Range. Measures per-candle volatility."""
        if len(candles) < 2:
            return 0.0
        trs = []
        for i in range(1, len(candles)):
            h, l, pc = candles[i]["high"], candles[i]["low"], candles[i - 1]["close"]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        return sum(trs) / len(trs)

    # ── State Classification ──────────────────────────────────────────────────

    def _classify_state(self, ratio: float, candles: list[dict]) -> str:
        """
        Classify volatility behavioral state.

        Thresholds are intentionally conservative to avoid over-labeling.
        "compressed" requires sustained tightening, not just one quiet candle.
        """
        if ratio < 0.55:
            return "compressed"      # extreme compression — very coiled structure
        if ratio < 0.80:
            return "compressing"     # actively tightening
        if ratio > 1.50:
            return "expanding"       # volatility breaking out of compression
        if ratio > 1.20:
            return "elevated"        # above baseline but not breakout
        return "normal"

    def _compression_score(self, ratio: float, candles: list[dict]) -> float:
        """
        How compressed is the current volatility? (0.0–1.0)
        Higher = more compressed. Not a trade score.
        """
        if ratio >= 1.0:
            return 0.0

        # Base: from ratio
        base = max(0.0, (1.0 - ratio))  # 0.0 at ratio=1.0, up to 1.0 at ratio=0.0

        # Bonus: how many consecutive candles are compressing?
        streak = self._count_compressing(candles)
        streak_bonus = min(streak / 10.0, 0.30)

        # Bonus: body size shrinkage
        body_bonus = self._body_shrink_score(candles)

        return round(min(base * 0.60 + streak_bonus + body_bonus, 1.0), 3)

    def _expansion_score(self, ratio: float) -> float:
        """How expanded is current volatility vs baseline? (0.0–1.0)"""
        if ratio <= 1.0:
            return 0.0
        return round(min((ratio - 1.0) / 1.5, 1.0), 3)

    def _count_compressing(self, candles: list[dict]) -> int:
        """
        Count consecutive candles where each candle's true range
        is smaller than the previous. Measures compression streak.
        """
        if len(candles) < 2:
            return 0
        count = 0
        recent = candles[-15:]
        for i in range(len(recent) - 1, 0, -1):
            tr_now = recent[i]["high"] - recent[i]["low"]
            tr_prev = recent[i - 1]["high"] - recent[i - 1]["low"]
            if tr_now < tr_prev:
                count += 1
            else:
                break
        return count

    def _body_shrink_score(self, candles: list[dict]) -> float:
        """
        Score based on candle body size shrinkage over recent candles.
        Shrinking bodies = momentum losing conviction = compression signal.
        Returns 0.0–0.20.
        """
        if len(candles) < 8:
            return 0.0
        bodies = [abs(c["close"] - c["open"]) for c in candles[-8:]]
        if not bodies or max(bodies) == 0:
            return 0.0
        # Ratio of latest body to max body in the window
        ratio = bodies[-1] / max(bodies)
        return round(max(0.0, (1.0 - ratio)) * 0.20, 3)

    # ── Notes Builder ─────────────────────────────────────────────────────────

    def _build_notes(
        self,
        state: str,
        ratio: float,
        compression_score: float,
        expansion_score: float,
        streak: int,
        timeframe: str,
    ) -> list[str]:
        notes = []

        state_descriptions = {
            "compressed":  "Volatility is in extreme compression — structure tightly coiled.",
            "compressing": "Volatility actively contracting — range tightening.",
            "expanding":   "Volatility expanding — structure potentially breaking down.",
            "elevated":    "Volatility above baseline — above-normal candle ranges.",
            "normal":      "Volatility is within normal baseline range.",
            "unknown":     "Volatility state undetermined.",
        }
        notes.append(state_descriptions.get(state, "Unknown state."))

        notes.append(
            f"ATR ratio {ratio:.2f} vs baseline "
            f"({'below' if ratio < 1.0 else 'above'} baseline)."
        )

        if streak >= 5:
            notes.append(
                f"Compression streak: {streak} consecutive candles with tightening range. "
                f"Structure coiling for extended period."
            )
        elif streak >= 3:
            notes.append(f"Compression building: {streak} consecutive candles narrowing.")

        if compression_score >= 0.7:
            notes.append("Compression score high — structure is tightly wound.")
        if expansion_score >= 0.5:
            notes.append(
                "Expansion score elevated — volatility breaking above prior behavior. "
                "Watch structure boundaries for breakdown or breakout."
            )

        return notes
