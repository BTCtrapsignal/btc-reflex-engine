"""
Reflex Sprint 3B-P1 — Unit Tests (Refined)
Composite Breakdown Detector + Breakdown Classifier + Event Logger

Runs with: python -m pytest test_sprint3b_p1.py -v

Groups:
  1. classify_breakdown() pure function         — 8 tests
  2. _score_signals() normal inputs             — 8 tests
  3. _score_signals() defensive / malformed     — 8 tests
  4. _classify()                                — 4 tests
  5. Cooldown behaviour                         — 4 tests
  6. Failure isolation                          — 6 tests
  7. BreakdownEventLogger / CapturingLogger     — 5 tests
  8. _build_narrative output                    — 4 tests
  9. W25-04 gap replay                          — 2 tests

Total: 49 tests
"""
from __future__ import annotations
import sys, time, types, importlib, importlib.util, pathlib
from unittest.mock import MagicMock
import pytest

# ── Bootstrap: register modules under their real dotted names ─────────────────
# This is required so @dataclass(frozen=True) can resolve __module__.

def _register(filename: str, module_name: str):
    path = pathlib.Path("/mnt/user-data/outputs") / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod  = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod          # register BEFORE exec
    spec.loader.exec_module(mod)
    return mod


def _install_stubs() -> None:
    app = types.ModuleType("app")
    sys.modules.setdefault("app", app)
    for sub in [
        "app.config", "app.engines",
        "app.engines.context_assembler",
    ]:
        sys.modules.setdefault(sub, types.ModuleType(sub))
    sys.modules["app.engines.context_assembler"].BehavioralContext = object  # type: ignore


_install_stubs()

_clf = _register("breakdown_classifier.py",        "app.engines.breakdown_classifier")
_log = _register("breakdown_event_logger.py",       "app.engines.breakdown_event_logger")
_det = _register("composite_breakdown_detector.py", "app.engines.composite_breakdown_detector")

# Public aliases
SignalSet                     = _clf.SignalSet
classify_breakdown            = _clf.classify_breakdown
LEVEL_HIGH_RISK               = _clf.LEVEL_HIGH_RISK
LEVEL_WATCH                   = _clf.LEVEL_WATCH
LEVEL_NONE                    = _clf.LEVEL_NONE

CompositeBreakdownDetector    = _det.CompositeBreakdownDetector
BreakdownSignals              = _det.BreakdownSignals
BreakdownResult               = _det.BreakdownResult
_build_narrative              = _det._build_narrative

CapturingBreakdownEventLogger = _log.CapturingBreakdownEventLogger


# ── Context factory ───────────────────────────────────────────────────────────

def ctx(**kw) -> MagicMock:
    d = dict(
        verdict="PRESSURE_ACCUMULATING", confidence="HIGH", weight=0.62,
        expansion_score=0.60, vol_state="expanding",
        choch_detected=False, choch_direction="none", broken_level=None,
        rotation_boundary="upper", momentum_decaying=True, proximity_pct=0.02,
        structure_type="ranging", structure_phase="mature",
        s1h_type="ranging", s1h_phase="mid",
    )
    d.update(kw)
    c = MagicMock()
    c.interpretation.verdict      = d["verdict"]
    c.interpretation.confidence   = d["confidence"]
    c.behavioral_weight           = d["weight"]
    c.volatility.expansion_score  = d["expansion_score"]
    c.volatility.state            = d["vol_state"]
    c.volatility.compression_score = 0.0
    c.choch.choch_detected        = d["choch_detected"]
    c.choch.choch_direction       = d["choch_direction"]
    c.choch.broken_level          = d["broken_level"]
    c.rotation.boundary           = d["rotation_boundary"]
    c.rotation.momentum_decaying  = d["momentum_decaying"]
    c.rotation.proximity_pct      = d["proximity_pct"]
    c.structure_4h.structure_type = d["structure_type"]
    c.structure_4h.phase          = d["structure_phase"]
    c.structure_1h.structure_type = d["s1h_type"]
    c.structure_1h.phase          = d["s1h_phase"]
    return c


