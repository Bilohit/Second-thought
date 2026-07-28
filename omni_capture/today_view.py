"""
today_view.py — the desktop TODAY/agenda aggregation (PARCHMENT-BOOST D-A, plan §10 task 11).

A pure derived view for one local calendar day, mirroring the phone's `todayAgenda.ts`
(`agendaForDay`): pending reminders partitioned into overdue / due-today, the scratchpad count,
and the day's daily note found by S1 title-match. The aggregation (`build_today`) is read-only —
it NEVER writes a note file or a reminder. Files are the source of truth; every input here
(reminders table, vault scan) is a derived read.

The ONE sanctioned writer is `create_daily_note` (find-or-create on demand, mirroring the phone's
"Start today's note" tap) — the first and only path by which the DESKTOP originates a `note`. It is
invoked ONLY from the explicit POST `/today/daily-note`, never as a side-effect of the GET. It is
idempotent and never clobbers an existing note (body sacred).

Cross-peer parity note: overdue = reminders whose local day is BEFORE the viewed day and whose
fire time has passed; due-today = reminders whose local day IS the viewed day (soonest-first);
future-day reminders are excluded (they surface on their own day). This matches the phone's buckets.

The daily note is FOUND, never created here — "find-or-create on demand" (the plan) creates it via a
separate action, exactly as the phone's agenda finds `dailyNoteId` and the UI creates on tap.
"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Optional


def _parse_local(iso: str) -> Optional[datetime]:
    """Parse an ISO reminder `fire_at` to a LOCAL naive datetime, or None if unparseable.

    An offset-aware value is converted to local time; a naive value is assumed already local
    (that is how reminders are stored). Fail-closed on a bad value — a reminder we cannot place
    on a day is dropped from the agenda rather than crashing the view."""
    try:
        dt = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def _bucket_reminders(reminders: list[dict], now: datetime) -> tuple[list[dict], list[dict]]:
    """Partition pending reminders into (overdue, due_today) relative to `now` (local)."""
    today = now.date()
    overdue: list[tuple[datetime, dict]] = []
    due_today: list[tuple[datetime, dict]] = []
    for r in reminders:
        dt = _parse_local(r.get("fire_at", ""))
        if dt is None:
            continue
        row = {
            "id": r["id"],
            "note_path": r["note_path"],
            "title": r["label"],
            "fire_at": r["fire_at"],
        }
        d = dt.date()
        if d < today and dt <= now:
            overdue.append((dt, row))
        elif d == today:
            due_today.append((dt, row))
        # future (d > today) → excluded; it surfaces on its own day
    overdue.sort(key=lambda x: x[0], reverse=True)   # most-recent miss first (phone parity)
    due_today.sort(key=lambda x: x[0])               # soonest first
    return [r for _, r in overdue], [r for _, r in due_today]


def find_daily_note(vault_root: Path, day_iso: str) -> Optional[dict]:
    """S1 title-match: the daily note is the note whose title == `day_iso` (YYYY-MM-DD).

    Returns {"id", "path", "title"} or None. ponytail: full vault rglob per call via
    read_vault_notes — fine for one on-demand GET; add a title index only if a vault ever holds
    enough notes that a scan is felt. ISO-date title collisions are implausible, so first match wins."""
    from mobile_sync_agent import read_vault_notes

    for note in read_vault_notes(str(vault_root)).values():
        if (note.get("title") or "").strip() == day_iso:
            return {"id": note["id"], "path": note["path"], "title": note["title"]}
    return None


# Phone-parity daily template (phone `templates.ts` id "daily"): title == the ISO day, body dates
# itself + intentions/log skeleton. One-time plain-Markdown insert; the user owns it after creation.
_DAILY_BODY = "# {day}\n\n## Intentions\n- [ ] \n\n## Log\n"


def create_daily_note(vault_root: Path, day_iso: str, folder: str = "Daily",
                       now_iso: Optional[str] = None) -> dict:
    """Find-or-create the daily note for `day_iso` under `<vault>/<folder>/`.

    The ONLY path by which the desktop ORIGINATES a note (origin:note, origin_device:desktop). Body
    sacred + idempotent: if a note already matches this day (S1 title-match anywhere in the vault) or
    a file already occupies the target path, that existing note is returned UNTOUCHED — this never
    overwrites user bytes. Returns {"id", "path", "title"}. `now_iso` is injectable for tests."""
    existing = find_daily_note(vault_root, day_iso)
    if existing:
        return existing

    from mobile_sync_agent import _atomic_write_note, _mint_capture_id
    from note_model import parse_note, serialize_note
    from reconcile import Note

    dest = Path(vault_root) / folder
    path = dest / f"{day_iso}.md"
    if path.exists():
        # Target file exists but its title did not match (e.g. user renamed it) — never clobber it.
        note = parse_note(path.read_text(encoding="utf-8", newline=""))
        return {"id": note.id, "path": str(path), "title": note.title}

    ts = now_iso or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())  # UTC-Z, desktop convention
    note = Note(
        id=_mint_capture_id(), created=ts, origin="note", title=day_iso,
        aliases=[], tags=[], remind_at=None, category=None,
        origin_device="desktop", enriched=False, enrich_source=None,
        modified=ts, device="desktop", attachments=[], extra={},
        body=_DAILY_BODY.format(day=day_iso),
    )
    dest.mkdir(parents=True, exist_ok=True)
    _atomic_write_note(str(path), serialize_note(note))   # atomic: never a torn note
    return {"id": note.id, "path": str(path), "title": day_iso}


def build_today(
    vault_root: Path,
    db_path: Path,
    day_iso: str,
    now: datetime,
    scratchpad_folder: str = "_scratchpad",
) -> dict:
    """Aggregate the TODAY view for `day_iso`. Read-only. `now` is the local wall-clock used to
    split overdue vs due-today (passed in so this stays deterministic under test)."""
    from reminders import list_reminders
    from scratchpad import list_scratchpad

    overdue, due_today = _bucket_reminders(list_reminders(db_path), now)
    return {
        "date": day_iso,
        "overdue": overdue,
        "due_today": due_today,
        "scratchpad_count": len(list_scratchpad(Path(vault_root), scratchpad_folder)),
        "daily_note": find_daily_note(Path(vault_root), day_iso),
    }
