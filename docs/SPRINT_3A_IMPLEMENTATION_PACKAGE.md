# BTC Reflex Engine — Sprint 3A Implementation Package
## Reflex Journal Export → Railway Volume

**Status:** IMPLEMENTATION COMPLETE — NOT DEPLOYED  
**W25:** Evidence collection continues unaffected  
**Prepared:** 2026-06-24 UTC  

---

## Governance

| Authority | System | Role |
|---|---|---|
| Deterministic authority | Brain Ops | Architecture decisions |
| Execution engine | Signal Bot | Trade signals |
| Observer only | Reflex | This sprint |
| Read-only | Monitor | Status endpoint |
| Communication | OPS | Telegram layer |

**Change control:** Runtime Evidence → Verified Finding → Root Cause → Code Change  
**Deployment gate:** W25 must close before production deployment.

---

## 1. Final Implementation Plan

### Objective
Extend the Reflex Engine observation cycle with an append-only journal exporter. On each qualifying cycle, the exporter writes two files to a Railway Volume mounted at `/journal`. No GitHub push. No Obsidian integration. No Monitor integration. Observer-only — zero impact on signal generation, Telegram, or database writes.

### Trigger Logic
```
C1: context.interpretation.verdict != _last_exported_verdict
C2: context.interpretation.confidence in ("MEDIUM", "HIGH")

Export fires when: C1 OR C2
```

### Output Targets
```
/journal/BTC-Brain/raw/REFLEX-DAY-{YYYY-MM-DD}.md     ← daily artifact
/journal/wiki/intelligence/Reflex_Observation_Journal.md ← index
```

### Failure Contract
- `maybe_export()` NEVER raises to the scheduler
- Any exception: logged at ERROR, swallowed, cycle continues
- `_last_exported_verdict` advances ONLY after both writes succeed
- DB write completes before exporter is called
- Alert gate and Telegram execute after exporter regardless of outcome

### State Design
- `_last_exported_verdict` is in-memory, module-level
- Resets on process restart — intentional; produces a clean re-entry on restart
- No persistent state store needed; Railway Volume holds the durable record

---

## 2. File-by-File Change List

| File | Action | Lines changed | Impact |
|---|---|---|---|
| `app/journal/__init__.py` | **Create** | 2 | None — package init only |
| `app/journal/reflex_journal_exporter.py` | **Create** | 266 | New module, no dependencies on existing logic |
| `app/config.py` | **Modify** | +5 lines | Adds `reflex_journal_dir` field only |
| `app/scheduler.py` | **Modify** | +4 lines | Import, instantiation, one call site |

**Files confirmed NOT modified:**
- `app/engines/context_assembler.py`
- `app/engines/interpretation_engine.py`
- `app/notifiers/alert_gate.py`
- `app/notifiers/telegram_reflex_bot.py`
- `app/database/models.py`
- `app/database/memory_layer.py`
- `app/database/extended_memory.py`
- `main.py`
- All engine files

---

## 3. Complete Patch Set

### Patch A — `app/journal/__init__.py` (NEW FILE)

```python
# app/journal — Reflex Observation Journal
# Sprint 3A: append-only behavioral observation export
```

---

### Patch B — `app/journal/reflex_journal_exporter.py` (NEW FILE)