def make_det() -> tuple[CompositeBreakdownDetector, CapturingBreakdownEventLogger]:
    log = CapturingBreakdownEventLogger()
    det = CompositeBreakdownDetector(event_logger=log)
    return det, log


# ══════════════════════════════════════════════════════════════
# GROUP 1 — classify_breakdown() pure function
# ══════════════════════════════════════════════════════════════

class TestClassify:

    def test_no_trend_always_none(self):
        s = SignalSet(trend_bearish=False, s_verdict=True, s_volume=True, s_choch=True)
        assert classify_breakdown(s) == LEVEL_NONE

    def test_trend_two_gives_watch(self):
        s = SignalSet(trend_bearish=True, s_verdict=True, s_volume=True)
        assert classify_breakdown(s) == LEVEL_WATCH

    def test_trend_three_gives_high_risk(self):
        s = SignalSet(trend_bearish=True, s_verdict=True, s_volume=True, s_choch=True)
        assert classify_breakdown(s) == LEVEL_HIGH_RISK

    def test_trend_one_gives_none(self):
        s = SignalSet(trend_bearish=True, s_verdict=True)
        assert classify_breakdown(s) == LEVEL_NONE

    def test_post_exp_amplifies_count2(self):
        s = SignalSet(trend_bearish=True, s_verdict=True, s_volume=True, s_post_expansion=True)
        assert classify_breakdown(s) == LEVEL_HIGH_RISK

    def test_post_exp_count1_still_none(self):
        s = SignalSet(trend_bearish=True, s_verdict=True, s_post_expansion=True)
        assert classify_breakdown(s) == LEVEL_NONE

    def test_all_signals_high_risk(self):
        s = SignalSet(
            trend_bearish=True, s_verdict=True, s_volume=True,
            s_choch=True, s_rotation=True, s_post_expansion=True,
        )
        assert classify_breakdown(s) == LEVEL_HIGH_RISK

    def test_empty_none(self):
        assert classify_breakdown(SignalSet()) == LEVEL_NONE


# ══════════════════════════════════════════════════════════════
# GROUP 2 — _score_signals() normal inputs
# ══════════════════════════════════════════════════════════════

class TestScoreNormal:

    def setup_method(self): self.d, _ = make_det()

    def test_pressure_accumulating_bearish(self):
        s = self.d._score_signals(ctx(verdict="PRESSURE_ACCUMULATING"))
        assert s.trend_bearish and s.s_verdict

    def test_no_clear_verdict_not_bearish(self):
        s = self.d._score_signals(ctx(verdict="NO_CLEAR_VERDICT"))
        assert not s.trend_bearish and not s.s_verdict

    def test_high_expansion_score_volume(self):
        s = self.d._score_signals(ctx(expansion_score=0.70, vol_state="stable"))
        assert s.s_volume

    def test_expanding_state_volume_regardless_of_score(self):
        s = self.d._score_signals(ctx(expansion_score=0.10, vol_state="expanding"))
        assert s.s_volume

    def test_low_score_compressing_no_volume(self):
        s = self.d._score_signals(ctx(expansion_score=0.20, vol_state="compressing"))
        assert not s.s_volume

    def test_bearish_choch_sets_flag(self):
        s = self.d._score_signals(ctx(choch_detected=True, choch_direction="bearish_shift"))
        assert s.s_choch

    def test_bullish_choch_no_flag(self):
        s = self.d._score_signals(ctx(choch_detected=True, choch_direction="bullish_shift"))
        assert not s.s_choch

    def test_upper_boundary_decaying_rotation(self):
        s = self.d._score_signals(ctx(rotation_boundary="upper", momentum_decaying=True))
        assert s.s_rotation


# ══════════════════════════════════════════════════════════════
# GROUP 3 — _score_signals() defensive / malformed inputs
# ══════════════════════════════════════════════════════════════

