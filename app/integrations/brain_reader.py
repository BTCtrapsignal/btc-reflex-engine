"""
BTC Reflex Engine — Brain Reader (DISABLED — W22)

Brain Ops integration has been removed per W22 architecture correction.

Reflex must remain fully independent of Brain Ops.
Monitor v2 is the only component permitted to observe both systems.

This file is kept as a stub for potential future revert only.
It exports a NullBrainState that the assembler uses as a no-op placeholder.
The scheduler no longer calls fetch_brain_state().

TO REVERT: restore original implementation and re-enable in scheduler.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class BrainState:
    """Null stub — Brain integration disabled."""
    market_regime:      str   = "disabled"
    macro_bias:         str   = "disabled"
    confidence:         float = 0.0
    continuation_state: str   = "disabled"
    volatility_state:   str   = "disabled"
    risk_mode:          str   = "disabled"
    source:             str   = "disabled"


def fetch_brain_state(*args, **kwargs) -> BrainState:
    """Stub — always returns disabled state. Not called by scheduler."""
    return BrainState()