```python
"""
BTC Reflex Engine — Reflex Observation Journal Exporter
Sprint 3A

Writes behavioral observations to two append-only file targets:

  1. Daily artifact:
       BTC-Brain/raw/REFLEX-DAY-{YYYY-MM-DD}.md
       Appended throughout the day. One file per calendar day (UTC).
       Contains full observation narrative + structured header.

  2. Intelligence journal index:
       wiki/intelligence/Reflex_Observation_Journal.md
       Single append-only index. One row per export. Cross-links to
       daily artifact. Never truncated, never rewritten.

━━━ EXPORT TRIGGERS ━━━

  C1: verdict transition
      context.interpretation.verdict != last_exported_verdict

  C2: confidence >= MEDIUM
      context.interpretation.confidence in ("MEDIUM", "HIGH")

  Export fires when: C1 OR C2

  Weight-based triggering removed entirely (approved W22 design).

━━━ FAILURE CONTRACT ━━━

  - Exporter NEVER raises to caller.
  - Any exception is caught, logged at ERROR, and swallowed.
  - Scheduler cycle, alert gate, Telegram, and DB writes are
    completely unaffected by any exporter failure.
  - last_exported_verdict is updated ONLY after both writes succeed.
    A partial write failure does not advance state — next cycle retries.

━━━ STATE DESIGN ━━━

  _last_exported_verdict is module-level in-memory state.
  Resets on process restart — intentional. First cycle after restart
  always triggers C1, producing a clean re-entry in the journal.
  This is correct and expected behaviour.

━━━ UTC EVERYWHERE ━━━

  All filenames, timestamps, and log entries use UTC.
  No local time references anywhere in this module.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

# ── Module-level state ────────────────────────────────────────────────────────
# Resets on process restart — intentional. See module docstring.
_last_exported_verdict: str = ""

# ── Confidence tier ordering for C2 evaluation ────────────────────────────────
_EXPORT_CONFIDENCE_TIERS = {"MEDIUM", "HIGH"}

# ── File path templates ───────────────────────────────────────────────────────
_DAILY_ARTIFACT_SUBPATH   = "BTC-Brain/raw/REFLEX-DAY-{date}.md"
_JOURNAL_INDEX_SUBPATH    = "wiki/intelligence/Reflex_Observation_Journal.md"

# ── Journal index header (written once on file creation) ─────────────────────
_JOURNAL_INDEX_HEADER = (
    "# Reflex Observation Journal\n"
    "\n"
    "Append-only index of exported Reflex behavioral observations.\n"
    "Each row cross-links to the daily artifact containing the full narrative.\n"
    "\n"
    "| Timestamp (UTC) | Verdict | Confidence | Weight | Structure | Trigger | Daily Artifact |\n"
    "|---|---|---|---|---|---|---|\n"
)


class ReflexJournalExporter:
    """
    Appends behavioral observations to the Reflex Observation Journal.

    Caller interface:
        exporter = ReflexJournalExporter()
        exporter.maybe_export(context)   # call once per cycle, after _log_observation

    Never raises. All failures are logged and swallowed internally.
    """

    def __init__(self) -> None:
        self._journal_dir = Path(getattr(settings, "reflex_journal_dir", "."))

    # ── Public API ─────────────────────────────────────────────────────────────

    def maybe_export(self, context) -> None:
        """
        Evaluate C1/C2 triggers and export if either fires.

        Must be called after _log_observation() and before alert_gate.evaluate().
        Failure of this method never propagates to the caller.

        Args:
            context: BehavioralContext — fully assembled observation for this cycle.
        """
        global _last_exported_verdict

        try:
            should, trigger_reason = self._should_export(context)

            if not should:
                logger.debug(
                    "[journal] Export suppressed | verdict=%s confidence=%s reason=%s",
                    context.interpretation.verdict,
                    context.interpretation.confidence,
                    trigger_reason,
                )
                return

            now_utc = datetime.now(timezone.utc)

            # ── Write daily artifact ──────────────────────────────────────────
            # Must succeed before state advances.
            self._append_daily_artifact(context, now_utc)

            # ── Write intelligence journal index ──────────────────────────────
            # Must succeed before state advances.
            self._append_journal_index(context, now_utc, trigger_reason)

            # ── Advance state — only after both writes succeed ─────────────────
            _last_exported_verdict = context.interpretation.verdict

            logger.info(
                "[journal] Exported | verdict=%s confidence=%s weight=%.3f trigger=%s",
                context.interpretation.verdict,
                context.interpretation.confidence,
                context.behavioral_weight,
                trigger_reason,
            )

        except Exception as exc:
            # Exporter failure is fully contained here.
            # Scheduler, alert gate, Telegram, and DB are unaffected.
            logger.error(
                "[journal] Export failed — cycle unaffected: %s", exc, exc_info=True
            )

    # ── Trigger Logic ──────────────────────────────────────────────────────────

    def _should_export(self, context) -> tuple[bool, str]:
        """
        Evaluate C1 and C2 triggers.

        C1: verdict transition    (current verdict != last exported verdict)
        C2: confidence >= MEDIUM  (confidence in {"MEDIUM", "HIGH"})

        Returns:
            (should_export: bool, reason: str)
        """
        verdict    = context.interpretation.verdict
        confidence = context.interpretation.confidence

        c1 = verdict != _last_exported_verdict
        c2 = confidence in _EXPORT_CONFIDENCE_TIERS

        if c1 and c2:
            return True, "C1+C2"
        if c1:
            return True, "C1"
        if c2:
            return True, "C2"
        return False, f"suppressed(verdict_unchanged,confidence={confidence})"

    # ── Daily Artifact ─────────────────────────────────────────────────────────

    def _append_daily_artifact(self, context, now_utc: datetime) -> None:
        """
        Append one observation entry to today's daily artifact file.

        Path: {journal_dir}/BTC-Brain/raw/REFLEX-DAY-{YYYY-MM-DD}.md
        Created on first write of the day. Appended on subsequent writes.
        Directory is created if absent.

        Entry format:
            ## HH:MM UTC — VERDICT (CONFIDENCE)

            {full narrative}

            ---
        """
        date_str = now_utc.strftime("%Y-%m-%d")
        time_str = now_utc.strftime("%H:%M")

        path = self._journal_dir / _DAILY_ARTIFACT_SUBPATH.format(date=date_str)
        os.makedirs(path.parent, exist_ok=True)

        verdict    = context.interpretation.verdict.replace("_", " ")
        confidence = context.interpretation.confidence

        entry = (
            f"## {time_str} UTC — {verdict} ({confidence})\n"
            f"\n"
            f"{context.narrative}\n"
            f"\n"
            f"---\n"
            f"\n"
        )

        with open(path, "a", encoding="utf-8") as f:
            f.write(entry)

        logger.debug("[journal] Daily artifact appended: %s", path)

    # ── Intelligence Journal Index ─────────────────────────────────────────────

    def _append_journal_index(
        self, context, now_utc: datetime, trigger_reason: str
    ) -> None:
        """
        Append one index row to the intelligence journal.

        Path: {journal_dir}/wiki/intelligence/Reflex_Observation_Journal.md
        Header row written once on file creation.
        All subsequent writes append one table row.
        Directory is created if absent.

        Row format:
            | YYYY-MM-DD HH:MM UTC | VERDICT | CONFIDENCE | weight | structure_type | trigger | [[REFLEX-DAY-YYYY-MM-DD]] |
        """
        path = self._journal_dir / _JOURNAL_INDEX_SUBPATH
        os.makedirs(path.parent, exist_ok=True)

        # Write header if file does not yet exist
        if not path.exists():
            with open(path, "w", encoding="utf-8") as f:
                f.write(_JOURNAL_INDEX_HEADER)
            logger.info("[journal] Intelligence journal created: %s", path)

        date_str      = now_utc.strftime("%Y-%m-%d")
        timestamp_str = now_utc.strftime("%Y-%m-%d %H:%M UTC")
        artifact_link = f"[[REFLEX-DAY-{date_str}]]"

        verdict        = context.interpretation.verdict
        confidence     = context.interpretation.confidence
        weight         = f"{context.behavioral_weight:.3f}"
        structure_type = context.structure_4h.structure_type.replace("_", " ")

        row = (
            f"| {timestamp_str} "
            f"| {verdict} "
            f"| {confidence} "
            f"| {weight} "
            f"| {structure_type} "
            f"| {trigger_reason} "
            f"| {artifact_link} |\n"
        )

        with open(path, "a", encoding="utf-8") as f:
            f.write(row)

        logger.debug("[journal] Index row appended: %s", path)
```