class TestScoreDefensive:

    def setup_method(self): self.d, _ = make_det()

    def test_none_context_returns_safe_signals(self):
        s = self.d._score_signals(None)
        assert isinstance(s, BreakdownSignals) and not s.trend_bearish

    def test_empty_object_returns_safe_signals(self):
        s = self.d._score_signals(object())
        assert s.bearish_count == 0

    def test_nan_expansion_no_volume(self):
        c = ctx(); c.volatility.expansion_score = float("nan"); c.volatility.state = "stable"
        s = self.d._score_signals(c)
        assert not s.s_volume

    def test_inf_expansion_no_volume(self):
        c = ctx(); c.volatility.expansion_score = float("inf"); c.volatility.state = "stable"
        s = self.d._score_signals(c)
        assert not s.s_volume

    def test_none_expansion_no_volume(self):
        # expansion_score=None and vol_state="stable" → s_volume must be False
        # (if vol_state were "expanding", s_volume=True is correct behaviour)
        c = ctx(expansion_score=0.60, vol_state="stable")
        c.volatility.expansion_score = None  # type: ignore
        s = self.d._score_signals(c)
        assert not s.s_volume

    def test_invalid_confidence_clamped_to_low(self):
        r = self.d.evaluate(ctx(confidence="EXTREME"))
        assert r.confidence == "LOW"

    def test_missing_choch_attribute_safe(self):
        c = MagicMock()
        c.interpretation.verdict      = "PRESSURE_ACCUMULATING"
        c.interpretation.confidence   = "HIGH"
        c.behavioral_weight           = 0.5
        c.volatility.expansion_score  = 0.6
        c.volatility.state            = "expanding"
        c.rotation.boundary           = "upper"
        c.rotation.momentum_decaying  = True
        del c.choch
        s = self.d._score_signals(c)
        assert not s.s_choch

    def test_string_weight_returns_zero(self):
        c = ctx(); c.behavioral_weight = "not_a_number"  # type: ignore
        r = self.d.evaluate(c)
        assert r.weight == 0.0


# ══════════════════════════════════════════════════════════════
# GROUP 4 — _classify()
# ══════════════════════════════════════════════════════════════

class TestDetectorClassify:

    def setup_method(self): self.d, _ = make_det()

    def test_count3_high_risk(self):
        s = BreakdownSignals(trend_bearish=True, s_verdict=True, s_volume=True, s_choch=True)
        assert self.d._classify(s) == LEVEL_HIGH_RISK

    def test_count2_watch(self):
        s = BreakdownSignals(trend_bearish=True, s_verdict=True, s_volume=True)
        assert self.d._classify(s) == LEVEL_WATCH

    def test_no_trend_none(self):
        s = BreakdownSignals(trend_bearish=False, s_verdict=True, s_volume=True)
        assert self.d._classify(s) == LEVEL_NONE

    def test_count1_none(self):
        s = BreakdownSignals(trend_bearish=True, s_verdict=True)
        assert self.d._classify(s) == LEVEL_NONE


# ══════════════════════════════════════════════════════════════
# GROUP 5 — Cooldown behaviour
# ══════════════════════════════════════════════════════════════

class TestCooldown:

    def test_fresh_detector_not_in_cooldown(self):
        d, _ = make_det()
        r = d.evaluate(ctx(expansion_score=0.70))
        assert not r.cooldown_active

    def test_after_fired_next_is_cooldown(self):
        d, _ = make_det()
        d._last_alert_ts = time.time()
        r = d.evaluate(ctx(expansion_score=0.70))
        assert r.cooldown_active and not r.fired

    def test_reset_clears_timestamp(self):
        d, _ = make_det()
        d._last_alert_ts = time.time()
        d.reset_cooldown()
        assert d._last_alert_ts == 0.0

    def test_cooldown_event_logged(self):
        d, log = make_det()
        d._last_alert_ts = time.time()
        d.evaluate(ctx(expansion_score=0.70))
        assert log.cooldowns == 1
        assert log.events[0]["type"] == "cooldown"


