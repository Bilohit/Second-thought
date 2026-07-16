"""
reconcile.py — the field-aware, non-destructive conflict engine (data-model §6, edge-cases C1–C9).

Pure: no network, no disk, deterministic. Python port of the phone's reconcile.ts — the SAME
algorithm on both peers, so the two engines can never silently disagree. The caller fetches the
three inputs (base = last-reconciled revision, local = this device's version, remote = current
Drive head) and applies the result.

Core invariant: a user's typed BODY is never merged, overwritten, or lost. A body-vs-body
divergence spins the remote body off as a conflicted copy; everything else (tags, category,
enrichment, remind_at) merges silently. The common case — body edited on the phone while the
desktop enriches frontmatter — is conflict-free by construction (disjoint concerns).

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
    # machine-owned (once enriched)
    category: Optional[str]
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


def _lww(base: T, local: T, remote: T) -> T:
    """Last-writer-wins, three-way. Both diverged from base → advancing (remote) side wins.
    Works for scalars AND lists (Python `==` is value equality, unlike JS reference equality —
    so this covers both the TS `lww` and `lwwList` helpers)."""
    if local == remote:
        return local
    changed_local = local != base
    changed_remote = remote != base
    if changed_local and not changed_remote:
        return local
    if changed_remote and not changed_local:
        return remote
    return remote


def _union(a: list[str], b: list[str]) -> list[str]:
    """Union two lists, deduped, `a` order then `b`'s extras. Nothing is ever dropped — this is why
    a tag removed on one device but present on the other survives (edge-case C3)."""
    out = list(a)
    for x in b:
        if x not in out:
            out.append(x)
    return out


def _instant(iso: str) -> float:
    """Parse an ISO-8601 UTC timestamp to a comparable instant. Peers emit mixed precision
    ("…:00Z" vs "…:00.000Z") where lexicographic order lies — compare as instants (§6.3)."""
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0  # empty/invalid stamp → epoch, so reconcile never crashes on a bad `modified`


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
    # Only the desktop LLM pass sets enriched:true, so `enriched` is the authority for category.
    remote_auth = remote.enriched
    local_auth = local.enriched
    # K-1: a user re-categorization (either device) beats the machine value and is never reverted.
    # `category_source` rides in `extra` (unknown-key preservation); absent → "machine" (legacy).
    # Parsed extras keep the raw text after ":" (leading space included) — strip before comparing.
    local_cat_user = local.extra.get("category_source", "machine").strip() == "user"
    remote_cat_user = remote.extra.get("category_source", "machine").strip() == "user"
    if local_cat_user and not remote_cat_user:
        category = local.category
        category_source = "user"
    elif remote_cat_user and not local_cat_user:
        category = remote.category
        category_source = "user"
    elif local_cat_user and remote_cat_user:
        # both user-set → newest edit wins (note-level modified, instants), tie → remote
        category = (
            local.category
            if _instant(local.modified) > _instant(remote.modified)
            else remote.category
        )
        category_source = "user"
    elif remote_auth:
        category = remote.category
        category_source = "machine"
    elif local_auth:
        category = local.category
        category_source = "machine"
    else:
        category = _lww(base.category, local.category, remote.category)
        category_source = "machine"
    enriched = remote_auth or local_auth
    if enriched:
        enrich_source: Optional[str] = "desktop-llm"
    elif local.enrich_source is not None:
        enrich_source = local.enrich_source
    else:
        enrich_source = remote.enrich_source

    # remind_at: one-side-changed → that side; BOTH changed → newest edit wins (user ruling
    # 2026-07-09), tie → remote. Note-level `modified` proxies the field's edit time. Compared as
    # instants, NOT strings — peers emit mixed ISO precision where lexicographic order lies.
    if (
        local.remind_at != base.remind_at
        and remote.remind_at != base.remind_at
        and local.remind_at != remote.remind_at
    ):
        remind_at = (
            local.remind_at
            if _instant(local.modified) > _instant(remote.modified)
            else remote.remind_at
        )
    else:
        remind_at = _lww(base.remind_at, local.remind_at, remote.remind_at)

    merged = Note(
        id=base.id,  # immutable
        created=base.created,  # immutable
        origin=base.origin,  # immutable
        title=_lww(base.title, local.title, remote.title),
        aliases=_lww(base.aliases, local.aliases, remote.aliases),
        tags=_union(local.tags, remote.tags),  # set-union; user-typed tags always survive (C3)
        remind_at=remind_at,
        category=category,
        enriched=enriched,
        enrich_source=enrich_source,
        # informational: newest string wins (matches the TS — plain string compare, not instant).
        modified=local.modified if local.modified > remote.modified else remote.modified,
        device=local.device,  # the reconciling device stamps; informational only
        attachments=_union(local.attachments, remote.attachments),  # additive; never lose one
        # preserve both (local wins collisions); K-1 category_source follows the category winner
        extra={**remote.extra, **local.extra, "category_source": category_source},
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
    suffix = f"(conflicted copy {remote.device} {remote.modified})"
    conflicted_copy = replace(
        remote,
        id=fresh_conflict_id,  # caller mints a fresh id; "" = "not yet assigned"
        title=f"{remote.title} {suffix}",
        enriched=False,  # new id → needs its own enrichment/embedding pass
        enrich_source=None,
        extra={**remote.extra},
    )
    return ReconcileResult(merged, conflicted_copy)
