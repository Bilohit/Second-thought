# Design — S1: desktop tag/registry core (projects rework, sub-project 1 of 5)

**Date:** 2026-08-01 · **Session:** s125 · **Status:** design drafted, awaiting user review.

Parent design: `2026-08-01-projects-rework-design.md`.
Binding contract: `Second Thought - Android App/data-model-and-contracts.md` **v3.1** — §1 (frontmatter
schema + field-ownership table), §1.3 (projects), §13 (`.projects.toml`).
Decisions: `BUILD-STATE/PROGRESS/DECISIONS.md` §5, s124 + s125 blocks.

This is sub-project 1 of the five named in the parent design §11. It builds the Python core that every
later sub-project consumes, and deletes `category`. It ships **no new UI**.

---

## 0. Why this decomposition

Measured, not estimated: `categor*` matches **1144 times across 66 Python files** and **203 times across
27 gui files**. `storage_engine.py` alone carries 129, `mobile_sync_agent.py` 103,
`test_mobile_sync_agent.py` 95. A single change of that size has no safe intermediate state, so S1 is
split into two commits with a green gate between them.

**Step A — new modules, zero callers.** Everything new, nothing existing touched, full test coverage,
gates green. If Step B goes wrong, this is the bisect point.
**Step B — rip-out and wire.** `category` deleted end to end, the new modules wired in, gui patched
only enough to stay green.

## 1. Scope

**In scope.** The `#project@` parser and structural-tag exclusion · the `project:` derived frontmatter
cache · `.projects.toml` load/save/merge/rebuild · the derived-path tidy pass · deletion of `category`
end to end · the `project` index column · the four hardcoded-category deletions · the minimal phone
parity slice (§7) · the minimal gui keep-green patch (§8).

**Out of scope.** Desktop full-window project UI (sub-project 3) · compact-mode UI (4) · phone project
surfaces, tiles, three-dot assign, semantic matching (5) · auto-assignment confidence bands and the
Inbox suggestion flow, beyond deleting the category enum the LLM currently picks from.

## 2. New modules (Step A)

Each is pure where it can be, has a sibling `test_*.py`, and follows the repo's plain-function style —
no classes, no DI, module-level config singleton access only at the edges.

### 2.1 `omni_capture/projects.py` — the tag layer

```python
parse_project_tags(body: str) -> list[str]      # every #project@ capture, in document order
parse_project_tag(body: str) -> str | None      # first capture, or None
is_valid_project_name(name: str) -> bool        # ^[A-Za-z0-9][A-Za-z0-9_-]*$
is_structural_tag(tag: str) -> bool             # sys/* or project@*
resolve_project(body: str, registry: Registry) -> str | None   # None == loose
project_cache_value(resolved: str | None) -> str               # "[research]" | "[-]"
note_dir_for(resolved: str | None) -> str                      # "research" | "_loose"
```

**Parser.** Contract §1.3 writes the parser as `/#project@([^\s]+)/`. Implemented **whitespace-anchored
and code-stripped**, i.e. `(^|\s)#project@([^\s]+)`, applied after `body_tags`'s existing
`_FENCED_CODE`/`_INLINE_CODE` stripping. This is a deliberate tightening of the contract's shorthand,
for one reason: the bare form matches inside `https://example.com/page#project@x`, which would file a
note from a URL fragment. It matches the grammar `body_tags.py` already enforces for every other tag,
so the two stay consistent. **Recorded as a tightening, not a drift** — the phone mirror must match it.

**Two tags.** The parent design calls two projects "a validation error the UI prevents, not a state the
model resolves". The model still must not crash on a hand-typed file, so: **first tag in document order
wins**, deterministically, and `parse_project_tags` exposes the full list so a later UI can flag it.