# ══════════════════════════════════════════════════════════════
# GROUP 6 — Failure isolation
# ══════════════════════════════════════════════════════════════

class TestIsolation:

    def test_none_context_returns_safe_result(self):
        d, _ = make_det()
        r = d.evaluate(None)
        assert isinstance(r, BreakdownResult) and not r.fired

    def test_empty_object_context_safe(self):
        d, _ = make_det()
        r = d.evaluate(object())
        assert not r.fired

    def test_exception_captured_in_logger(self):
        d, log = make_det()
        class Bang:
            def __getattr__(self, item): raise RuntimeError("forced bang")
        d.evaluate(Bang())
        assert len(log.exceptions) >= 1 and "forced bang" in log.exceptions[0]

    def test_exception_does_not_propagate(self):
        d, _ = make_det()
        try:
            d.evaluate(None)
        except Exception as e:
            pytest.fail(f"evaluate() propagated: {e}")

    def test_result_always_returned(self):
        d, _ = make_det()
        r = d.evaluate(None)
        assert r is not None and hasattr(r, "fired") and hasattr(r, "level")

    def test_cooldown_ts_not_advanced_on_exception(self):
        d, _ = make_det()
        original = d._last_alert_ts
        d.evaluate(None)
        assert d._last_alert_ts == original


# ══════════════════════════════════════════════════════════════
# GROUP 7 — CapturingBreakdownEventLogger
# ══════════════════════════════════════════════════════════════

class TestLogger:

    def test_records_evaluation(self):
        d, log = make_det()
        d.evaluate(ctx(expansion_score=0.70))
        assert any(e["type"] == "evaluation" for e in log.events)

    def test_records_level(self):
        d, log = make_det()
        d.evaluate(ctx(
            expansion_score=0.70,
            choch_detected=True, choch_direction="bearish_shift",
        ))
        assert log.last_level in (LEVEL_WATCH, LEVEL_HIGH_RISK)

    def test_records_cooldown(self):
        d, log = make_det()
        d._last_alert_ts = time.time()
        d.evaluate(ctx(expansion_score=0.70))
        assert log.cooldowns == 1

    def test_records_exception(self):
        # None is handled gracefully (returns BreakdownResult, no exception logged).
        # To reliably trigger the exception path, use an object that raises on getattr.
        d, log = make_det()
        class Bang:
            def __getattr__(self, item): raise RuntimeError("forced bang")
        d.evaluate(Bang())
        assert len(log.exceptions) >= 1

    def test_reset(self):
        d, log = make_det()
        d.evaluate(ctx())
        log.reset()
        assert log.events == [] and log.last_level == "" and log.cooldowns == 0


# ══════════════════════════════════════════════════════════════
# GROUP 8 — _build_narrative output
# ══════════════════════════════════════════════════════════════

class TestNarrative:

    def _sw(self): return BreakdownSignals(trend_bearish=True, s_verdict=True, s_volume=True)
    def _hi(self): return BreakdownSignals(trend_bearish=True, s_verdict=True, s_volume=True, s_choch=True)

    def test_watch_title(self):
        assert "BEARISH BREAKDOWN WATCH" in _build_narrative(LEVEL_WATCH, ctx(), self._sw())

    def test_high_risk_title(self):
        assert "HIGH RISK BEARISH BREAKDOWN" in _build_narrative(LEVEL_HIGH_RISK, ctx(), self._hi())

    def test_observer_disclaimer_always_present(self):
        for level, sig in [(LEVEL_WATCH, self._sw()), (LEVEL_HIGH_RISK, self._hi())]:
            n = _build_narrative(level, ctx(), sig)
            assert "Observer Mode" in n and "Reflex observes" in n

    def test_no_trade_commands_in_narrative(self):
        for level, sig in [(LEVEL_WATCH, self._sw()), (LEVEL_HIGH_RISK, self._hi())]:
            n = _build_narrative(level, ctx(), sig).upper()
            for forbidden in ("BUY", "SELL", "LONG ", "SHORT ", "EXECUTE", "ENTER"):
                assert forbidden not in n, f"Forbidden word '{forbidden}' in narrative"


