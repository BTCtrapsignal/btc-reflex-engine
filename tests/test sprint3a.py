"""
Sprint 3A Verification Tests — ReflexJournalExporter
"""
import os, sys, types, tempfile, importlib, importlib.util
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

# ── Bootstrap: register app package from disk, stub app.config ────────────────
sys.path.insert(0, "/home/claude/sprint3a")

spec = importlib.util.spec_from_file_location(
    "app", "/home/claude/sprint3a/app/__init__.py",
    submodule_search_locations=["/home/claude/sprint3a/app"]
)
app_mod = importlib.util.module_from_spec(spec)
sys.modules["app"] = app_mod
spec.loader.exec_module(app_mod)

mock_settings = MagicMock()
mock_settings.reflex_journal_dir = "."

config_mod = types.ModuleType("app.config")
config_mod.settings = mock_settings
sys.modules["app.config"] = config_mod
app_mod.config = config_mod

import app.journal.reflex_journal_exporter as exporter_mod
from app.journal.reflex_journal_exporter import ReflexJournalExporter

# ── Helpers ───────────────────────────────────────────────────────────────────

def make_context(verdict, confidence, weight=0.55, structure_type="ranging"):
    ctx = MagicMock()
    ctx.interpretation.verdict    = verdict
    ctx.interpretation.confidence = confidence
    ctx.behavioral_weight         = weight
    ctx.structure_4h.structure_type = structure_type
    ctx.narrative = (
        f"━━━ BTC REFLEX OBSERVATION ━━━\n"
        f"Symbol: BTCUSDT  |  Price: $67,000.00\n\n"
        f"🧠 BEHAVIORAL INTERPRETATION\n"
        f"  Verdict:    {verdict.replace('_', ' ')}\n"
        f"  Confidence: {confidence}\n"
        f"  Reading:    Test observation.\n\n"
        f"─── Observer Mode — No Execution ───\n"
        f"Reflex observes. The trader decides."
    )
    return ctx

def reset_state():
    exporter_mod._last_exported_verdict = ""

PASS, FAIL = "✓", "✗"
results = []

def check(name, condition, detail=""):
    status = PASS if condition else FAIL
    results.append((status, name, detail))
    print(f"  {status}  {name}" + (f" — {detail}" if detail else ""))

# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 1: Trigger Logic
# ═══════════════════════════════════════════════════════════════════════════════
print("\n━━━ GROUP 1: Trigger Logic ━━━")
exp = ReflexJournalExporter()

reset_state()
ctx = make_context("BOUNDARY_DEFENDING", "MEDIUM")
s, r = exp._should_export(ctx)
check("T1.1 Fresh start MEDIUM → C1+C2", s and r == "C1+C2", f"should={s} reason={r}")

reset_state()
ctx = make_context("NO_CLEAR_VERDICT", "LOW")
s, r = exp._should_export(ctx)
check("T1.2 Fresh start LOW → C1 only", s and r == "C1", f"should={s} reason={r}")

reset_state()
exporter_mod._last_exported_verdict = "BOUNDARY_DEFENDING"
ctx = make_context("BOUNDARY_DEFENDING", "MEDIUM")
s, r = exp._should_export(ctx)
check("T1.3 Same verdict MEDIUM → C2 only", s and r == "C2", f"should={s} reason={r}")

reset_state()
exporter_mod._last_exported_verdict = "BOUNDARY_DEFENDING"
ctx = make_context("BOUNDARY_DEFENDING", "LOW")
s, r = exp._should_export(ctx)
check("T1.4 Same verdict LOW → suppressed", not s, f"should={s} reason={r}")

reset_state()
exporter_mod._last_exported_verdict = "BOUNDARY_DEFENDING"
ctx = make_context("COMPRESSION_COILING", "LOW")
s, r = exp._should_export(ctx)
check("T1.5 Verdict changes LOW → C1 only", s and r == "C1", f"should={s} reason={r}")

reset_state()
exporter_mod._last_exported_verdict = "BOUNDARY_DEFENDING"
ctx = make_context("COMPRESSION_COILING", "MEDIUM")
s, r = exp._should_export(ctx)
check("T1.6 Verdict changes MEDIUM → C1+C2", s and r == "C1+C2", f"should={s} reason={r}")

reset_state()
exporter_mod._last_exported_verdict = "NO_CLEAR_VERDICT"
ctx = make_context("NO_CLEAR_VERDICT", "LOW")
s, r = exp._should_export(ctx)
check("T1.7 NO_CLEAR_VERDICT stable LOW → suppressed", not s, f"should={s} reason={r}")

