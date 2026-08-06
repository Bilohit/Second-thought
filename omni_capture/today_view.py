"""
today_view.py — the desktop TODAY/agenda aggregation (PARCHMENT-BOOST D-A, plan §10 task 11).

A pure derived view for one local calendar day, mirroring the phone's `todayAgenda.ts`
(`agendaForDay`): pending reminders partitioned into overdue / due-today, the scratchpad count,
and the day's daily note found by S1 title-match. The aggregation (`build_today`) is read-only —
it NEVER writes a note file or a reminder. Files are the source of truth; every input here
(reminders table, vault scan) is a derived read.

There are TWO sanctioned desktop note-origination writers, both sharing the `_write_note_file`
write path so they emit the identical frontmatter key set (contract:
`Second Thought - Android App/data-model-and-contracts.md`): `create_daily_note` (find-or-create
on demand, mirroring the phone's "Start today's note" tap, invoked ONLY from the explicit POST
`/today/daily-note`, never as a side-effect of the GET; idempotent and never clobbers an existing
note — body sacred) and `create_note` (always-new, invoked from POST `/note`, lands in `_loose/`
rather than `Daily/`).

Cross-peer parity note: overdue = reminders whose local day is BEFORE the viewed day and whose
fire time has passed; due-today = reminders whose local day IS the viewed day (soonest-first);
future-day reminders are excluded (they surface on their own day). This matches the phone's buckets.

The daily note is FOUND, never created here — "find-or-create on demand" (the plan) creates it via a
separate action, exactly as the phone's agenda finds `dailyNoteId` and the UI creates on tap.
"""
from __future__ import annotations

import sys
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
_DAILY_SKELETON = "\n## Intentions\n- [ ] \n\n## Log\n"


def _daily_body(day_iso: str, tag: Optional[str]) -> str:
    """The daily template, optionally carrying its `#<tag>` line (SP3 Task 10).

    The tag goes in as ORDINARY BODY TEXT, one line under the heading -- deliberately NOT the
    trailing machine `tags:` line (ISS-051 §3). That line is machine-managed, and
    `mobile_sync_agent`'s enrichment pass REPLACES it wholesale
    (`apply_trailing_tags_line(body, ["project@X"])`, mobile_sync_agent.py:1484-1487, whose own
    `ponytail:` note says it merges only "if a second machine-owned token appears") -- so a tag
    parked there would be silently dropped the first time a note got classified into a project.
    Written once at creation and never rewritten: `create_daily_note` is find-or-create, so the
    user owns this line from the moment it exists, exactly like a tag they typed themselves.

    With no tag the output is BYTE-IDENTICAL to the pre-Task-10 template."""
    head = f"# {day_iso}\n" + (f"#{tag}\n" if tag else "")
    return head + _DAILY_SKELETON


def _write_note_file(vault_root: Path, folder: str, title: str, body: str,
                      filename_stem: Optional[str] = None,
                      now_iso: Optional[str] = None,
                      remind_at: Optional[str] = None) -> dict:
    """Shared desktop note-origination write path — the ONE place that mints a note id, builds the
    `Note`, and writes it atomically. `create_daily_note` and `create_note` both call this rather
    than each re-authoring their own write, so the two routes stay locked to the identical
    frontmatter key set (contract: `Second Thought - Android App/data-model-and-contracts.md`).

    `filename_stem` defaults to the freshly-minted id; `create_daily_note` overrides it to
    `day_iso` so the file stays discoverable by the S1 title-match convention. `folder=""` writes
    to the vault root. Returns {"id", "path", "title"}. `now_iso` is injectable for tests.

    `remind_at` (CAL-D): an optional ISO string landing straight in the `remind_at` frontmatter key
    via the `Note` struct + `serialize_note` — the SAME field `reconcile.py`'s LWW merge and
    `reminders.sync_reminders_from_notes` already read. `None` (the default, every pre-existing
    caller) serializes to no `remind_at:` line at all, matching prior output byte-for-byte."""
    from mobile_sync_agent import _atomic_write_note, _mint_capture_id
    from note_model import serialize_note
    from project_registry import load as load_registry
    from reconcile import Note

    ts = now_iso or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())  # UTC-Z, desktop convention
    note = Note(
        id=_mint_capture_id(), created=ts, origin="note", title=title,
        aliases=[], tags=[], remind_at=remind_at,
        origin_device="desktop", enriched=False, enrich_source=None,
        modified=ts, device="desktop", attachments=[], extra={},
        body=body,
    )
    stem = filename_stem if filename_stem is not None else note.id
    dest = Path(vault_root) / folder if folder else Path(vault_root)
    path = dest / f"{stem}.md"
    dest.mkdir(parents=True, exist_ok=True)
    # v3.1: the registry is what turns the body's `#project@` tag into the `project:` frontmatter
    # cache — the line is ALWAYS present (`[-]` for a loose note, which a fresh note is).
    _atomic_write_note(str(path), serialize_note(note, load_registry(vault_root)))   # atomic: never torn
    # FR-30: this is the ONE place the desktop originates a note, and it used to tell no index.
    # The only reconciler (vault_sync's diff pass) runs at server startup or on a manual POST
    # /vault/sync-index, so a note made mid-session was absent from captures.db -- invisible to
    # /search and uncounted by the vault tile -- until the next restart. Reproduced on BOTH the
    # pre-FR-29 vault-root location and the current `_loose/` one, so the directory was never
    # the variable. Best-effort and non-fatal, the same idiom trash.py and project_tidy.py use:
    # the file is the source of truth and is already written, so a failed index write must
    # never fail the note write.
    #
    # ponytail: captures.db only -- a fresh note's body is empty, so there is nothing to embed
    # yet, and re-embedding needs Ollama config today_view.py has no business importing (same
    # division of labour as trash.py's restore).
    try:
        from index_writer import upsert_capture_from_file
        upsert_capture_from_file(vault_root, path)
    except Exception as exc:
        print(f"[TodayView] index sync on note create error: {exc}", file=sys.stderr)
    return {"id": note.id, "path": str(path), "title": title}