# ══════════════════════════════════════════════════════════════
# GROUP 9 — W25-04 gap replay
# ══════════════════════════════════════════════════════════════

class TestW25Replay:

    def test_w25_04_conditions_produce_high_risk(self):
        """
        Evidence: W25 EV-001, EV-002, EV-003, CF-01
        OI +8.1% + Volume x3.6 + BEARISH + post_expansion
        → must produce HIGH_RISK_BEARISH_BREAKDOWN
        """
        d, log = make_det()
        c = ctx(
            verdict="PRESSURE_ACCUMULATING", confidence="HIGH", weight=0.68,
            expansion_score=0.72, vol_state="post_expansion",
            choch_detected=False,
            rotation_boundary="upper", momentum_decaying=True,
        )
        r = d.evaluate(c)
        assert r.fired, f"Expected fired=True, got fired={r.fired} level={r.level}"
        assert r.level == LEVEL_HIGH_RISK, f"Expected HIGH_RISK, got {r.level}"
        assert r.signals.trend_bearish
        assert r.signals.s_volume
        assert r.signals.s_post_expansion
        assert r.signals.bearish_count >= 2
        assert "HIGH RISK BEARISH BREAKDOWN" in r.narrative
        assert log.last_level == LEVEL_HIGH_RISK

    def test_pre_detector_gap_confirmed(self):
        """
        Without trend gate (pre-3B-P1): no synthesis → NONE.
        Documents the W25-04 gap this sprint closes.
        """
        s = SignalSet(
            trend_bearish=False,  # no synthesis path existed
            s_verdict=True, s_volume=True, s_post_expansion=True,
        )
        assert classify_breakdown(s) == LEVEL_NONE


# ══════════════════════════════════════════════════════════════
# GROUP 10 — Custom config values are actually used
# ══════════════════════════════════════════════════════════════