---

### Patch C — `app/config.py` (MODIFY)

Apply after the `alert_threshold` field (end of Settings class):

```diff
     # ── Alert threshold ───────────────────────────────────────────────────────
     # Minimum behavioral weight to trigger Telegram alert (0.0–1.0)
     alert_threshold: float = float(os.getenv("REFLEX_ALERT_THRESHOLD", "0.40"))
+
+    # ── Observation Journal (Sprint 3A) ───────────────────────────────────────
+    # Root directory for journal file output.
+    # Production: set REFLEX_JOURNAL_DIR=/journal (Railway Volume mount path)
+    # Daily artifact:  {dir}/BTC-Brain/raw/REFLEX-DAY-{YYYY-MM-DD}.md
+    # Journal index:   {dir}/wiki/intelligence/Reflex_Observation_Journal.md
+    reflex_journal_dir: str = os.getenv("REFLEX_JOURNAL_DIR", ".")
```

---

### Patch D — `app/scheduler.py` (MODIFY — 3 targeted additions)

**Addition 1 — Import block** (after `from app.monitor import runtime_state`):

```diff
 from app.monitor import runtime_state
+from app.journal.reflex_journal_exporter import ReflexJournalExporter
```

**Addition 2 — Engine instantiation block** (after `_ext_mem = ExtendedMemoryWriter()`):

```diff
 _ext_mem = ExtendedMemoryWriter()
+_journal_exporter = ReflexJournalExporter()
```

**Addition 3 — Call site** (after `_log_observation`, before `alert_gate.evaluate`):

