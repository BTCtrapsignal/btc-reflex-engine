"""
BTC Reflex Engine — Structure Intelligence Layer

Detects market structure via swing high/low analysis.
Classifies the structure type and behavioral phase.

PHILOSOPHY:
  Structure is context, not signal.
  A descending wedge does not mean "go long."
  It means "price is compressing inside a narrowing range
  with lower highs — watch for boundary behavior."
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class StructureState:
    timeframe: str
    structure_type: str       # "range", "descending_wedge", "ascending_wedge",
                              # "ascending_triangle", "descending_triangle",
                              # "bull_flag", "bear_flag", "channel_up",
                              # "channel_down", "expanding", "unknown"
    phase: str                # "compression", "expansion", "bouncing", "at_boundary", "breakout"
    location: str             # "at_lower_boundary", "at_upper_boundary", "mid_range", "outside"
    upper_boundary: float | None
    lower_boundary: float | None
    range_width_pct: float    # structure width as % of current price
    structure_quality: float  # 0.0–1.0, clarity of the structure
    swing_highs: list[float] = field(default_factory=list)
    swing_lows: list[float] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class StructureEngine:
    """
    Detects and classifies market structure from OHLCV candles.

    Output is behavioral context only.
    No trade signals. No directional predictions.
    """

    def __init__(self, swing_lookback: int = 5):
        self.swing_lookback = swing_lookback

    def analyze(self, candles: list[dict], timeframe: str) -> StructureState:
        """
        Analyze candles and return structural context.

        Args:
            candles:   List of OHLCV dicts from binance_feed.
            timeframe: e.g. "4H" or "1H" — for logging/context only.
        """
        if len(candles) < self.swing_lookback * 2 + 1:
            return self._unknown(timeframe, "Insufficient candles for structure analysis.")

        swing_highs = self._find_swing_highs(candles)
        swing_lows = self._find_swing_lows(candles)

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return self._unknown(timeframe, "Insufficient swing points detected.")

        current_price = candles[-1]["close"]
        structure_type = self._classify_structure(swing_highs, swing_lows)
        upper_boundary, lower_boundary = self._get_boundaries(swing_highs, swing_lows)
        range_width_pct = self._range_width_pct(upper_boundary, lower_boundary, current_price)
        phase = self._detect_phase(candles, upper_boundary, lower_boundary, range_width_pct)
        location = self._detect_location(current_price, upper_boundary, lower_boundary, range_width_pct)
        quality = self._score_quality(swing_highs, swing_lows, structure_type, range_width_pct)
        notes = self._build_notes(structure_type, phase, location, swing_highs, swing_lows)

        logger.info(
            "[structure_engine] %s | %s | %s | %s | quality=%.2f",
            timeframe, structure_type, phase, location, quality
        )

        return StructureState(
            timeframe=timeframe,
            structure_type=structure_type,
            phase=phase,
            location=location,
            upper_boundary=upper_boundary,
            lower_boundary=lower_boundary,
            range_width_pct=range_width_pct,
            structure_quality=quality,
            swing_highs=swing_highs[-4:],
            swing_lows=swing_lows[-4:],
            notes=notes,
        )

    # ── Swing Detection ───────────────────────────────────────────────────────

    def _find_swing_highs(self, candles: list[dict]) -> list[float]:
        """
        A swing high is a candle whose high is the highest within
        swing_lookback candles on each side.
        """
        highs = []
        n = len(candles)
        lb = self.swing_lookback
        for i in range(lb, n - lb):
            h = candles[i]["high"]
            left_max = max(c["high"] for c in candles[i - lb:i])
            right_max = max(c["high"] for c in candles[i + 1:i + lb + 1])
            if h > left_max and h > right_max:
                highs.append(h)
        return highs

    def _find_swing_lows(self, candles: list[dict]) -> list[float]:
        """
        A swing low is a candle whose low is the lowest within
        swing_lookback candles on each side.
        """
        lows = []
        n = len(candles)
        lb = self.swing_lookback
        for i in range(lb, n - lb):
            l = candles[i]["low"]
            left_min = min(c["low"] for c in candles[i - lb:i])
            right_min = min(c["low"] for c in candles[i + 1:i + lb + 1])
            if l < left_min and l < right_min:
                lows.append(l)
        return lows

    # ── Structure Classification ──────────────────────────────────────────────

    def _classify_structure(
        self, swing_highs: list[float], swing_lows: list[float]
    ) -> str:
        """
        Classify structure based on the trend of recent swing highs and lows.
        Uses last 3 swing points of each type for robustness.
        """
        highs = swing_highs[-3:]
        lows = swing_lows[-3:]

        highs_descending = all(highs[i] > highs[i + 1] for i in range(len(highs) - 1))
        highs_ascending = all(highs[i] < highs[i + 1] for i in range(len(highs) - 1))
        highs_flat = self._is_flat(highs)

        lows_ascending = all(lows[i] < lows[i + 1] for i in range(len(lows) - 1))
        lows_descending = all(lows[i] > lows[i + 1] for i in range(len(lows) - 1))
        lows_flat = self._is_flat(lows)

        # Wedges — converging structure
        if highs_descending and lows_ascending:
            return "symmetrical_triangle"
        if highs_descending and lows_flat:
            return "descending_wedge"
        if highs_flat and lows_ascending:
            return "ascending_wedge"

        # Triangles — one flat boundary
        if highs_flat and lows_descending:
            return "descending_triangle"
        if highs_ascending and lows_flat:
            return "ascending_triangle"

        # Channels
        if highs_ascending and lows_ascending:
            return "channel_up"
        if highs_descending and lows_descending:
            return "channel_down"

        # Expanding structure
        if highs_ascending and lows_descending:
            return "expanding"

        # Range / flat consolidation
        if highs_flat and lows_flat:
            return "range"

        return "complex_range"

    # ── Boundary Detection ────────────────────────────────────────────────────

    def _get_boundaries(
        self, swing_highs: list[float], swing_lows: list[float]
    ) -> tuple[float | None, float | None]:
        """
        Upper boundary: average of recent swing highs.
        Lower boundary: average of recent swing lows.
        Using averages smooths noise vs taking the absolute max/min.
        """
        if not swing_highs or not swing_lows:
            return None, None
        upper = sum(swing_highs[-3:]) / len(swing_highs[-3:])
        lower = sum(swing_lows[-3:]) / len(swing_lows[-3:])
        return upper, lower

    def _range_width_pct(
        self,
        upper: float | None,
        lower: float | None,
        price: float,
    ) -> float:
        if upper is None or lower is None or price == 0:
            return 0.0
        return round((upper - lower) / price * 100, 2)

    # ── Phase Detection ───────────────────────────────────────────────────────

    def _detect_phase(
        self,
        candles: list[dict],
        upper: float | None,
        lower: float | None,
        range_width_pct: float,
    ) -> str:
        """
        Detect the behavioral phase of the structure.
        - compression: structure tightening (ATR shrinking, range narrowing)
        - expansion: volatility increasing, range widening
        - bouncing: price repeatedly touching and rejecting boundaries
        - at_boundary: price is currently at a structural edge
        """
        if len(candles) < 20:
            return "unknown"

        # ATR comparison: recent 5 candles vs prior 15
        recent_atr = self._atr(candles[-5:])
        prior_atr = self._atr(candles[-20:-5])

        if prior_atr == 0:
            return "unknown"

        atr_ratio = recent_atr / prior_atr

        if range_width_pct < 2.0:
            return "compression"
        if atr_ratio > 1.4:
            return "expansion"
        if atr_ratio < 0.75:
            return "compression"
        return "bouncing"

    # ── Location Detection ────────────────────────────────────────────────────

    def _detect_location(
        self,
        price: float,
        upper: float | None,
        lower: float | None,
        range_width_pct: float,
        proximity_pct: float = 0.03,
    ) -> str:
        """
        Where is current price relative to structural boundaries?
        proximity_pct: within this fraction of range = "at boundary"
        """
        if upper is None or lower is None:
            return "unknown"

        rng = upper - lower
        if rng == 0:
            return "unknown"

        if price > upper * (1 + proximity_pct):
            return "above_structure"
        if price < lower * (1 - proximity_pct):
            return "below_structure"
        if price >= upper - rng * proximity_pct:
            return "at_upper_boundary"
        if price <= lower + rng * proximity_pct:
            return "at_lower_boundary"
        return "mid_range"

    # ── Quality Scoring ───────────────────────────────────────────────────────

    def _score_quality(
        self,
        swing_highs: list[float],
        swing_lows: list[float],
        structure_type: str,
        range_width_pct: float,
    ) -> float:
        """
        Structural clarity score (0.0–1.0).
        Higher = cleaner, more reliable structure.
        This is NOT a trade probability score.
        """
        score = 0.0

        # More swing points = more validated structure
        score += min(len(swing_highs) / 6.0, 0.3)
        score += min(len(swing_lows) / 6.0, 0.3)

        # Cleaner structure types score higher
        clean_types = {"range", "descending_wedge", "ascending_wedge",
                       "ascending_triangle", "descending_triangle"}
        if structure_type in clean_types:
            score += 0.2

        # Range width: very tight = high compression, wider = clearer boundaries
        if 1.5 < range_width_pct < 8.0:
            score += 0.2

        return round(min(score, 1.0), 3)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _atr(self, candles: list[dict]) -> float:
        """Average True Range of a candle list."""
        if len(candles) < 2:
            return 0.0
        trs = []
        for i in range(1, len(candles)):
            h = candles[i]["high"]
            l = candles[i]["low"]
            pc = candles[i - 1]["close"]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        return sum(trs) / len(trs) if trs else 0.0

    def _is_flat(self, values: list[float], tolerance_pct: float = 0.015) -> bool:
        """Values are 'flat' if they vary by less than tolerance_pct of their mean."""
        if len(values) < 2:
            return True
        mean = sum(values) / len(values)
        if mean == 0:
            return True
        return max(abs(v - mean) / mean for v in values) < tolerance_pct

    def _build_notes(
        self,
        structure_type: str,
        phase: str,
        location: str,
        swing_highs: list[float],
        swing_lows: list[float],
    ) -> list[str]:
        """
        Build behavioral context notes for this structure observation.

        Describes structural behavior in plain language.
        Never produces directional commands or trade signals.
        Output is context for the trader to interpret — not instructions.
        """
        notes = []

        # ── Structure character ───────────────────────────────────────────────
        structure_descriptions = {
            "range":               "Price consolidating within a horizontal range — boundaries defined by repeated swing interaction.",
            "descending_wedge":    "Compression structure with lower highs — resistance declining while support holds. Range narrowing.",
            "ascending_wedge":     "Compression structure with higher lows — support rising while resistance holds. Range narrowing.",
            "symmetrical_triangle":"Converging structure — both boundaries compressing toward each other. Energy accumulating.",
            "ascending_triangle":  "Flat resistance with rising support — lower boundary ascending toward upper boundary.",
            "descending_triangle": "Flat support with declining resistance — upper boundary descending toward lower boundary.",
            "channel_up":          "Parallel ascending structure — both boundaries rising together. Trend continuation context.",
            "channel_down":        "Parallel descending structure — both boundaries falling together. Trend continuation context.",
            "expanding":           "Expanding structure — boundaries diverging. Volatility increasing, range widening.",
            "complex_range":       "Complex consolidation — swing sequence does not form a clean structure type.",
        }
        desc = structure_descriptions.get(structure_type)
        if desc:
            notes.append(desc)

        # ── Phase behavioral description ──────────────────────────────────────
        phase_descriptions = {
            "compression": "Phase: compression — ATR contracting, candle ranges tightening. Structure coiling.",
            "expansion":   "Phase: expansion — ATR increasing above baseline. Structure potentially breaking down.",
            "bouncing":    "Phase: bouncing — price interacting repeatedly with structural boundaries within normal volatility.",
            "unknown":     "Phase: undetermined — insufficient candle history for phase classification.",
        }
        phase_desc = phase_descriptions.get(phase)
        if phase_desc:
            notes.append(phase_desc)

        # ── Location behavioral description ───────────────────────────────────
        location_descriptions = {
            "at_upper_boundary":  "Price currently interacting with upper structural boundary. Watch for rejection or continuation behavior.",
            "at_lower_boundary":  "Price currently interacting with lower structural boundary. Watch for absorption or breakdown behavior.",
            "mid_range":          "Price mid-structure — no immediate boundary pressure. Range center interaction.",
            "above_structure":    "Price has moved above the defined structure range. Boundary breakout context.",
            "below_structure":    "Price has moved below the defined structure range. Boundary breakdown context.",
            "unknown":            "Price location within structure undetermined.",
        }
        loc_desc = location_descriptions.get(location)
        if loc_desc:
            notes.append(loc_desc)

        # ── Swing sequence context ────────────────────────────────────────────
        if len(swing_highs) >= 3:
            h = swing_highs[-3:]
            if h[0] > h[1] > h[2]:
                notes.append("Swing highs declining — resistance stepping down across structure.")
            elif h[0] < h[1] < h[2]:
                notes.append("Swing highs rising — upper boundary pressure building progressively.")
            else:
                notes.append("Swing highs mixed — upper boundary character inconsistent.")

        if len(swing_lows) >= 3:
            l = swing_lows[-3:]
            if l[0] < l[1] < l[2]:
                notes.append("Swing lows rising — support stepping up, lower boundary defending.")
            elif l[0] > l[1] > l[2]:
                notes.append("Swing lows declining — lower boundary losing structural support.")
            else:
                notes.append("Swing lows mixed — lower boundary character inconsistent.")

        return notes

    def _unknown(self, timeframe: str, reason: str) -> StructureState:
        return StructureState(
            timeframe=timeframe,
            structure_type="unknown",
            phase="unknown",
            location="unknown",
            upper_boundary=None,
            lower_boundary=None,
            range_width_pct=0.0,
            structure_quality=0.0,
            notes=[reason],
        )