**`resolve_project` is the single resolution rule**, and every surface calls it rather than reimplementing:
a tag resolves only if the name is registry-eligible **and** the registry holds it, either under its
current key or as some entry's `renamed_from`. Anything else — missing tag, invalid name, unregistered
name, unsynced registry — is **loose**. That one rule absorbs deletion, invalid names, rename lag and
sync lag alike (contract §1.3, "dangling reads as loose").

### 2.2 `omni_capture/project_registry.py` — `.projects.toml`

```python
load(vault_root: Path) -> Registry            # tomllib; missing file -> empty registry, never an error
save(vault_root: Path, reg: Registry) -> None # tomlkit; round-trips unknown keys; rejects invalid names
merge(base: Registry, local: Registry, remote: Registry) -> Registry
rebuild_from_vault(vault_root: Path) -> Registry
clear_stale_renamed_from(reg: Registry, live_names: set[str]) -> Registry
```

- Schema exactly as contract §13.1: `schema = 1`, `[projects."<name>"]` **always quoted**, fields
  `description` / `created` / `modified` / `device`, optional transitional `renamed_from`.
- **Unknown keys round-trip.** A future field written by the phone must survive a desktop rewrite
  untouched (contract §13.1, mirroring §10's frontmatter rule).
- **`save` rejects an invalid name** rather than writing it (contract §13.1: "a writer MUST reject").
- **`schema` is not merged.** A `schema` value this build does not understand means: leave the file
  alone entirely and surface it. Never rewrite a file whose fields you would drop.
- **Never store an embedding vector** (contract §13.1).
- `rebuild_from_vault` scans bodies for `#project@`, per contract §13.3: every project reappears with an
  empty description, `renamed_from` is unreconstructable and simply absent, and notes carrying an old
  name read as loose — the correct fallback, no special case.

**`merge` is the correctness core of this sub-project.** It implements contract §13.2's six-row table
directly, and its test is written **as that table**, one parametrized case per row, quoting the row:

| base | local | remote | Outcome |
|---|---|---|---|
| absent | present | absent | added locally → keep |
| absent | absent | present | added remotely → keep |
| absent | present | present | both added → merge per-field (row 5) |
| present | absent | unchanged | deleted locally → delete applies |
| present | present | present, differing | per-field: newest entry `modified` wins; exact tie → remote |
| present | absent | **modified** | **edit beats delete** → entry resurrected |

`created` is immutable — on divergence take the **earlier** value. **A last-writer-wins shortcut here
silently eats a description written on the other device** and is the single most likely way this
sub-project ships a real bug; row 6 and the tie rule are the ones to write tests for first.

`base_projects` — the registry as of last sync, the merge's `base` — is persisted in the existing
desktop sync state, `.omni_capture/mobile_sync_state.json` (`mobile_sync_agent.py:1827`), alongside the
per-note `base_parent` bookkeeping. No new state file.

### 2.3 `omni_capture/project_tidy.py` — derived housekeeping

Split pure planner from impure applier, per repo convention:

```python
plan_tidy(entries: list[NoteLoc], registry: Registry) -> list[Move]   # pure, fully tested
apply_tidy(vault_root: Path, moves: list[Move]) -> TidyResult          # os.replace under the vault lock
```

- Target is `vault_root / note_dir_for(resolve_project(body, registry))` — a project directory, or
  `_loose/`. **Every note stays at depth 1** (contract §1.3): this is what keeps each note's
  `![alt](../_attachments/<id>/<file>)` body ref valid across every move, without ever rewriting a body.
- **Desktop alone re-paths.** The phone never moves a file and never creates a directory.
- Moves are `os.replace` (atomic, same volume) and **refuse to clobber** — the existing
  `_maybe_refile_local` (`mobile_sync_agent.py:686`) is the pattern to follow, not reinvent.
- Serialized under `dedup._vault_lock`, the existing vault `FileLock` (contract §13.2 as corrected in
  v3.1).
- Emptied project directories are removed; `_loose/` is created on demand and never removed.
- **A tidy pass never edits file content** — it moves files and nothing else.

### 2.4 `body_tags.py` — structural exclusion

`parse_body_tags` drops any tag for which `is_structural_tag` holds, so the derived `tags:` cache carries
descriptive vocabulary only. This is the only Step A change to an existing module, and it is
behaviour-changing, so it lands with its own regression test.

Consequence to state plainly: `tag_vocab.py` normalizes new tags against the vault's existing
vocabulary, so an unfiltered `project@research` in the cache can capture a genuine new tag. That is the
functional reason for the rule, not tidiness.

### 2.5 The `project:` frontmatter cache

`frontmatter.py` / `note_model.py` gain `project`, written **always bracketed**: `project: [research]`
when resolved, `project: [-]` when loose, **never absent**. Recomputed from the body on every save
alongside `tags:` and `attachments:`; hand edits to it are overwritten; deleting the line rebuilds it
losslessly. It is a cache, exactly like the two beside it (contract §1, §1.3 v3.1).

## 3. Step B — the rip-out

`category` is deleted end to end. Grouped by role, with the surveyed anchors:

| Area | Files | What happens |
|---|---|---|
| Discovery + `.category.toml` | `storage_engine.py:114-201, 718` | `discover_categories`, `read_category_config`, `build_category_descriptions`, `write_category_description`, `ensure_category` all deleted; `.projects.toml` replaces them |
| Capture model | `models.py:42, 93-118` | `CaptureOutput.category` and the live folder-name enum in `build_capture_model` deleted |
| LLM | `llm_engine.py:266-332` | category descriptions in the prompt/schema become project descriptions from the registry; **`key_signals`→arbitrary-tag generation is deleted** (parent design §8) |
| Write path | `storage_engine.py:346, 518-522, 920-1043` | `_category_str`, `_resolve_file_path`, `write_to_named_category`, the `write_to_vault` decision/dedup-refile logic all re-key onto the resolved project / `_loose` |
| Sync agent | `mobile_sync_agent.py:593, 686, 1375-1484` | `_resolve_dest_folder`, `_maybe_refile_local`, the classify→`dest_category`→`refile` pipeline re-key onto project; `base_projects` added to sync state |
| Index | `index_writer.py:13, 76, 91, 709-721, 963-1057` | the `category` column is **renamed to `project`**, not dropped — `by_category` stats/filters become `by_project` near-mechanically. See §4 |
| Server + CLI | `server.py:907, 1683-1747`, `main.py:182-197, 522` | category-CRUD endpoints become project-registry endpoints; the two pipelines stay **hand-mirrored** |
| Scratchpad | `scratchpad.py:231-278, 360-369` | approve routes to a project or `_loose`; `_CATEGORY_DEFAULT_STATUS` deleted |
| Retry engine | `retry_engine.py:133-227` | the ≥1-category-folder precondition **collapses to "Ollama is reachable"** — see §5 |
| Everything else | `jobs.py` `capture_log.py` `delete_detect.py` `link_resolver.py` `note_editor.py` `rag_engine.py` `merge.py` `reconcile.py` `note_model.py` `pre_resolver.py` `notifier.py` `enrichment_router.py` | carry the field through, re-key or delete per §6 |

**Hardcoded category names — deleted (explicit user instruction, s125).** `storage_engine._LEDGER_FILES`
(`{"Finance": "Expenses.md"}`), `pre_resolver`'s Finance/CRM hints, `link_resolver.py:154`'s CRM
word-count special-case, `scratchpad.py:360`'s `_CATEGORY_DEFAULT_STATUS`. They encode a fixed taxonomy
that user-named projects replace, and they already contradicted the repo hard rule "vault categories are
never hardcoded". This is a feature subtraction and is authorised.

## 4. The index column

`index_writer.py`'s `captures` table has a `category` column feeding search filters and the `by_category`
stats aggregation. It is **re-keyed to `project`**, not deleted:

- Grouping by project is the most frequent read in the whole rework — every tile, every count, every
  list. An indexed column answers it without reading a single note body.
- Net schema change is zero: one column is renamed, not added.
- The phone has the exact twin (`phone/src/db/index.ts:66`, `category TEXT`), which sub-project 5 renames
  the same way. Its rename is **not** in S1.

The column is derived from `resolve_project`, so it agrees with the `project:` frontmatter cache by
construction. Both are caches of one truth: the body tag.

## 5. Inherited item — P2a's precondition

`retry_pending()` currently refuses to run unless `discover_categories()` returns ≥1 folder. That was
correct against s124's code (`run_llm_engine` hard-refuses an empty category set) and becomes wrong the
moment projects land: a retry can then always succeed, because worst case the repaired note lands loose.
Step B collapses the precondition to "Ollama is reachable". Carried from `HANDOVER.md` §5 item 4 —
flagged there as "do not rip out before the rework; do not forget during".

## 6. Testing

- Every new module ships a sibling `test_*.py`. `project_registry.merge` is tested **as contract
  §13.2's table**, one parametrized case per row, each quoting its row.
- **Body-sacred assertions** on every op that touches a note: byte-identity of the body above any
  trailing tag line, asserted before/after. Non-negotiable, both repos.
- **Round-trip identity** is the new gate the user's priority demands: a note whose body is unchanged
  must re-derive byte-identical `tags:` and `project:` on both peers. Test the desktop half here;
  sub-project 5 owns the phone half.
- `FUZZ=1 pytest test_fuzz_races.py -q` is **required** for Step B — the sync agent's re-path and
  sync-state surfaces move. It is not required for Step A.
- Gates to beat: desktop **1173**/4skip · gui **545** + build clean · phone **1823**/6skip.

## 7. Phone parity slice (mandatory, small)

The user's stated first priority is that desktop and Android process `.md` files identically, and that
sync never edits content. Once desktop writes `#project@x` into bodies, an unmodified phone would
harvest it into `tags:` on its next save — the two peers would disagree about the same file's derived
cache, and each save would churn the other's. So the phone parity change **cannot** wait for
sub-project 5:

- `phone/src/lib/bodyTags.ts` — the same structural-tag exclusion, mirroring `body_tags.py`. The two
  grammars are already required to stay identical and their docstrings say so.
- `phone/src/lib/frontmatter.ts` — read/write/derive `project:` with the identical bracket form.

Out of this slice: the phone's index column, tiles, assign menu, semantic matching — all sub-project 5.

## 8. gui keep-green patch

Step B removes `category` from API responses that ~27 gui files read. The desktop project UI is
sub-projects 3 and 4, so gui gets the **minimum patch that typechecks and keeps 545 green** — fields and
columns dropped, no new project UI. Deliberately throwaway; master never goes red.

## 9. Risks

1. **`merge` shipped as last-writer-wins.** The failure is silent and destroys a user's description.
   Mitigated by writing the §13.2 table as the test before the implementation.
2. **The plan's code blocks are unverified drafts.** s124 proved this three times in one session — a
   logically wrong safety gate, a hardcoded path that `write_to_vault` derives from the title, and a
   `row["filepath"]` that is actually `row["path"]`. **Every symbol is verified at source before use.**
3. **`main.py` / `server.py` are hand-duplicated by design.** Any pipeline change lands in both, by hand.
   Collapsing them is explicitly forbidden by the repo hard rules.
4. **Scale.** 66 Python files, 7 of them heavy test rewrites (`test_mobile_sync_agent.py` 95 hits,
   `test_index_and_search.py` 43, `test_storage_engine.py` 40, `test_server.py` 34,
   `test_fable_s23_sync.py` 28, `test_adversarial_inputs.py` 27, `test_conflict_and_trash.py` 23). Step B
   is delegated in batches by area, each verified against source, never by find-and-replace.
5. **Parser tightening vs the contract's shorthand** (§2.1). Recorded deliberately; the phone mirror
   must carry the identical tightening or the peers drift on the first URL containing a `#project@`
   fragment.