```diff
         # ── 8. Log to Database ────────────────────────────────────────────────
         _log_observation(context, current_price)

+        # ── 8a. Reflex Observation Journal — Sprint 3A ────────────────────────
+        # Independent of alert gate. Evaluates C1/C2 triggers directly on context.
+        # Failure never propagates — exporter contains its own error boundary.
+        _journal_exporter.maybe_export(context)
+
         # ── 9. Alert Gate — event-driven, no spam ─────────────────────────────
         decision = alert_gate.evaluate(context)
```

---

## 4. Unit Test Coverage Map

**Test file:** `test_sprint3a.py`  
**Result:** 33 / 33 PASSED

| Group | ID | Scenario | Covers |
|---|---|---|---|
| 1 — Trigger Logic | T1.1 | Fresh start, MEDIUM verdict | C1+C2 fires |
| | T1.2 | Fresh start, LOW verdict | C1 only fires |
| | T1.3 | Same verdict, MEDIUM | C2 only fires |
| | T1.4 | Same verdict, LOW | Suppressed |
| | T1.5 | Verdict changes, LOW | C1 only fires |
| | T1.6 | Verdict changes, MEDIUM | C1+C2 fires |
| | T1.7 | NO_CLEAR_VERDICT stable, LOW | Suppressed |
| | T1.8 | Same verdict, HIGH | C2 only fires |
| 2 — File Output | T2.1 | Artifact file created | Path construction |
| | T2.2 | First entry header | Timestamp + verdict format |
| | T2.3 | Second entry header | Append behaviour |
| | T2.4 | Narrative content | context.narrative written |
| | T2.5 | Separator present | `---` between entries |
| | T2.6 | Entry count correct | Two writes = two entries |
| | T2.7 | Index file created | Path construction |
| | T2.8 | Index header present | First-write header |
| | T2.9 | Table header present | Column structure |
| | T2.10 | First data row | Field values |
| | T2.11 | Second data row | Append behaviour |
| | T2.12 | Artifact link format | `[[REFLEX-DAY-...]]` |
| | T2.13 | Trigger reason recorded | C1+C2 / C2 labels |
| | T2.14 | Weight precision | 3 decimal places |
| | T2.15 | Structure type | Field present |
| 3 — Dir Creation | T3.1 | Non-existent deep path, artifact | `makedirs(exist_ok=True)` |
| | T3.2 | Non-existent deep path, index | `makedirs(exist_ok=True)` |
| 4 — Failure Isolation | T4.1 | OSError does not propagate | Scheduler safety |
| | T4.2 | State not advanced after failure | No state corruption |
| 5 — State Sequencing | T5.1 | Partial write (index fails) | State not advanced |
| 6 — Restart | T6.1 | State empty after reset | In-memory reset |
| | T6.2 | Post-restart C1 fires | Re-entry on restart |
| 7 — UTC | T7.1 | Filename uses UTC date | Year-boundary date |
| | T7.2 | Artifact header UTC time | `HH:MM UTC` format |
| | T7.3 | Index row UTC timestamp | Full timestamp format |

**Coverage gaps (accepted):**
- No integration test against live Binance feed or real DB (out of scope — observer mode)
- No test for `>30 min C2 rate` scenario (design gap, Sprint 3B consideration)
- `test_sprint3a.py` hardcodes `/home/claude/sprint3a` path — not portable to CI without modification (known, accepted for Sprint 3A)

---

## 5. Runtime Verification Checklist

Execute after deployment. Do not proceed to production merge until all items pass.

### 5a — Railway Volume (pre-deploy)

- [ ] Railway Volume created in dashboard
- [ ] Volume attached to Reflex Engine service
- [ ] Volume mount path set to `/journal`
- [ ] Service restarted after volume attachment
- [ ] `REFLEX_JOURNAL_DIR=/journal` set in Railway ENV

### 5b — First cycle after deploy

Check Railway logs for one of:
- [ ] `[journal] Exported | verdict=... confidence=... weight=... trigger=...`
- [ ] `[journal] Export suppressed | verdict=... confidence=... reason=...`

Confirm absence of:
- [ ] `[journal] Export failed` — would indicate write error
- [ ] Any Python traceback referencing `reflex_journal_exporter`

### 5c — File existence on volume

Via Railway CLI:
```bash
railway volume files browse /journal
```
- [ ] `/journal/BTC-Brain/raw/` directory exists
- [ ] `REFLEX-DAY-{today-UTC}.md` file exists
- [ ] `/journal/wiki/intelligence/` directory exists
- [ ] `Reflex_Observation_Journal.md` file exists

### 5d — File content validation

