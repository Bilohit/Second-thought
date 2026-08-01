"""
reconcile.py — the field-aware, non-destructive conflict engine (data-model §6, edge-cases C1–C9).

Pure: no network, no disk, deterministic. Python port of the phone's reconcile.ts — the SAME
algorithm on both peers, so the two engines can never silently disagree. The caller fetches the
three inputs (base = last-reconciled revision, local = this device's version, remote = current
Drive head) and applies the result.

Core invariant: a user's typed BODY is never merged, overwritten, or lost. A body-vs-body
divergence spins the remote body off as a conflicted copy; everything else (tags, enrichment,
remind_at) merges silently. A note's PROJECT is not a merged field at all (Projects S1, v3.1
§1.3): it is the `#project@<name>` body tag, so it travels inside the body and is re-derived on
every read. The `project:` frontmatter line and the `project` index column are derived caches with
no independent value to merge — the dead v2.2 `category` field that used to sit on this struct for
that purpose is deleted. The common case — body edited on the phone while the desktop enriches
frontmatter — is conflict-free by construction (disjoint concerns).

Scope: body + frontmatter reconciliation. The delete-vs-edit race (edge-case C5) is the op-queue's
job (data-model §5), not here.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Optional, TypeVar


@dataclass
class Note:
    # system identity (immutable once set)
    id: str
    created: str
    origin: str  # "note" | "capture"
    # user-owned
    title: str
    aliases: list[str]
    tags: list[str]
    remind_at: Optional[str]
    origin_device: Optional[str]  # v2.2 provenance: "phone"|"desktop"|"shared"; None on legacy notes
    enriched: bool
    enrich_source: Optional[str]  # "phone-heuristic" | "desktop-llm" | None
    # informational (never a correctness input)
    modified: str
    device: str
    attachments: list[str]
    # preservation — unknown frontmatter keys, round-tripped verbatim
    extra: dict[str, str]
    body: str


@dataclass
class ReconcileResult:
    merged: Note
    conflicted_copy: Optional[Note] = None


T = TypeVar("T")


def _lww(base: T, local: T, remote: T, local_device: str, remote_device: str) -> T:
    """Last-writer-wins, three-way. Both diverged from base → the LOWEST `device` string wins.

    "Remote wins" was NOT a convergent rule: `remote` is a role, and the two peers assign the roles
    oppositely, so peer A (local=A, remote=B) kept B while peer B (local=B, remote=A) kept A — each
    then saw the other as changed, forever (SYNC-04). The device tie-break is role-INDEPENDENT: both
    peers compare the same two device strings and reach the same answer.

    Works for scalars AND lists (Python `==` is value equality, unlike JS reference equality — so
    this one helper covers both the TS `lww` and `lwwList` mirrors, which must each carry the arm)."""
    if local == remote:
        return local
    changed_local = local != base
    changed_remote = remote != base
    if changed_local and not changed_remote:
        return local
    if changed_remote and not changed_local:
        return remote
    return local if local_device < remote_device else remote


def _union(a: list[str], b: list[str]) -> list[str]:
    """Union two lists, deduped and SORTED. Nothing is ever dropped — this is why a tag removed on
    one device but present on the other survives (edge-case C3).

    Sorted because the ORDER must not depend on which side happens to be `local`: the old "a's order
    then b's extras" made `union(A, B) != union(B, A)`, so the two peers serialized different bytes
    for the same logical note, hashed differently, and each saw "the other side changed" on every
    cycle (SYNC-05). The TS mirror is `[...new Set([...a, ...b])].sort()` — JS sorts by UTF-16 code
    unit and Python by code point, which agree across the whole BMP; a shared fixture in both suites
    pins that agreement so an astral-plane divergence fails loudly instead of silently."""
    return sorted(set(a) | set(b))


def _instant(iso: str) -> float:
    """Parse an ISO-8601 UTC timestamp to a comparable instant. Peers emit mixed precision
    ("…:00Z" vs "…:00.000Z") where lexicographic order lies — compare as instants (§6.3)."""
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0  # empty/invalid stamp → epoch, so reconcile never crashes on a bad `modified`


def _newest(a: str, b: str) -> str:
    """The newer of two ISO stamps, compared as INSTANTS. A raw string compare lies on mixed
    precision — "…:00Z" beats "…:00.500Z" because 'Z' (0x5A) > '.' (0x2E), so the EARLIER whole-second
    stamp won (SYNC-15). Equal instants fall back to `max()` of the raw text, which is symmetric:
    both peers max the same two strings regardless of which one they call `local`."""
    ia, ib = _instant(a), _instant(b)
    if ia != ib:
        return a if ia > ib else b
    return max(a, b)


def _local_is_newer(local: Note, remote: Note) -> bool:
    """True when `local` holds the authoritative newer revision. Instants first (see `_newest`);
    equal instants break on the LOWEST `device` string. Both steps are role-independent, so peer A
    asking about (A, B) and peer B asking about (B, A) reach the same verdict — resolving to `remote`
    on a tie did not, and made the peers pick opposite winners (SYNC-15/SYNC-27)."""
    il, ir = _instant(local.modified), _instant(remote.modified)
    if il != ir:
        return il > ir
    return local.device < remote.device


def reconcile(
    base: Note, local: Note, remote: Note, fresh_conflict_id: str = ""
) -> ReconcileResult:
    """Reconcile three versions of a note into one merged note (+ an optional conflicted copy).

    fresh_conflict_id: id the caller mints for a conflicted copy. Left "" when omitted so reconcile
    stays pure/deterministic; the caller MUST assign a fresh id before persisting a conflicted copy
    (data-model §6: "with a fresh id, so both index independently").
    """
    body_changed_local = local.body != base.body
    body_changed_remote = remote.body != base.body
    body_conflict = body_changed_local and body_changed_remote and local.body != remote.body

    # body + title + aliases (user-owned). On conflict keep local in place; remote body → copy.
    merged_body = (
        remote.body
        if (not body_conflict and body_changed_remote and not body_changed_local)
        else local.body
    )

    # enrichment frontmatter (machine-owned; merges silently, never a conflicted copy).
    # Projects S1 (v3.1 §1.3): nothing about a note's project is decided here — the `#project@`
    # tag rides the body, so it is already covered by the body merge above. The legacy
    # `category_source` key is dropped from the merged `extra`. Only `enriched`/`enrich_source`
    # still merge: the desktop LLM pass sets enriched:true.
    remote_auth = remote.enriched
    local_auth = local.enriched
    enriched = remote_auth or local_auth
    if enriched:
        enrich_source: Optional[str] = "desktop-llm"
    elif local.enrich_source is not None:
        enrich_source = local.enrich_source
    else:
        enrich_source = remote.enrich_source

    # remind_at: one-side-changed → that side; BOTH changed → newest edit wins (user ruling
    # 2026-07-09), equal instants → lowest device. Note-level `modified` proxies the field's edit
    # time. Compared as instants, NOT strings — peers emit mixed ISO precision where lexicographic
    # order lies.
    if (
        local.remind_at != base.remind_at
        and remote.remind_at != base.remind_at
        and local.remind_at != remote.remind_at
    ):
        remind_at = local.remind_at if _local_is_newer(local, remote) else remote.remind_at
    else:
        remind_at = _lww(
            base.remind_at, local.remind_at, remote.remind_at, local.device, remote.device
        )

    merged = Note(
        # immutable — but a legacy revision with no `id` would write `id: ""`, which
        # `read_vault_notes` skips, making the note permanently invisible to sync (SYNC-10). Fall
        # through to the live sides rather than propagate the empty id.
        id=base.id or local.id or remote.id,
        created=base.created,  # immutable
        origin=base.origin,  # immutable
        title=_lww(base.title, local.title, remote.title, local.device, remote.device),
        aliases=_lww(base.aliases, local.aliases, remote.aliases, local.device, remote.device),
        tags=_union(local.tags, remote.tags),  # set-union; user-typed tags always survive (C3)
        remind_at=remind_at,
        # origin_device is immutable once a real platform is stamped (§2.1); prefer whichever side
        # carries a value so provenance survives reconcile. Both sides normally agree (same note).
        origin_device=local.origin_device or remote.origin_device,
        enriched=enriched,
        enrich_source=enrich_source,
        # informational: newest INSTANT wins (a string compare mis-ranks mixed precision — SYNC-15).
        modified=_newest(local.modified, remote.modified),
        device=local.device,  # the reconciling device stamps; informational only
        attachments=_union(local.attachments, remote.attachments),  # additive; never lose one
        # preserve both (local wins collisions); the dead `category_source` is dropped from disk
        extra={k: v for k, v in {**remote.extra, **local.extra}.items() if k != "category_source"},
        body=merged_body,
    )

    if not body_conflict:
        return ReconcileResult(merged)

    # A conflicted copy with an empty id would collide/orphan — fail loud rather than persist one.
    if not fresh_conflict_id:
        raise ValueError(
            "reconcile: a body-vs-body conflict needs a fresh id — pass fresh_conflict_id"
        )

    # Real body-vs-body conflict → keep-both. Never delete or overwrite either body (edge-case C1).
    # The copy's title is prefixed with the MERGED title, not the remote one: conflict_resolver
    # (`find_conflict_sibling`, `list_vault_conflicts`) matches siblings on the title of the note
    # that stayed at its path. When only the local side retitled, `merged.title` is `local.title`,
    # a `remote.title` prefix never matched, and the conflict was invisible to the resolver (SYNC-14).
    suffix = f"(conflicted copy {remote.device} {remote.modified})"
    conflicted_copy = replace(
        remote,
        id=fresh_conflict_id,  # caller mints a fresh id; "" = "not yet assigned"
        title=f"{merged.title} {suffix}",
        enriched=False,  # new id → needs its own enrichment/embedding pass
        enrich_source=None,
        extra={**remote.extra},
    )
    return ReconcileResult(merged, conflicted_copy)
