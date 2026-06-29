# CHANGELOG — Reflex Sprint 3B-P1

```
------------------------------------------------
System Owner:          Reflex
Project Sprint:        Reflex 3B-P1
Implementation Target: Reflex Engine (internal)
Signal Bot:            Read-only consumer via existing Telegram interface
Version:               Reflex v1.1
Status:                IMPLEMENTATION COMPLETE — 57/57 tests passing
Addresses:             W25-04 confirmed gap — composite synthesis absent
------------------------------------------------
```

---

## Summary

Sprint 3B-P1 implements the Composite Breakdown Detector inside the Reflex Engine. When multiple simultaneous bearish behavioral signals converge — verdict, volatility expansion, CHoCH, rotation pressure — the detector synthesises them into a single directional observation alert and surfaces it via the existing Reflex Telegram interface.

The Signal Bot is not modified. Brain Ops is not modified. No thresholds are changed. Observer mode is preserved throughout.

---

## New Files

| File | Location | Purpose |
|---|---|---|
| `composite_breakdown_detector.py` | `app/engines/` | Pure evaluation engine — `BehavioralContext → BreakdownResult` |
| `breakdown_classifier.py` | `app/engines/` | Standalone classification logic — testable without engine dependencies |
| `breakdown_event_logger.py` | `app/engines/` | Centralised logging interface — all `[breakdown]` log lines route here |
| `test_sprint3b_p1.py` | `tests/` | 57 unit tests — classification, scoring, defensive, cooldown, W25-04 replay, config wiring |

---

## Modified Files

| File | Change | Lines added |
|---|---|---|
| `app/scheduler.py` | Import + instantiation (config-wired) + call site + `_surface_breakdown_alert()` | +21 |
| `app/config.py` | 4 new ENV-configurable constants with `REFLEX_` prefix | +10 |

---

## Architecture

```
run_observation_cycle()
    │
    ├── [existing engines unchanged]
    │
    ├── _assembler.assemble() → context
    ├── _log_observation(context)           ← DB write
    ├── _journal_exporter.maybe_export()    ← Sprint 3A
    │
    ├── _breakdown_detector.evaluate(context)   ← Sprint 3B-P1 NEW
    │       │
    │       │  Pure evaluation only:
    │       │  BehavioralContext → BreakdownResult
    │       │  No I/O. No Telegram. No state mutation beyond cooldown.
    │       │
    │       └── BreakdownResult(fired, level, narrative, signals, ...)
    │
    ├── if result.fired:
    │       _surface_breakdown_alert(result)    ← scheduler owns surfacing
    │           └── send_raw(result.narrative)
    │
    └── alert_gate.evaluate(context)        ← unchanged
```

---

## Classification Rules

```
Inputs (all from BehavioralContext — no new API calls):
  s_verdict   : interpretation.verdict in BEARISH_ALIGNED_VERDICTS
  s_volume    : volatility.expansion_score >= 0.55 OR state == "expanding"
  s_choch     : choch.choch_detected AND choch_direction == "bearish_shift"
  s_rotation  : rotation.boundary == "upper" AND momentum_decaying
  s_post_exp  : volatility.state in {"post_expansion", "expanding"}

  trend_bearish = s_verdict  (gate — classification aborts if False)
  bearish_count = sum(s_verdict, s_volume, s_choch, s_rotation)

Classification:
  HIGH_RISK : trend_bearish AND count >= 3
  HIGH_RISK : trend_bearish AND s_post_expansion AND count >= 2
  WATCH     : trend_bearish AND count >= 2
  none      : below threshold
```

---

## Config Wiring

All four thresholds are ENV-configurable via `app/config.py` and passed to
`CompositeBreakdownDetector` at instantiation. No Railway ENV changes are
required — all defaults match the approved W25 design parameters.

```python
_breakdown_detector = CompositeBreakdownDetector(
    cooldown_secs        = settings.breakdown_cooldown_secs,       # 1800
    signals_watch        = settings.breakdown_signals_watch,       # 2
    signals_high         = settings.breakdown_signals_high,        # 3
    volume_expansion_min = settings.breakdown_volume_expansion_min, # 0.55
)
```

---

## W25-04 Replay Verification

The confirmed W25 gap (EV-001, EV-002, EV-003) is tested directly:

```
OI +8.1%    → expansion_score=0.72 → s_volume=True
Volume x3.6 → vol_state=post_expansion → s_post_expansion=True
BEARISH     → verdict=PRESSURE_ACCUMULATING → trend_bearish=True
              → s_verdict=True
bearish_count = 2, s_post_expansion = True
→ HIGH_RISK_BEARISH_BREAKDOWN  ✓  (test_w25_04_conditions_produce_high_risk)
```

---

## Runtime Log Signatures

Sprint 3B-P2 observation uses these signatures as primary evidence:

```
[breakdown] eval level=HIGH_RISK_BEARISH_BREAKDOWN signals=3 trend=True ...
[breakdown] eval level=BEARISH_BREAKDOWN_WATCH signals=2 trend=True ...
[breakdown] eval level=none signals=1 trend=True ...
[breakdown] cooldown_active remaining=Nmin
[breakdown] surfaced | level=... signals=N weight=...
[breakdown] exception (non-fatal): ...
```

Absence of `[breakdown] eval` after two observation cycles = call site not wired.

---

## ENV Variables Added

| Variable | Default | Description |
|---|---|---|
| `REFLEX_BREAKDOWN_COOLDOWN_SECS` | `1800` | Seconds between breakdown alerts |
| `REFLEX_BREAKDOWN_SIGNALS_WATCH` | `2` | Min non-trend signals for WATCH |
| `REFLEX_BREAKDOWN_SIGNALS_HIGH` | `3` | Min non-trend signals for HIGH_RISK |
| `REFLEX_BREAKDOWN_VOLUME_MIN` | `0.55` | Min expansion_score for volume flag |

All optional. Defaults match approved W25 design parameters.

---

## Isolation Guarantees

| System | Modified | Notes |
|---|---|---|
| BTC Signal Bot | **NO** | Read-only consumer via Telegram |
| Brain Ops | **NO** | No interaction |
| Alert gate | **NO** | Breakdown runs before gate, independently |
| Journal exporter | **NO** | Both run sequentially, no shared state |
| DB writes | **NO** | `_log_observation` completes before detector runs |
| Observer mode | **PRESERVED** | No execution path modified |

---

## Test Results

```
57 passed, 0 failed
Coverage:
  Classification logic (pure)     8/8
  Signal scoring — normal         8/8
  Signal scoring — defensive      8/8  (None, NaN, Inf, missing attrs, invalid types)
  Classifier via detector         4/4
  Cooldown                        4/4
  Failure isolation               6/6
  Event logger / CapturingLogger  5/5
  Narrative output                4/4
  W25-04 gap replay               2/2
  Config wiring (Group 10)        8/8
```

---

## Deployment Order

See `SPRINT_3B_P1_DEPLOYMENT_GUIDE.md` for step-by-step instructions.

Short form:
1. Copy 3 new files to `app/engines/`
2. Copy test file to `tests/`
3. Replace `app/scheduler.py` with updated version
4. Replace `app/config.py` with updated version
5. Run tests locally — confirm 57/57
6. Commit and push — Railway redeploys
7. Verify `[breakdown] eval` in Railway logs within two observation cycles

---

*Reflex Sprint 3B-P1 · CHANGELOG*
*Observer mode only · No execution · No Signal Bot modification*
*W26 · BTC Ecosystem Governance*
