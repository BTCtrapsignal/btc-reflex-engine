# Sprint 3B-P1 — Deployment & Integration Guide

```
------------------------------------------------
System Owner:          Reflex
Project Sprint:        Reflex 3B-P1
Implementation Target: Reflex Engine (internal)
Signal Bot:            Read-only consumer — NOT modified
Status:                READY FOR DEPLOYMENT
Tests:                 57/57 passing
------------------------------------------------
```

---

## What This Sprint Delivers

A new `[breakdown]` observation channel inside the Reflex Engine.

When `BehavioralContext` contains simultaneous bearish signal confluence
(verdict + volatility expansion + CHoCH + rotation pressure), the
`CompositeBreakdownDetector` classifies the condition and surfaces a
structured Telegram alert through the existing Reflex notification path.

**The Signal Bot is not touched. Brain Ops is not touched.**

---

## Files to Commit

### New files — copy to these exact paths

| File (this package) | Destination in repo |
|---|---|
| `composite_breakdown_detector.py` | `app/engines/composite_breakdown_detector.py` |
| `breakdown_classifier.py` | `app/engines/breakdown_classifier.py` |
| `breakdown_event_logger.py` | `app/engines/breakdown_event_logger.py` |
| `test_sprint3b_p1.py` | `tests/test_sprint3b_p1.py` |

### Replace in place — complete file replacements

| File (this package) | Destination in repo |
|---|---|
| `scheduler.py` | `app/scheduler.py` |
| `config.py` | `app/config.py` |

Both files are complete replacements. No manual patching required.

---

## What Changed in scheduler.py

### Import (after Sprint 3A import)

```python
from app.journal.reflex_journal_exporter import ReflexJournalExporter  # Sprint 3A
from app.engines.composite_breakdown_detector import CompositeBreakdownDetector  # Sprint 3B-P1
```

### Instantiation (after Sprint 3A instance) — config-wired

```python
_journal_exporter    = ReflexJournalExporter()       # Sprint 3A
_breakdown_detector  = CompositeBreakdownDetector(   # Sprint 3B-P1
    cooldown_secs        = settings.breakdown_cooldown_secs,
    signals_watch        = settings.breakdown_signals_watch,
    signals_high         = settings.breakdown_signals_high,
    volume_expansion_min = settings.breakdown_volume_expansion_min,
)
```

### Call site (after step 8a, before step 9)

```python
        # ── 8a. Reflex Observation Journal — Sprint 3A ────────────────────────
        _journal_exporter.maybe_export(context)

        # ── 8b. Composite Breakdown Detector — Sprint 3B-P1 ──────────────────
        # Pure evaluation: BehavioralContext → BreakdownResult.
        # Detector owns NO actions. Scheduler owns surfacing decisions.
        _breakdown_result = _breakdown_detector.evaluate(context)
        if _breakdown_result.fired:
            _surface_breakdown_alert(_breakdown_result)

        # ── 9. Alert Gate — event-driven, no spam ─────────────────────────────
```

### New helper function (after `_log_observation`)

```python
def _surface_breakdown_alert(result) -> None:
    """
    Surface a fired BreakdownResult to Telegram.
    Scheduler owns this decision. Detector owns evaluation only.
    Observer mode only. Never modifies Signal Bot state.
    """
    try:
        from app.notifiers.telegram_reflex_bot import send_raw
        sent = send_raw(result.narrative)
        if sent:
            logger.info(
                "[breakdown] surfaced | level=%s signals=%d weight=%.3f",
                result.level,
                result.signals.bearish_count,
                result.weight,
            )
        else:
            logger.warning(
                "[breakdown] narrative not delivered (Telegram returned False) "
                "level=%s", result.level
            )
    except Exception as exc:
        logger.error("[breakdown] surface failed (non-fatal): %s", exc)
```

---

## What Changed in config.py

Added after the `alert_threshold` field:

```python
    # ── Composite Breakdown Detector (Sprint 3B-P1) ───────────────────────────
    breakdown_cooldown_secs: int = int(
        os.getenv("REFLEX_BREAKDOWN_COOLDOWN_SECS", "1800")
    )
    breakdown_signals_watch: int = int(
        os.getenv("REFLEX_BREAKDOWN_SIGNALS_WATCH", "2")
    )
    breakdown_signals_high: int = int(
        os.getenv("REFLEX_BREAKDOWN_SIGNALS_HIGH", "3")
    )
    breakdown_volume_expansion_min: float = float(
        os.getenv("REFLEX_BREAKDOWN_VOLUME_MIN", "0.55")
    )
```

No Railway ENV vars need to be set — all defaults match the approved design.