def create_daily_note(vault_root: Path, day_iso: str, folder: Optional[str] = None,
                       now_iso: Optional[str] = None, tag: Optional[str] = None) -> dict:
    """Find-or-create the daily note for `day_iso` under `<vault>/<folder>/`.

    One of the two desktop note-origination paths (the other is `create_note`, always-new in
    `_loose/` — see server.py's POST /note docstring for what distinguishes them). Body sacred +
    idempotent: if a note already matches this day (S1 title-match anywhere in the vault) or a file
    already occupies the target path, that existing note is returned UNTOUCHED — this never
    overwrites user bytes. Returns {"id", "path", "title"}. `now_iso` is injectable for tests.

    SP3 Task 10: `folder` now defaults to `_loose/` (via `note_dir_for(None)`), not the old
    hardcoded `"Daily"`. A daily note is not a project — post-s127 a project IS the body tag
    `#project@<name>`, so a note written into `Daily/` with no such tag resolves loose anyway and
    the tidy pass relocates it (measured, not assumed). Grouping is carried by the ordinary
    descriptive `tag` instead, which is what `tag` writes. Passing `folder` explicitly still works
    and is what the tests use to pin the old shape."""
    from projects import note_dir_for   # function-local, matching this module's import style

    existing = find_daily_note(vault_root, day_iso)
    if existing:
        return existing

    if folder is None:
        folder = note_dir_for(None)
    dest = Path(vault_root) / folder
    path = dest / f"{day_iso}.md"
    if path.exists():
        # Target file exists but its title did not match (e.g. user renamed it) — never clobber it.
        from note_model import parse_note
        note = parse_note(path.read_text(encoding="utf-8", newline=""))
        return {"id": note.id, "path": str(path), "title": note.title}

    return _write_note_file(vault_root, folder, day_iso, _daily_body(day_iso, tag),
                             filename_stem=day_iso, now_iso=now_iso)


def create_note(vault_root: Path, title: Optional[str] = None, now_iso: Optional[str] = None,
                 body: Optional[str] = None, remind_at: Optional[str] = None) -> dict:
    """Always-new generic note origination — the desktop's SECOND note-origination path, alongside
    `create_daily_note`. Unlike the daily note this is never find-or-create: every call mints a
    fresh note, filed in `_loose/` (never `Daily/`). Invoked from POST `/note`. Reuses
    `_write_note_file`, `create_daily_note`'s own write path, rather than re-authoring one, so both
    routes emit the identical frontmatter key set — a second, differently-shaped write path would
    fork the contract owned by `Second Thought - Android App/data-model-and-contracts.md`. Returns
    {"id", "path", "title"}.

    FR-29: this used to pass `folder=""`, landing the note directly in the vault ROOT — and
    `vault_admin._filed_notes` checks `entry.is_dir()` before it ever looks at a file, so a
    root-level note was structurally invisible to the project-tidy pass and could never be
    re-filed once the user tagged it. A fresh note has an empty body, so it carries no
    `#project@` tag by construction, and the data model's own rule for an unresolved project is
    `projects.note_dir_for(None) == LOOSE_DIR` — the same `_loose/` every other writer already
    uses (mobile_sync_agent.py:617). Landing it there makes it tidy-visible from birth.

    `body` (CAL-D): optional body text — e.g. an inline `#project@<name>` tag the caller wants
    resolved into the `project:` frontmatter cache exactly like any other note (body is truth,
    never a literal project name). `remind_at` (CAL-D): optional ISO string threaded straight to
    `_write_note_file` → the `remind_at` frontmatter key. Both default to the prior behaviour
    (empty body, no reminder) so every existing caller is unaffected."""
    from projects import note_dir_for   # function-local, matching this module's import style

    return _write_note_file(vault_root, note_dir_for(None), title or "", body or "",
                             now_iso=now_iso, remind_at=remind_at)


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
