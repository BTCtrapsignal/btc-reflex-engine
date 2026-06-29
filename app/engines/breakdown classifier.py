"""
BTC Reflex Engine — Breakdown Classifier
Reflex Sprint 3B-P1

Pure classification logic extracted from CompositeBreakdownDetector.
No I/O. No logging. No state. Fully deterministic and unit-testable.

This module exists so classification rules can be tested in isolation
without constructing BehavioralContext or BreakdownSignals objects.

Usage in tests:
    from app.engines.breakdown_classifier import classify_breakdown, SignalSet

    signals = SignalSet(trend_bearish=True, s_verdict=True, s_volume=True)
    level = classify_breakdown(signals)
    assert level == "BEARISH_BREAKDOWN_WATCH"
"""
from __future__ import annotations
from dataclasses import dataclass

# ── Constants (mirrors composite_breakdown_detector.py) ───────────────────────
BREAKDOWN_SIGNALS_WATCH = 2
BREAKDOWN_SIGNALS_HIGH  = 3

LEVEL_HIGH_RISK = "HIGH_RISK_BEARISH_BREAKDOWN"
LEVEL_WATCH     = "BEARISH_BREAKDOWN_WATCH"
LEVEL_NONE      = "none"


@dataclass(frozen=True)
class SignalSet:
    """
    Immutable input for classify_breakdown().
    All fields default to False — only set True signals explicitly.
    """
    trend_bearish:    bool = False   # required gate — classification skips if False
    s_verdict:        bool = False   # behavioral verdict is bearish-aligned
    s_volume:         bool = False   # volatility expansion above threshold
    s_choch:          bool = False   # bearish CHoCH detected
    s_rotation:       bool = False   # upper boundary + momentum decaying
    s_post_expansion: bool = False   # post_expansion regime amplifier

    @property
    def bearish_count(self) -> int:
        """Non-trend signal count (trend is a gate, not a scorer)."""
        return sum([self.s_verdict, self.s_volume, self.s_choch, self.s_rotation])


def classify_breakdown(signals: SignalSet) -> str:
    """
    Apply W25-04 approved classification rules.

    Pure function. No side effects. No logging. No state.

    Rules:
      HIGH_RISK: trend_bearish AND bearish_count >= 3
      HIGH_RISK: trend_bearish AND post_expansion AND bearish_count >= 2
      WATCH:     trend_bearish AND bearish_count >= 2
      None:      below threshold or trend not bearish

    Args:
        signals: SignalSet — immutable flag set for one evaluation

    Returns:
        str — one of LEVEL_HIGH_RISK, LEVEL_WATCH, LEVEL_NONE
    """
    if not signals.trend_bearish:
        return LEVEL_NONE

    count = signals.bearish_count

    if count >= BREAKDOWN_SIGNALS_HIGH:
        return LEVEL_HIGH_RISK

    if signals.s_post_expansion and count >= BREAKDOWN_SIGNALS_WATCH:
        return LEVEL_HIGH_RISK   # post_expansion amplifies WATCH → HIGH_RISK

    if count >= BREAKDOWN_SIGNALS_WATCH:
        return LEVEL_WATCH

    return LEVEL_NONE


def describe_signals(signals: SignalSet) -> dict:
    """
    Return a human-readable summary dict of a SignalSet.
    Useful for logging and testing assertions.
    """
    return {
        "trend_bearish":    signals.trend_bearish,
        "bearish_count":    signals.bearish_count,
        "s_verdict":        signals.s_verdict,
        "s_volume":         signals.s_volume,
        "s_choch":          signals.s_choch,
        "s_rotation":       signals.s_rotation,
        "s_post_expansion": signals.s_post_expansion,
        "level":            classify_breakdown(signals),
    }