---

## Pre-Deployment Checklist

- [ ] Three new engine files copied to `app/engines/`
- [ ] Test file copied to `tests/`
- [ ] `app/scheduler.py` replaced with updated version
- [ ] `app/config.py` replaced with updated version
- [ ] `python -m pytest tests/test_sprint3b_p1.py` passes 57/57 locally
- [ ] No Railway ENV changes required (all defaults correct)
- [ ] Signal Bot repo: **not touched**
- [ ] Brain Ops: **not touched**

---

## Deployment

Commit all changes to `main`. Railway auto-deploys.

**Commit message:**

```
feat: Reflex Sprint 3B-P1 — Composite Breakdown Detector

Adds CompositeBreakdownDetector to Reflex Engine observation cycle.

Pure evaluation: BehavioralContext → BreakdownResult.
Scheduler surfaces fired results via existing Telegram interface.
Detector owns no I/O. Observer mode preserved throughout.

All four classification thresholds are ENV-configurable via
REFLEX_BREAKDOWN_* vars. Defaults match approved W25 design.

New files:
  app/engines/composite_breakdown_detector.py
  app/engines/breakdown_classifier.py
  app/engines/breakdown_event_logger.py
  tests/test_sprint3b_p1.py

Modified:
  app/scheduler.py  (+import, +instance config-wired, +call site, +_surface_breakdown_alert)
  app/config.py     (+4 REFLEX_BREAKDOWN_* constants)

Addresses W25-04 gap: OI surge + volume expansion + BEARISH verdict
converging simultaneously produced no synthesis. Now produces:
  HIGH_RISK_BEARISH_BREAKDOWN or BEARISH_BREAKDOWN_WATCH

Tests: 57/57 passing
Signal Bot: not modified
Brain Ops: not modified
```

---

## Post-Deployment Verification

Watch Railway Deploy Logs immediately after Active status.

### Required within first two observation cycles (≤ 30 min)

```
[breakdown] eval level=... signals=... trend=... verdict=... confidence=... weight=...
```

This line fires on **every** evaluation — fired or suppressed. Its presence
confirms the call site is wired and the detector is running.

### Expected log patterns

| Log line | Meaning |
|---|---|
| `[breakdown] eval level=none signals=0 trend=False ...` | Neutral market — correct, no alert |
| `[breakdown] eval level=none signals=1 trend=True ...` | BEARISH but below threshold — correct |
| `[breakdown] eval level=BEARISH_BREAKDOWN_WATCH ...` | WATCH fired — alert sent |
| `[breakdown] eval level=HIGH_RISK_BEARISH_BREAKDOWN ...` | HIGH_RISK fired — alert sent |
| `[breakdown] cooldown_active remaining=Nmin` | Post-alert cooldown — correct |
| `[breakdown] surfaced \| level=... signals=N weight=...` | Telegram delivered |
| `[breakdown] exception (non-fatal): ...` | Internal error — cycle continues |

### Failure indicator

If `[breakdown] eval` does **not** appear after two full observation cycles,
the scheduler.py replacement was not applied. Verify the file in the repo.

### Confirm existing behaviour unchanged

```
[HEARTBEAT] price=... structure=... phase=... weight=... | ...
[scheduler] Alert delivered ...    ← existing alerts continue
```

Neither line should change cadence or content.

---

## Signal Bot Integration (Read-Only)

The Signal Bot **consumes** Reflex output via Telegram only.
No code changes to Signal Bot are required or permitted.

The breakdown alert arrives in the same Telegram channel as existing
Reflex observations. It is visually distinct:

```
━━━ ⚠ BEARISH BREAKDOWN WATCH ━━━          ← WATCH level
━━━ 🚨 HIGH RISK BEARISH BREAKDOWN ━━━     ← HIGH_RISK level
```

Both end with:
```
─── Observer Mode — No Execution ───
Reflex observes. The trader decides.
```

The Signal Bot operator reads this as structural context alongside
the existing observation narrative. No signal bot logic reads or
parses Reflex output programmatically.

---

## Sprint 3B-P2 Opens After Deployment

Runtime validation begins once `[breakdown] eval` is confirmed in Railway logs.

Sprint 3B-P2 evidence collection uses `W26_RUNTIME_EVIDENCE.md`.
Closure criterion: 7-day observation with execution rate ≥ 95%, 0 exceptions,
0 false positives (non-BEARISH trend producing WATCH or HIGH_RISK).

---

*Reflex Sprint 3B-P1 — Deployment & Integration Guide*
*Observer mode only · No execution · No Signal Bot modification*
*W26 · BTC Ecosystem Governance*