reset_state()
exporter_mod._last_exported_verdict = "EXPANSION_INITIATING"
ctx = make_context("EXPANSION_INITIATING", "HIGH")
s, r = exp._should_export(ctx)
check("T1.8 Same verdict HIGH → C2 only", s and r == "C2", f"should={s} reason={r}")

# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 2: File Output Format
# ═══════════════════════════════════════════════════════════════════════════════
print("\n━━━ GROUP 2: File Output Format ━━━")

with tempfile.TemporaryDirectory() as tmpdir:
    mock_settings.reflex_journal_dir = tmpdir
    exp2 = ReflexJournalExporter()
    reset_state()

    now_a = datetime(2025, 6, 15, 14, 30, 0, tzinfo=timezone.utc)
    now_b = datetime(2025, 6, 15, 16,  0, 0, tzinfo=timezone.utc)
    ctx_a = make_context("BOUNDARY_DEFENDING",  "HIGH",   weight=0.720)
    ctx_b = make_context("COMPRESSION_COILING", "MEDIUM", weight=0.550)

    exp2._append_daily_artifact(ctx_a, now_a)
    exp2._append_journal_index(ctx_a, now_a, "C1+C2")
    exp2._append_daily_artifact(ctx_b, now_b)
    exp2._append_journal_index(ctx_b, now_b, "C2")

    artifact_path = Path(tmpdir) / "BTC-Brain/raw/REFLEX-DAY-2025-06-15.md"
    index_path    = Path(tmpdir) / "wiki/intelligence/Reflex_Observation_Journal.md"

    check("T2.1 Daily artifact file exists", artifact_path.exists())
    art = artifact_path.read_text(encoding="utf-8")
    check("T2.2 First entry header correct",
          "## 14:30 UTC — BOUNDARY DEFENDING (HIGH)" in art, repr(art[:100]))
    check("T2.3 Second entry header correct",
          "## 16:00 UTC — COMPRESSION COILING (MEDIUM)" in art)
    check("T2.4 Narrative content present", "BEHAVIORAL INTERPRETATION" in art)
    check("T2.5 Separator present", art.count("\n---\n") >= 2)
    check("T2.6 Two entries in file", art.count("## ") == 2)

    check("T2.7 Journal index file exists", index_path.exists())
    idx = index_path.read_text(encoding="utf-8")
    check("T2.8 Header present",  "# Reflex Observation Journal" in idx)
    check("T2.9 Table header present", "| Timestamp (UTC) | Verdict |" in idx)
    check("T2.10 First row present",
          "| 2025-06-15 14:30 UTC | BOUNDARY_DEFENDING | HIGH" in idx)
    check("T2.11 Second row present",
          "| 2025-06-15 16:00 UTC | COMPRESSION_COILING | MEDIUM" in idx)
    check("T2.12 Artifact link format correct", "[[REFLEX-DAY-2025-06-15]]" in idx)
    check("T2.13 Trigger reasons recorded", "C1+C2" in idx and "C2" in idx)
    check("T2.14 Weights correct", "0.720" in idx and "0.550" in idx)
    check("T2.15 Structure type in row", "ranging" in idx)

# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 3: Directory Auto-Creation
# ═══════════════════════════════════════════════════════════════════════════════
print("\n━━━ GROUP 3: Directory Auto-Creation ━━━")

with tempfile.TemporaryDirectory() as tmpdir:
    deep = os.path.join(tmpdir, "does", "not", "exist", "yet")
    mock_settings.reflex_journal_dir = deep
    exp3 = ReflexJournalExporter()
    reset_state()
    now = datetime(2025, 6, 15, 10, 0, 0, tzinfo=timezone.utc)
    ctx = make_context("TRAPPED_POSITIONING", "HIGH")
    try:
        exp3._append_daily_artifact(ctx, now)
        exp3._append_journal_index(ctx, now, "C1+C2")
        art_ok = (Path(deep) / "BTC-Brain/raw/REFLEX-DAY-2025-06-15.md").exists()
        idx_ok = (Path(deep) / "wiki/intelligence/Reflex_Observation_Journal.md").exists()
        check("T3.1 Artifact in non-existent dir", art_ok)
        check("T3.2 Index in non-existent dir",    idx_ok)
    except Exception as e:
        check("T3.1 Artifact in non-existent dir", False, str(e))
        check("T3.2 Index in non-existent dir",    False, str(e))

# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 4: Failure Isolation
# ═══════════════════════════════════════════════════════════════════════════════
print("\n━━━ GROUP 4: Failure Isolation ━━━")

with tempfile.TemporaryDirectory() as tmpdir:
    mock_settings.reflex_journal_dir = tmpdir
    exp4 = ReflexJournalExporter()
    reset_state()
    ctx = make_context("BOUNDARY_DEFENDING", "HIGH")
    propagated = False
    with patch("builtins.open", side_effect=OSError("Disk full — simulated")):
        try:
            exp4.maybe_export(ctx)
        except Exception:
            propagated = True
    check("T4.1 OSError does not propagate", not propagated)
    check("T4.2 State not advanced after failure",
          exporter_mod._last_exported_verdict == "",
          f"state='{exporter_mod._last_exported_verdict}'")

# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 5: State Update After Both Writes Succeed
# ═══════════════════════════════════════════════════════════════════════════════
print("\n━━━ GROUP 5: State Update Sequencing ━━━")

with tempfile.TemporaryDirectory() as tmpdir:
    mock_settings.reflex_journal_dir = tmpdir
    exp5 = ReflexJournalExporter()
    reset_state()
    ctx = make_context("EXPANSION_INITIATING", "HIGH")
    call_n = {"n": 0}
    real_open = open
    def fail_second(*a, **kw):
        call_n["n"] += 1
        if call_n["n"] == 2:
            raise OSError("Simulated index write failure")
        return real_open(*a, **kw)
    with patch("builtins.open", side_effect=fail_second):
        try:
            exp5.maybe_export(ctx)
        except Exception:
            pass
    check("T5.1 State not advanced after partial write",
          exporter_mod._last_exported_verdict == "",
          f"state='{exporter_mod._last_exported_verdict}'")

# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 6: Restart Behaviour
# ═══════════════════════════════════════════════════════════════════════════════
print("\n━━━ GROUP 6: Restart Behaviour ━━━")

exp6 = ReflexJournalExporter()
exporter_mod._last_exported_verdict = "BOUNDARY_DEFENDING"
reset_state()
check("T6.1 State empty after reset",
      exporter_mod._last_exported_verdict == "",
      f"state='{exporter_mod._last_exported_verdict}'")
ctx = make_context("BOUNDARY_DEFENDING", "LOW")
s, r = exp6._should_export(ctx)
check("T6.2 Post-restart C1 fires on LOW same-verdict",
      s and "C1" in r, f"should={s} reason={r}")

# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 7: UTC Enforcement
# ═══════════════════════════════════════════════════════════════════════════════
print("\n━━━ GROUP 7: UTC Enforcement ━━━")

with tempfile.TemporaryDirectory() as tmpdir:
    mock_settings.reflex_journal_dir = tmpdir
    exp7 = ReflexJournalExporter()
    reset_state()
    fixed = datetime(2025, 12, 31, 23, 55, 0, tzinfo=timezone.utc)
    ctx = make_context("FAILED_CONTINUATION", "HIGH")
    exp7._append_daily_artifact(ctx, fixed)
    exp7._append_journal_index(ctx, fixed, "C1+C2")
    art_path = Path(tmpdir) / "BTC-Brain/raw/REFLEX-DAY-2025-12-31.md"
    idx_path = Path(tmpdir) / "wiki/intelligence/Reflex_Observation_Journal.md"
    check("T7.1 Artifact filename uses UTC date", art_path.exists(), str(art_path))
    check("T7.2 Artifact header contains UTC time",
          "23:55 UTC" in art_path.read_text(encoding="utf-8"))
    check("T7.3 Index row contains UTC timestamp",
          "2025-12-31 23:55 UTC" in idx_path.read_text(encoding="utf-8"))

# ═══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "━" * 60)
print("SPRINT 3A VERIFICATION RESULTS")
print("━" * 60)
passed = sum(1 for r in results if r[0] == PASS)
failed = sum(1 for r in results if r[0] == FAIL)
for status, name, detail in results:
    print(f"  {status}  {name}")
print(f"\n  Total: {len(results)}  |  Passed: {passed}  |  Failed: {failed}")
if failed == 0:
    print("\n  ALL TESTS PASSED — Sprint 3A implementation verified.")
else:
    print(f"\n  {failed} TEST(S) FAILED — review output above.")
    sys.exit(1)
