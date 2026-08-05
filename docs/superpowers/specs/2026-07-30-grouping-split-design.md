# Grouping split — folders vs project tags (2026-07-30)

## Problem

Two features claim the "group my files" job: vault category folders (pipeline auto-filing,
explorer-visible) and `project/` namespace tags. Result: two answers to "where's my note",
overlapping meaning, UI clutter, double grooming.

## Decision (user-approved, mock: scratchpad grouping-split-mock.html)

One grouping feature in-app: **`project/` tags**. Folders keep the **auto-categorize** job only.

- Folder = category output of the capture pipeline + free user disk territory. User may move/
  add/delete folders in Explorer/Obsidian at will; app follows (category enum stays live-derived
  from folder names — existing behavior, unchanged).
- App never offers folder-based *project* grouping and never blocks user folder edits.
- Projects = `#project/name` body hashtags only. Cross-cutting (a note can be in 2 projects).
- No file moves, no schema change, no sync impact. Tags stay body-authoritative,
  provenance-gated (ISS-051 rules untouched).
- **`project/` and `@`-action tags are user-assigned only** (user-decided 2026-07-30): no
  enrichment path may auto-attach them — phone heuristic filters them from its vocab
  (`heuristicEnrich.ts`), desktop LLM pass filters them from classifier output
  (`mobile_sync_agent.py` `enrich_notes`).

## Changes

### Doctrine (first)
- BUILD-STATE `PROGRESS/DECISIONS` §5: new entry stating the split (wording above).
- No contract-doc change (no schema/Drive/frontmatter change).

### Desktop — TagsView.tsx (UI-only)
- Pinned `PROJECTS` section at top: leaf rows of the `project/` namespace (name without
  prefix, count right-aligned, tag icon). Click → existing `/search?q=tag:project/<leaf>`
  hand-off (no new API).
- `ALL TAGS` tree below with the `project/` namespace node **removed** (no duplication).
- Empty projects state: one-line hint `no projects yet — add #project/name in any note`
  (text-3, not a panel).
- Motion: CSS-only, 150ms hover (surface-2 bg), `:focus-visible` ring. Rows are buttons.
- Sibling TagsView.test.ts: split/filter logic tested (project extraction + tree filtering
  as pure exported function).

### Android — tags UI parity
- Same pinned Projects section in the phone tags screen, same click-to-filter behavior,
  tokens from `src/lib/tokens.ts`. Heuristic enrichment must never invent `project/` tags
  (verify — user-assigned only).

## Non-goals

- No `Projects/x.md` materialized index notes (revisit only if explorer-visibility of
  projects is missed in practice).
- No migration, no removal of VaultManager file browser, no category changes.