class TestCustomConfig:
    """
    Proves that constructor parameters are wired into runtime behaviour.
    Each test overrides exactly one threshold and confirms the change
    is observable — classification behavior changes accordingly.
    """

    # ── signals_watch ──────────────────────────────────────────────────────────

    def test_custom_signals_watch_raises_threshold(self):
        """
        Default WATCH threshold = 2.
        With signals_watch=3, count=2 must produce NONE not WATCH.

        Exact signal count = 2 requires:
          s_verdict=True  (PRESSURE_ACCUMULATING)
          s_volume=True   (expansion_score=0.70)
          s_choch=False   (choch_detected=False)
          s_rotation=False (boundary="lower")
          s_post_expansion=False (vol_state="stable")
        bearish_count=2, no amplifier → threshold=3 should give NONE.
        """
        log = CapturingBreakdownEventLogger()
        det = CompositeBreakdownDetector(signals_watch=3, signals_high=4, event_logger=log)
        r = det.evaluate(ctx(
            expansion_score=0.70, vol_state="stable",
            choch_detected=False,
            rotation_boundary="lower", momentum_decaying=False,
        ))
        assert r.level == LEVEL_NONE, (
            f"signals_watch=3 should require 3 signals for WATCH, got {r.level}"
        )

    def test_custom_signals_watch_lowers_threshold(self):
        """
        With signals_watch=1, a single non-trend signal must produce WATCH.
        """
        log = CapturingBreakdownEventLogger()
        det = CompositeBreakdownDetector(signals_watch=1, signals_high=3, event_logger=log)
        # verdict only → bearish_count=1, trend_bearish=True
        r = det.evaluate(ctx(
            expansion_score=0.10, vol_state="compressing",
            choch_detected=False,
            rotation_boundary="lower", momentum_decaying=False,
        ))
        assert r.level in (LEVEL_WATCH, LEVEL_HIGH_RISK), (
            f"signals_watch=1 should fire on 1 signal, got {r.level}"
        )

    # ── signals_high ───────────────────────────────────────────────────────────

    def test_custom_signals_high_raises_threshold(self):
        """
        Default HIGH threshold = 3.
        With signals_high=4, count=3 must produce WATCH not HIGH_RISK.

        Exact signal count = 3 requires:
          s_verdict=True  (PRESSURE_ACCUMULATING)
          s_volume=True   (expansion_score=0.70)
          s_choch=True    (bearish_shift)
          s_rotation=False (boundary="lower")
          s_post_expansion=False (vol_state="stable")
        bearish_count=3, no amplifier → threshold=4 should give WATCH not HIGH_RISK.
        """
        log = CapturingBreakdownEventLogger()
        det = CompositeBreakdownDetector(signals_watch=2, signals_high=4, event_logger=log)
        r = det.evaluate(ctx(
            expansion_score=0.70, vol_state="stable",
            choch_detected=True, choch_direction="bearish_shift",
            rotation_boundary="lower", momentum_decaying=False,
        ))
        assert r.level == LEVEL_WATCH, (
            f"signals_high=4 should require 4 signals for HIGH_RISK, got {r.level}"
        )

    # ── volume_expansion_min ───────────────────────────────────────────────────

    def test_custom_volume_expansion_min_raises_threshold(self):
        """
        Default volume threshold = 0.55.
        With volume_expansion_min=0.80, score=0.70 + stable state must NOT set s_volume.
        """
        log = CapturingBreakdownEventLogger()
        det = CompositeBreakdownDetector(volume_expansion_min=0.80, event_logger=log)
        r = det.evaluate(ctx(expansion_score=0.70, vol_state="stable"))
        assert not r.signals.s_volume, (
            "volume_expansion_min=0.80 should not flag score=0.70 as volume expansion"
        )

    def test_custom_volume_expansion_min_lowers_threshold(self):
        """
        With volume_expansion_min=0.30, score=0.40 + stable state must set s_volume.
        """
        log = CapturingBreakdownEventLogger()
        det = CompositeBreakdownDetector(volume_expansion_min=0.30, event_logger=log)
        r = det.evaluate(ctx(expansion_score=0.40, vol_state="stable"))
        assert r.signals.s_volume, (
            "volume_expansion_min=0.30 should flag score=0.40 as volume expansion"
        )

    # ── cooldown_secs ──────────────────────────────────────────────────────────

    def test_custom_cooldown_secs_respected(self):
        """
        With cooldown_secs=9999, a detector whose _last_alert_ts was set
        1 second ago must report cooldown_active=True.
        """
        import time
        log = CapturingBreakdownEventLogger()
        det = CompositeBreakdownDetector(cooldown_secs=9999, event_logger=log)
        det._last_alert_ts = time.time() - 1   # 1 second elapsed < 9999
        r = det.evaluate(ctx(expansion_score=0.70))
        assert r.cooldown_active, "cooldown_secs=9999 should still be in cooldown after 1s"

    def test_custom_cooldown_zero_never_in_cooldown(self):
        """
        With cooldown_secs=0, cooldown is effectively disabled.
        Even immediately after firing, next call must not be suppressed.
        """
        import time
        log = CapturingBreakdownEventLogger()
        det = CompositeBreakdownDetector(cooldown_secs=0, event_logger=log)
        det._last_alert_ts = time.time()   # just fired
        r = det.evaluate(ctx(expansion_score=0.70))
        assert not r.cooldown_active, "cooldown_secs=0 should never suppress"

    # ── defaults unchanged ─────────────────────────────────────────────────────

    def test_defaults_match_approved_constants(self):
        """
        Constructor with no arguments must behave identically to the
        module-level constants — no regression from config wiring.
        """
        det = CompositeBreakdownDetector()
        assert det._cooldown_secs        == 1800
        assert det._signals_watch        == 2
        assert det._signals_high         == 3
        assert det._volume_expansion_min == 0.55