```bash
railway volume files download /journal/wiki/intelligence/Reflex_Observation_Journal.md
```
- [ ] `# Reflex Observation Journal` header present
- [ ] Table header row present with correct columns
- [ ] At least one data row present
- [ ] Timestamp column format: `YYYY-MM-DD HH:MM UTC`
- [ ] Artifact link format: `[[REFLEX-DAY-YYYY-MM-DD]]`
- [ ] Trigger column contains `C1`, `C2`, or `C1+C2`

```bash
railway volume files download /journal/BTC-Brain/raw/REFLEX-DAY-{today}.md
```
- [ ] Entry header format: `## HH:MM UTC — VERDICT (CONFIDENCE)`
- [ ] Narrative block present (contains `BTC REFLEX OBSERVATION`)
- [ ] `---` separator present after entry

### 5e — Persistence across redeploy

- [ ] Trigger a Railway redeploy (push trivial commit)
- [ ] After redeploy, re-run Step 5c
- [ ] Files from before redeploy still present (not wiped)
- [ ] New entries appended after first post-redeploy cycle

### 5f — Isolation verification

Observe 3+ consecutive cycles in Railway logs:
- [ ] `[HEARTBEAT]` lines continue appearing on suppressed cycles
- [ ] Telegram alerts continue firing on qualifying cycles (unchanged behaviour)
- [ ] No increase in scheduler cycle time (export adds <50ms — negligible)
- [ ] No change to DB write behaviour
- [ ] No change to alert gate behaviour

### 5g — Negative test (failure path)

Temporarily rename `/journal` volume mount to a non-writable path (or temporarily revoke volume):
- [ ] `[journal] Export failed — cycle unaffected` appears in logs
- [ ] Scheduler continues running normally
- [ ] Telegram continues delivering alerts
- [ ] DB writes continue
- [ ] No crash, no `ERROR` outside of `[journal]` prefix

Restore volume mount. Confirm normal operation resumes on next cycle.

---

## 6. Production Deployment Checklist

**Gate condition: W25 must be closed before executing this checklist.**

### Pre-deploy

- [ ] W25 evidence collection window confirmed CLOSED
- [ ] Sprint 3A implementation package reviewed and signed off
- [ ] All 33 unit tests passing on local/staging run
- [ ] Railway Volume created and confirmed attached at `/journal`
- [ ] `REFLEX_JOURNAL_DIR=/journal` confirmed set in Railway ENV
- [ ] No other ENV changes required
- [ ] No database migrations required
- [ ] Signal Bot production service: confirmed UNCHANGED
- [ ] Brain Ops: confirmed UNCHANGED
- [ ] Monitor service: confirmed UNCHANGED

### Deploy

- [ ] Merge Sprint 3A branch to main
- [ ] Railway auto-deploys from GitHub (confirm trigger fires)
- [ ] Watch Railway build log — confirm no import errors on startup
- [ ] Confirm `━━━ BTC Reflex Engine ━━━` startup sequence completes
- [ ] Confirm first observation cycle completes in logs

### Post-deploy (Runtime Verification Checklist 5a–5g)

- [ ] 5b passed — journal log lines present
- [ ] 5c passed — files exist on volume
- [ ] 5d passed — file content valid
- [ ] 5e passed — persistence confirmed across redeploy
- [ ] 5f passed — isolation confirmed across 3+ cycles
- [ ] 5g passed — failure path confirmed safe

### Sign-off

- [ ] All checklist items green
- [ ] Sprint 3A declared COMPLETE
- [ ] Sprint 3B scope opened: git push automation, GitHub sync

---

## Out of Scope — Sprint 3B Queue

The following were explicitly excluded from Sprint 3A. They require no code changes to what has been deployed. Sprint 3B picks up here.

| Item | Description |
|---|---|
| Git push automation | Script to `git add / commit / push` journal files from `/journal` to GitHub on a schedule |
| GitHub synchronization | Files on Railway Volume become visible in browser |
| Obsidian integration | Cross-linking journal artifacts into Obsidian vault |
| BTC Monitor integration | Surfacing journal export status in the read-only monitor endpoint |
| C2 rate limiting | Optional minimum interval between consecutive C2-only exports |
| Test portability | Fix hardcoded path in `test_sprint3a.py` for CI compatibility |

---

## Audit Trail

| Phase | Status | Date |
|---|---|---|
| Architecture review | COMPLETE | W25 |
| Design review | COMPLETE | W25 |
| Implementation | COMPLETE | W25 |
| Implementation audit | COMPLETE — 0 defects | W25 |
| Configuration review | COMPLETE | W25 |
| Unit tests | COMPLETE — 33/33 PASSED | W25 |
| Production deployment | PENDING — W25 gate | — |
