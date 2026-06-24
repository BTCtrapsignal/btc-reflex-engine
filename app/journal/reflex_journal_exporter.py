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
