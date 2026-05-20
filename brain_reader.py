"""
BTC Reflex Engine — CHoCH Engine (Change of Character)

Detects when market structure character transitions.

PHILOSOPHY:
  A CHoCH is NOT a reversal signal.
  A CHoCH means the previous swing sequence behavior has been invalidated.

  The engine asks:
  - Was price making higher highs / higher lows? Has that sequence broken?
  - Was price making lower highs / lower lows? Has that broken?
  - What caused the break — a sweep, a momentum shift, a fake continuation?
  - How convincing is the character transition?

  CHoCH is a structural observation, not a trade command.

  Example:
    Previous behavior: HH, HL, HH, HL (bullish swing sequence)
    Event: Price breaks below last HL
    CHoCH: Bullish sequence invalidated — character shifting to bearish
    Output: Context note, NOT "go short"
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class CHoCHState:
    """
    Represents the current swing sequence character
    and any detected character transitions.
    """
    # Current observed sequence character
    current_character: str   # "bullish_sequence", "bearish_sequence", "mixed", "unknown"

    # Was a CHoCH detected this cycle?
    choch_detected: bool
    choch_direction: str     # "bearish_shift" | "bullish_shift" | "none"

    # How convincing is the CHoCH? (0.0–1.0)
    # Based on: clean break vs wick, volume context, how many sequence points broken
    conviction: float

    # Key price levels
    broken_level: float | None    # the swing point that was broken
    trigger_price: float | None   # price at which character changed

    notes: list[str] = field(default_factory=list)


class CHoCHEngine:
    """
    Detects Change of Character in swing sequence behavior.

    Tracks higher highs / higher lows for bullish sequence.
    Tracks lower highs / lower lows for bearish sequence.
    Detects when that sequence is structurally invalidated.

    Output: behavioral context. Not a trade signal.
    """

    def __init__(self, swing_lookback: int = 5):
        self.swing_lookback = swing_lookback

    def analyze(self, candles: list[dict], timeframe: str = "1H") -> CHoCHState:
        """
        Analyze candle sequence for character transitions.

        Args:
            candles:   OHLCV list (1H for tactical, 4H for structural).
            timeframe: Label for logging/context.
        """
        if len(candles) < self.swing_lookback * 3:
            return CHoCHState(
                current_character="unknown",
                choch_detected=False,
                choch_direction="none",
                conviction=0.0,
                broken_level=None,
                trigger_price=None,
                notes=["Insufficient candles for CHoCH analysis."],
            )

        swing_highs = self._find_pivots(candles, "high")
        swing_lows = self._find_pivots(candles, "low")

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return CHoCHState(
                current_character="unknown",
                choch_detected=False,
                choch_direction="none",
                conviction=0.0,
                broken_level=None,
                trigger_price=None,
                notes=["Not enough swing pivots to assess character."],
            )

        current_character = self._classify_character(swing_highs, swing_lows)
        choch_detected, choch_direction, broken_level, conviction = self._detect_choch(
            candles, swing_highs, swing_lows, current_character
        )

        trigger_price = candles[-1]["close"] if choch_detected else None
        notes = self._build_notes(
            current_character, choch_detected, choch_direction,
            broken_level, conviction, timeframe
        )

        logger.info(
            "[choch_engine] %s | character=%s choch=%s direction=%s conviction=%.2f",
            timeframe, current_character, choch_detected, choch_direction, conviction
        )

        return CHoCHState(
            current_character=current_character,
            choch_detected=choch_detected,
            choch_direction=choch_direction,
            conviction=round(conviction, 3),
            broken_level=broken_level,
            trigger_price=trigger_price,
            notes=notes,
        )

    # ── Pivot Detection ───────────────────────────────────────────────────────

    def _find_pivots(self, candles: list[dict], side: str) -> list[tuple[int, float]]:
        """
        Find swing pivot points (index, price).
        Returns list of (candle_index, price) tuples in chronological order.
        """
        lb = self.swing_lookback
        n = len(candles)
        pivots = []
        for i in range(lb, n - lb):
            val = candles[i][side]
            if side == "high":
                left = max(c["high"] for c in candles[i - lb:i])
                right = max(c["high"] for c in candles[i + 1:i + lb + 1])
                if val > left and val > right:
                    pivots.append((i, val))
            else:
                left = min(c["low"] for c in candles[i - lb:i])
                right = min(c["low"] for c in candles[i + 1:i + lb + 1])
                if val < left and val < right:
                    pivots.append((i, val))
        return pivots

    # ── Character Classification ──────────────────────────────────────────────

    def _classify_character(
        self,
        swing_highs: list[tuple[int, float]],
        swing_lows: list[tuple[int, float]],
    ) -> str:
        """
        Classify the current swing sequence character.

        Bullish sequence: HH + HL (each high and low higher than the last)
        Bearish sequence: LH + LL (each high and low lower than the last)
        Mixed: inconsistent or transitioning
        """
        highs = [p[1] for p in swing_highs[-3:]]
        lows = [p[1] for p in swing_lows[-3:]]

        hh = all(highs[i] < highs[i + 1] for i in range(len(highs) - 1))  # ascending highs
        hl = all(lows[i] < lows[i + 1] for i in range(len(lows) - 1))     # ascending lows
        lh = all(highs[i] > highs[i + 1] for i in range(len(highs) - 1))  # descending highs
        ll = all(lows[i] > lows[i + 1] for i in range(len(lows) - 1))     # descending lows

        if hh and hl:
            return "bullish_sequence"
        if lh and ll:
            return "bearish_sequence"
        return "mixed"

    # ── CHoCH Detection ───────────────────────────────────────────────────────

    def _detect_choch(
        self,
        candles: list[dict],
        swing_highs: list[tuple[int, float]],
        swing_lows: list[tuple[int, float]],
        current_character: str,
    ) -> tuple[bool, str, float | None, float]:
        """
        Detect if the current character has been invalidated.

        Bullish sequence invalidated: close below the most recent HL
        Bearish sequence invalidated: close above the most recent LH

        Returns: (detected, direction, broken_level, conviction)
        """
        current_close = candles[-1]["close"]

        if current_character == "bullish_sequence" and len(swing_lows) >= 2:
            # Most recent higher low — if price breaks below it, character shifts
            last_hl = swing_lows[-1][1]
            if current_close < last_hl:
                conviction = self._measure_conviction(candles, last_hl, "bearish")
                return True, "bearish_shift", last_hl, conviction

        elif current_character == "bearish_sequence" and len(swing_highs) >= 2:
            # Most recent lower high — if price breaks above it, character shifts
            last_lh = swing_highs[-1][1]
            if current_close > last_lh:
                conviction = self._measure_conviction(candles, last_lh, "bullish")
                return True, "bullish_shift", last_lh, conviction

        return False, "none", None, 0.0

    def _measure_conviction(
        self, candles: list[dict], broken_level: float, direction: str
    ) -> float:
        """
        How convincing is the CHoCH break?

        Factors:
        - Clean close vs just a wick: close-based breaks are more convincing
        - Recent candle body size: large body = more conviction
        - Volume: above average = more conviction

        Returns 0.0–1.0
        """
        if not candles:
            return 0.0

        c = candles[-1]
        prev = candles[-2] if len(candles) >= 2 else c
        conviction = 0.0

        # 1. Clean close beyond level (not just wick)
        if direction == "bearish" and c["close"] < broken_level:
            conviction += 0.35
        elif direction == "bullish" and c["close"] > broken_level:
            conviction += 0.35

        # 2. Body vs total candle size (large body = conviction)
        body = abs(c["close"] - c["open"])
        total = c["high"] - c["low"]
        if total > 0 and body / total > 0.6:
            conviction += 0.30

        # 3. Volume above recent average
        avg_vol = sum(cc["volume"] for cc in candles[-20:]) / min(20, len(candles))
        if c["volume"] > avg_vol * 1.2:
            conviction += 0.20

        # 4. Gap from prior close (strong momentum break)
        prior_close = prev["close"]
        gap_pct = abs(c["close"] - prior_close) / (prior_close + 1e-9)
        if gap_pct > 0.005:
            conviction += 0.15

        return round(min(conviction, 1.0), 3)

    # ── Notes Builder ─────────────────────────────────────────────────────────

    def _build_notes(
        self,
        character: str,
        detected: bool,
        direction: str,
        broken_level: float | None,
        conviction: float,
        timeframe: str,
    ) -> list[str]:
        notes = []

        char_map = {
            "bullish_sequence": "Swing sequence is bullish (HH + HL structure).",
            "bearish_sequence": "Swing sequence is bearish (LH + LL structure).",
            "mixed": "Swing sequence is mixed — no clean directional character.",
            "unknown": "Swing sequence character not yet established.",
        }
        notes.append(char_map.get(character, "Unknown character."))

        if detected:
            level_str = f"{broken_level:,.2f}" if broken_level else "unknown"
            if direction == "bearish_shift":
                notes.append(
                    f"CHoCH detected on {timeframe}: bullish swing sequence invalidated. "
                    f"Close broke below last higher low at {level_str}."
                )
            elif direction == "bullish_shift":
                notes.append(
                    f"CHoCH detected on {timeframe}: bearish swing sequence invalidated. "
                    f"Close broke above last lower high at {level_str}."
                )

            if conviction >= 0.7:
                notes.append("Conviction: High — clean close, strong body, above-average volume.")
            elif conviction >= 0.4:
                notes.append("Conviction: Moderate — close beyond level but body/volume mixed.")
            else:
                notes.append(
                    "Conviction: Low — marginal break, possible wick-only or thin volume. "
                    "Monitor for confirmation."
                )
        else:
            notes.append("No CHoCH detected this cycle — sequence character intact.")

        return notes
