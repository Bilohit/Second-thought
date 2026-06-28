# Second Thought — Performance / Redundancy / Simplification Audit

Whole-repo pass over `omni_capture/` (pipeline + server) and `gui/` (React +
Rust). Tests, markdown, HTML, and the `__main__` smoke blocks were skipped.
The first part covers **performance, redundancy, and simplification**; a
**Correctness & Security** pass (`S1–S4`, `C1–C3`) is appended at the end on
request.

Each finding has: the problem, the optimal fix, an Impact×Effort rating, and
pros/cons/risk. Findings are ranked **biggest cut / win first** within tiers.

> **Read the Correctness & Security section first.** It was out of the original
> over-engineering scope, but `S1` (path traversal) and `C1` (approved notes
> vanish from search) are the highest-priority fixes in this document.

> Out of scope by design (left alone, see bottom): `main.py:run_pipeline()` vs
> `server.py:_run_pipeline_blocking()` (CLAUDE.md hard rule), `ponytail:`-marked
> shortcuts whose ceiling isn't hit, the Rust mini-TOML/keymap parser, the
> live-built category Enum (`models.build_capture_model`), and the App.tsx
> window-geometry machinery (every block is a documented DPI bugfix).

---

## Impact × Effort matrix

| | **Low effort** | **Medium effort** | **High effort** |
|---|---|---|---|
| **High impact** | F1 `init_db` per-call rebuild · F4 dead config | F2 vector full-scan cosine | — |
| **Med impact** | F3 geoLog default-on · F7 vision warmup · F11 dual-write log · F19 log level | F5 SSE dedup · F6 cosine dedup · F12 SegmentedControl · F14 link-index cache | — |
| **Low impact** | F8 frontmatter dedup · F10 warmup base_url · F13 focusRing reuse · F15 api error helper · F16 chat updateLast · F17 clipboard branch · F18 notifier dedup · F20 shortcut handler · F21 count cache cap · F23 orphan-purge overlap · F24 startup tasks | — | — |

**Do-first cluster: F1, F4, F3, F7, F11** — all low-effort; F1/F11 cut the
hottest shared paths (search-on-keystroke, every capture write).

---

## F1 — `init_db()` rebuilds schema + triggers on *every* DB call  ★ High impact / Low effort

**Where:** `index_writer.py` — `init_db()` is called by `log_capture_db`, `search`,
`stats`, `remove_capture_by_path`, `upsert_capture_from_file`, `reindex_bodies`,
`migrate_jsonl`, and (transitively) `vault_sync`.

**Problem:** each call runs `executescript(_DDL)` **plus** `_migrate_schema()`,
which on *every* invocation does `PRAGMA table_info`, `_migrate_fts_internal`
(reads `_meta` + maybe `sqlite_master`), `executescript(_TRIGGERS_DDL)`
(**`DROP` + `CREATE` all three FTS triggers unconditionally**), and
`_rebuild_fts_once` (another `_meta` read). `GET /search` fires on every keystroke
in Look, so three triggers are dropped/recreated and four meta queries run *per
character typed*, plus on every capture and stats refresh.

**Optimal fix:** split "open" from "ensure schema"; gate migration once per process
per vault path.
```python
_INITIALIZED: set[str] = set()

def init_db(vault_root: Path) -> sqlite3.Connection:
    db_path = get_db_path(vault_root)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    key = str(db_path)
    if key not in _INITIALIZED:
        conn.executescript(_DDL)
        _migrate_schema(conn)
        _INITIALIZED.add(key)
    return conn
```
DDL/migrations are already idempotent — this stops *repeating* the idempotent work.

- **Pros:** removes 4 queries + 3 trigger DROP/CREATEs from every read; faster search.
- **Cons:** won't re-migrate if the on-disk schema is swapped under a live process
  (not a real scenario — Rust owns the single server process).
- **Risk:** **Low.** Worst case a manual DB swap needs a restart (already happens on config reload).

---

## F2 — Vector retrieval is a full table scan + Python cosine loop, every query  ★ High impact / Medium effort

**Where:** `vector_store.py:_cosine_top_k` / `retrieve_related` / `best_match`,
duplicated in `rag_engine.py:_semantic_ranked`.

**Problem:** every capture (`retrieve_related`) and every chat turn
(`hybrid_retrieve`) does `SELECT * FROM embeddings`, `np.frombuffer`s every BLOB,
and computes cosine **one row at a time in a Python loop**. O(N) Python iteration
+ N small numpy calls per query. Fine at 50 notes, slow by a few thousand.

**Optimal fix:** (1) vectorize — stack once, one matmul, `argpartition` instead of
full sort:
```python
mat = np.vstack([np.frombuffer(b, np.float32) for b in blobs])      # (N, d)
mat /= np.linalg.norm(mat, axis=1, keepdims=True) + 1e-12
sims = mat @ (q / (np.linalg.norm(q) + 1e-12))
top = np.argpartition(-sims, top_k)[:top_k]
```
(2) cache the stacked matrix in-process, keyed on `(count, max_rowid)`; invalidate
on `index_note`/`remove_from_index`/vault-sync.

- **Pros:** order-of-magnitude faster as the vault grows; one shared ranker for capture + chat + best-match.
- **Cons:** cache adds an invalidation surface.
- **Risk:** **Medium.** Math is equivalent; test that an upsert invalidates the cache. Step 1 alone is risk-free.

---

## F3 — `geoLog.ts` diagnostics ship ON by default, wired into the drag hot path  ★ Med impact / Low effort

**Where:** `gui/src/lib/geoLog.ts` (187 lines), 7 call sites in `App.tsx`
(`geoSnapshot("drag.pointerdown")`, `geoClamp` per drag frame + per fling step),
plus a Settings toggle.

**Problem:** the header calls it OBSERVE-ONLY scaffolding for a *past* boundary
investigation, yet `geoEnabled()` defaults to **true** — every drag does
`Promise.all([outerPosition, outerSize, scaleFactor, availableMonitors])` +
`monitorFromPoint` + maps all monitors, throttled per frame.

**Optimal fix:** flip the default to opt-in:
```ts
return localStorage.getItem(GEO_DEBUG_KEY) === "1";   // off unless enabled
```
If the boundary bug is closed, **delete** the module + 7 call sites + test +
Settings toggle (`delete:`, ~200 lines).

- **Pros:** removes 4–5 IPC round-trips from drag-grab; cleaner drag code.
- **Cons:** a recurrence is captured only after re-enabling via the toggle.
- **Risk:** **Low** (flip) / **Low–Med** (delete).

---

## F4 — Dead config keys and constants  ★ High-ish impact (clarity) / Low effort

**Where:** `config.py`, `vector_store.py`.

**Problem:** loaded/defined but never read:
- `cfg.youtube.write_raw_transcript` (`config.py:115,258`) — `create_youtube_note`
  always writes the transcript; the toggle does nothing.
- `cfg.vector.collection` (`config.py:247`) + `COLLECTION_NAME` (`vector_store.py:50`)
  — the table is hardcoded `embeddings`; neither is referenced.
- (`daily_digest.py` is already deleted in the working tree — confirm it's staged.)

**Optimal fix:** delete the three dead declarations and their `.get(...)` loads.

- **Pros:** honest config schema; `grep` stops returning no-op sites.
- **Cons:** drops a "planned" knob (re-add when a user asks).
- **Risk:** **Low.** Pure deletion of unreferenced names.

---

## F5 — SSE frame parsing duplicated 4×  ★ Med impact / Medium effort

**Where:** `api.ts` (`streamCapture` + `streamLookChat`); Python `server.py`
(`_stream_capture` + `_stream_look_chat`). The browser extension mirrors it a 5th time.

**Problem (TS):** both generators repeat the same reader/decoder/`split("\n\n")`/
`event:`+`data:` block (~25 lines each); only the typed `switch` differs.

**Optimal fix (TS):** one `sseFrames(res)` async generator yielding `{event, data}`;
each caller keeps only its switch + `logger` calls.
```ts
async function* sseFrames(res: Response): AsyncGenerator<{event: string; data: string}> {
  const reader = res.body!.getReader(); const dec = new TextDecoder(); let buf = "";
  for (;;) {
    const { done, value } = await reader.read(); if (done) return;
    buf += dec.decode(value, { stream: true });
    const frames = buf.split("\n\n"); buf = frames.pop() ?? "";
    for (const f of frames) {
      if (!f.trim()) continue;
      let event = "message", data = "";
      for (const ln of f.split("\n")) {
        if (ln.startsWith("event: ")) event = ln.slice(7).trim();
        else if (ln.startsWith("data: ")) data = ln.slice(6).trim();
      }
      if (data) yield { event, data };
    }
  }
}
```
**Python:** `_stream_capture`/`_stream_look_chat` are also near-identical
executor-submit + queue-drain wrappers — collapse into one
`_sse_from_blocking(fn, *args)`. (These are pure transport wrappers, *not* the
protected 4-stage pipeline body.)

- **Pros:** ~50 fewer TS lines; one place to fix SSE edge cases.
- **Cons:** thin shared layer to keep per-event logging out of.
- **Risk:** **Medium.** SSE is load-bearing — extract behind existing `*.test.ts`; verify `npm test`.

---

## F6 — Cosine similarity reimplemented in `rag_engine`  ★ Med impact / Medium effort

**Where:** `rag_engine.py:_semantic_ranked` hand-rolls the normalize-and-dot loop
that `vector_store.py:_cosine_top_k` already owns (and rag already imports `_embed`,
`_connect`, `_MAX_SNIPPET_CHARS` from it).

**Optimal fix:** fold into F2 — expose one vectorized ranker in `vector_store`
returning `[(rel, sim)]`; `_semantic_ranked` calls it and keeps only its RRF shaping.

- **Pros:** single similarity path; rag inherits the F2 speedup.
- **Cons:** `vector_store`'s public surface grows by one function.
- **Risk:** **Medium.** Gate behind existing rag/vector smoke tests.

---

## F7 — Per-capture vision warmup is a full extra `/api/generate` round-trip  ★ Med impact / Low effort

**Where:** `enrichment_router.py:_enrich_image` (the `warmup_body` call, timeout 120s).

**Problem:** *every* image capture fires a throwaway `/api/generate` "ready" call
before the real describe. But after the first image the vision model is resident
for `keep_alive` (30m), so every later screenshot pays an extra full round-trip.

**Optimal fix:** gate the warmup to once per process.
```python
_VISION_WARMED = False
...
if not _VISION_WARMED:
    # existing warmup call
    _VISION_WARMED = True
```
The 90s first-attempt timeout + retries already absorb a cold start if skipped.

- **Pros:** removes a full vision round-trip from every screenshot after the first.
- **Cons:** the first capture after eviction (idle > keep_alive) cold-loads on the real call (timeout already covers it).
- **Risk:** **Low.** Optimization either way; warmup is explicitly non-fatal.

---

## F8 — Frontmatter-strip / field-extract regex repeated  ★ Low impact / Low effort

**Where:** the `^---\n.*?\n---\n` strip is in `index_writer._read_body_excerpt`,
`rag_engine._read_snippet`, `storage_engine.get_scratchpad_item_text`;
`_extract_frontmatter_field`/`_read_note_tags`/`link_resolver._parse_aliases` each
re-parse frontmatter too.

**Optimal fix:** one small helper module — `strip_frontmatter(text)` +
`read_field(text, name)`. `shrink:` — one definition.

- **Pros:** one regex to fix if the convention changes; ~15 fewer lines.
- **Risk:** **Low.** Mechanical; covered by existing smoke tests.

---

## F10 — Startup `_warm_model` reimplements the `/v1` base-url logic  ★ Low impact / Low effort

**Where:** `server.py:_warm_model` hand-builds `base += "/v1"` + a raw `OpenAI`
client, duplicating `llm_engine._normalize_base_url` / `OLLAMA_API_KEY` (already
reused in `_run_look_chat_blocking` and the YouTube job).

**Optimal fix:** import and reuse them — one definition of the `/v1` boundary the
CLAUDE.md hard rule cares about.

- **Risk:** **Low.** Same call, fewer literals.

---

## F11 — Capture log dual-writes JSONL + SQLite on every capture  ★ Med impact / Low–Med effort

**Where:** `capture_log.py:log_capture` (writes `captures.jsonl` *and* upserts
`captures.db`); the module docstring calls JSONL "legacy, transition period."

**Problem:** every capture appends a JSON line whose only consumers are the CLI
viewer (`python main.py --log` → `read_log`/`print_stats`) and the one-shot
`migrate_jsonl`. The DB already has `stats()` and `search()` covering the same
data. So JSONL is a second write + a parallel store kept only for a CLI that could
read the DB.

**Optimal fix:** point `print_recent`/`print_stats` at `index_writer.stats()` /
`search()` (DB is the source of truth for *derived* data — consistent with the
CLAUDE.md "files are truth, DB/indexes are derived" rule, since both are derived
indexes), then drop the JSONL write. Keep `migrate_jsonl` for one release as the
upgrade path, then delete.

- **Pros:** one write per capture instead of two; removes a parallel store and its drift risk.
- **Cons:** `--log` output now depends on the DB being initialized (it always is post-capture).
- **Risk:** **Low–Med.** The transition period the docstring names has plausibly elapsed — verify no external tooling tails the JSONL first.

---

## F12 — SettingsPanel repeats the same segmented-toggle button group ~8×  ★ Med impact / Medium effort

**Where:** `SettingsPanel.tsx` — Display Mode, Corner, Stay Pinned, Display picker,
Fan Style, Snap, Strictness, Auto-describe, Geo, Look-persist each render an
identical `.map` of buttons (`...BTN_SECONDARY, flex:1, background active?accent…,
aria-pressed`). ~25–30 lines × ~8 ≈ 240 lines of copy-paste.

**Optimal fix:** one small component:
```tsx
function SegmentedControl<T extends string>({ value, options, onChange }: {
  value: T; options: { v: T; label: string }[]; onChange: (v: T) => void;
}) {
  return <div style={{ display: "flex", gap: 4 }}>{options.map(({ v, label }) => {
    const active = value === v;
    return <button key={v} onClick={() => onChange(v)} className="btn-hover" aria-pressed={active}
      style={{ ...BTN_SECONDARY, flex: 1,
        background: active ? "var(--accent)" : (BTN_SECONDARY.background as string),
        color: active ? "var(--on-accent)" : (BTN_SECONDARY.color as string),
        borderColor: active ? "var(--accent)" : "var(--border)" }}>{label}</button>;
  })}</div>;
}
```
Each `Field` then wraps one `<SegmentedControl>` + its help `<span>`.

- **Pros:** ~200 fewer lines; one toggle style to restyle; a11y attributes defined once.
- **Cons:** the Snap group's disabled/opacity state needs a prop (`disabled`).
- **Risk:** **Medium.** Pure view refactor — eyeball each group after; no logic change.

---

## F13 — SettingsPanel inlines the focus-ring that already exists as a helper  ★ Low impact / Low effort

**Where:** `SettingsPanel.tsx` vault + model inputs hand-write `onFocus`/`onBlur`
that set `borderColor`/`boxShadow` inline — the exact behavior `focusRing`/`blurRing`
in `ui/styles.ts` already provide (and that `VaultManager.tsx` imports).

**Optimal fix:** `onFocus={focusRing} onBlur={blurRing}` — delete the two inline blocks.

- **Risk:** **Low.** Same visual; helper is already in use elsewhere.

---

## F14 — `build_link_index` walks the whole vault + reads every note's frontmatter, per capture  ★ Med impact / Medium effort

**Where:** `link_resolver.py:build_link_index`, called from
`storage_engine._try_inject_wikilinks` → `write_to_vault` on **every** capture.

**Problem:** each capture `rglob("*.md")`s the entire vault and calls `_parse_aliases`
(a `read_text`) on every file just to build the wikilink display-name index, then
throws it away. O(vault size) file reads per single capture write.

**Optimal fix:** cache the index in-process, invalidated on `(file count, max mtime)`
or rebuilt during vault-sync. Same caching pattern as F2.
```python
# ponytail: invalidate on (count, max_mtime); rebuild on vault sync.
```

- **Pros:** capture write no longer scales with vault size; big win on large vaults.
- **Cons:** cache invalidation surface; new notes from other sources need a sync to appear as link targets (already true between syncs for the embed index).
- **Risk:** **Medium.** Add one check that a new note invalidates the cache.

---

## F15 — api.ts repeats the error-body extraction 7×  ★ Low impact / Low effort

**Where:** `api.ts` — 7 copies of `const body = await r.json().catch(() => ({}));
throw new Error(body.detail ?? "…")`.

**Optimal fix:** one helper:
```ts
async function assertOk(r: Response, fallback: string): Promise<Response> {
  if (r.ok) return r;
  const body = await r.json().catch(() => ({} as { detail?: string }));
  throw new Error(body.detail ?? fallback);
}
```

- **Risk:** **Low.** Mechanical.

---

## F16 — useLookChat repeats the "patch last message" closure 4×  ★ Low impact / Low effort

**Where:** `useLookChat.ts` — `setMessages((prev) => { const n=[...prev];
n[n.length-1]={...n[n.length-1], …}; return n; })` for meta/sources/token/error.

**Optimal fix:** one local `updateLast(patch | (m)=>patch)` helper that does the
clone-and-replace once.

- **Risk:** **Low.** Same state shape.

---

## F17 — interceptor's Windows and Darwin image branches are identical  ★ Low impact / Low effort

**Where:** `interceptor.py:_try_read_image_from_clipboard` — the `"Windows"` and
`"Darwin"` arms are byte-for-byte the same (`from PIL import ImageGrab`,
`grabclipboard()`, save PNG to `BytesIO`).

**Optimal fix:** `if os_name in ("Windows", "Darwin"):` one shared block; keep Linux
(`xclip`) separate.

- **Risk:** **Low.** `yagni:`/`shrink:`; same behavior.

---

## F18 — notifier duplicates the plyer fallback + title build across Windows/Linux  ★ Low impact / Low effort

**Where:** `notifier.py:_notify_windows` / `_notify_linux` both compute
`full_title = f"{title} — {subtitle}"` and both carry the same plyer
`try/except` fallback.

**Optimal fix:** a `_plyer_notify(full_title, message)` helper called by both; build
`full_title` once in `send_notification` and pass it down.

- **Risk:** **Low.** Same backends, less copy-paste.

---

## F19 — Frontend log level defaults to TRACE in production  ★ Med impact / Low effort

**Where:** `logger.ts:initialLevel()` returns `LogLevel.TRACE` by default.

**Problem:** combined with F3 (geoLog on), a packaged build writes TRACE lines for
every drag frame, every API timer, every stream event to disk via batched
`append_log` IPC — heavy log churn for a shipped app. The infra (batching, rotation,
drop-oldest) is good; the *default verbosity* is the issue.

**Optimal fix:** default to `INFO` (or `DEBUG`) when no override is set; keep the
Settings toggle + `VITE_LOG_LEVEL` for opting into TRACE during diagnosis.
```ts
return LogLevel.INFO;   // was LogLevel.TRACE
```

- **Pros:** far less disk/IPC traffic in normal use; TRACE still one toggle away.
- **Cons:** a bug report needs the user to bump the level first (acceptable; that's what the toggle is for).
- **Risk:** **Low.** Pairs naturally with F3.

---

## F20 — lib.rs duplicates the hotkey `on_shortcut` handler body 3×  ★ Low impact / Low effort

**Where:** `lib.rs` — the closure `if event.state == ShortcutState::Pressed {
show_window_emit_debounced(&app, "trigger-capture") }` is written out in `setup`,
in `set_hotkey` (register), and again in `set_hotkey` (rollback).

**Optimal fix:** a small `register_capture_shortcut(app, shortcut) -> Result<…>`
that installs the handler; call it from all three sites.

- **Risk:** **Low.** Same registration, one definition.

---

## F21 — summarizer's `_count_cache` is an unbounded dict keyed on full text  ★ Low impact / Low effort

**Where:** `summarizer.py:_count_cache` (and `_tokenize_available`) grow without
bound, keyed on `sha256(base_url|model|text)`.

**Problem:** a long-lived server summarizing many large transcripts accumulates one
entry per distinct text forever. Small in practice, but unbounded.

**Optimal fix:** cap it — `functools.lru_cache(maxsize=…)` on a `(base_url, model,
text)` wrapper, or a manual size cap with a `ponytail:` note. The existing
"propose-then-verify" already keeps call volume low, so a modest cap is plenty.
```python
# ponytail: unbounded count cache; cap to N entries if a server runs for days.
```

- **Risk:** **Low.** Cache is a pure optimization; eviction only recomputes.

---

## F23 — `purge_orphan_index_entries` is a subset of `sync_vault_indexes`  ★ Low impact / Low effort

**Where:** `vault_sync.py` — `purge_orphan_index_entries` (startup) re-implements
the orphan-removal half of `sync_vault_indexes` against the captures table.

**Optimal fix:** have `sync_vault_indexes` call `purge_orphan_index_entries` for the
captures-table orphan pass (keep the embeddings-only pass separate), so removal
logic lives once. Minor; the two are already close.

- **Risk:** **Low.** Same DB ops, deduplicated.

---

## F24 — Three independent startup background tasks each open the DB  ★ Low impact / Low effort

**Where:** `server.py` — `_warm_model`, `_reindex_bodies`, `_purge_orphan_index_entries`
are three separate `@app.on_event("startup")` handlers, each submitting to
`_bg_executor`; two of them open the DB independently.

**Optimal fix:** optional — one boot worker that runs reindex + purge sequentially
(they touch the same DB) and kicks the model warmup. After F1 the repeated
`init_db` is cheap, so this is cosmetic; fold only if touching this area anyway.

- **Risk:** **Low.** Ordering is independent; mainly tidiness.

---

---

# Correctness & Security pass

Added on request — outside the over-engineering scope above. Severity-ranked,
worst first. These are **not** simplification findings; treat them as bugs.

## Severity summary

| ID | Type | Severity | One line |
|----|------|----------|----------|
| S1 | Security | **High** | Path traversal in `/inbox/{id}/approve` — write a note outside the vault |
| C1 | Correctness | **High** | Approved inbox notes are never re-indexed → gone from search until next sync |
| S2 | Security | Medium | SSRF — `/share` + URL enrichment fetch any host (localhost, cloud metadata) |
| C2 | Correctness | Medium | Frontmatter field reads match anywhere in the note, not just the `---` block |
| S3 | Security | Low–Med | Auth disabled when secret unset; secret compared non-constant-time |
| S4 | Security | Low | No size cap on base64 image/audio decode → memory DoS |
| C3 | Correctness | Low | `_safe_name` permits trailing dot/space → Windows name collisions |

---

## S1 — Path traversal in `/inbox/{note_id}/approve` (`target_category`)  ★ Security / High

**Where:** `server.py:approve_inbox` → `storage_engine.approve_scratchpad_item`.

**Problem:** every other category endpoint (`create`/`rename`/`delete`) routes the
name through `_safe_category_dir`, which rejects path separators and traversal.
`approve_inbox` does **not** — it passes `body.target_category` straight through:
```python
is_new = bool(body.target_category) and not (root / body.target_category).exists()
dest = approve_scratchpad_item(note_id, root, ..., target_category=body.target_category)
```
and `approve_scratchpad_item` does `dest_dir = vault_root / category;
dest_dir.mkdir(parents=True, exist_ok=True); dest_path.write_text(...)`. A
`target_category` of `../../Users/biloh/AppData/.../Startup` (or any `..\`-laden
string) creates directories and writes a `.md` file **outside the vault** — an
arbitrary-location file-write primitive. Reachable by anything that can call the
local API with the secret (the browser extension, any local process if the secret
is unset — see S3).

**Optimal fix:** validate `target_category` through the same `_safe_category_dir`
guard before use, in the endpoint:
```python
if body.target_category:
    _safe_category_dir(root, body.target_category)   # raises HTTP 400 on traversal
```
and/or sanitize inside `approve_scratchpad_item` (defense in depth) by rejecting any
`category` whose resolved path's parent isn't the vault root.

- **Risk of fix:** **Low.** Reuses the existing validated helper; only rejects names that were already invalid as folders.

---

## C1 — Approved inbox notes are never re-indexed  ★ Correctness / High

**Where:** `server.py:approve_inbox` → `storage_engine.approve_scratchpad_item`.

**Problem:** `approve_scratchpad_item` moves the note out of the scratchpad and
**removes** its old index rows:
```python
remove_from_index(vault_root, item)        # vectors.db
remove_capture_by_path(vault_root, item)   # captures.db
```
Its own comment says *"caller re-indexes the dest path"* — but the caller
(`approve_inbox`) never does. Nothing inserts the destination path into `captures.db`
(FTS) or `vectors.db`. So an approved note **disappears from search and semantic
retrieval** entirely until the next `/vault/sync-index` or a server-startup pass
happens to pick it up. The note is on disk and visible in Obsidian, but invisible to
Look/Chat — a silent data-availability bug.

**Optimal fix:** re-index the destination in `approve_inbox` after the move (mirrors
the capture pipeline's index tail):
```python
from index_writer import upsert_capture_from_file
from vector_store import index_note
upsert_capture_from_file(root, dest)
if cfg.vector.enabled:
    note_text = dest.read_text(encoding="utf-8", errors="ignore")
    index_note(root, dest, note_text, cfg.ollama.base_url, cfg.vector.embed_model)
```
(Or move the re-index inside `approve_scratchpad_item` so the comment becomes true
and every caller is covered.)

- **Risk of fix:** **Low.** Same index calls the capture path already uses; failures there are best-effort/swallowed.

---

## S2 — SSRF via `/share` and URL enrichment  ★ Security / Medium

**Where:** `enrichment_router.py:_enrich_web_url` / `_enrich_github_url` /
`_fetch_youtube_title` / `fetch_youtube_transcript` (all `urllib.request.urlopen`),
reachable from `server.py:/share` and `/capture`.

**Problem:** the server fetches **any** http(s) URL it's handed — including
`http://localhost:…`, `http://127.0.0.1`, `http://169.254.169.254/…` (cloud
metadata), and internal LAN hosts — then stores the response body in the vault. The
`/share` endpoint (browser extension) and a clipboard URL both reach this with no
host restriction. Classic SSRF; on a workstation the blast radius is local services
and any reachable intranet.

**Optimal fix:** before `urlopen`, resolve the host and reject private/loopback/
link-local/reserved ranges:
```python
import ipaddress, socket
def _public_host_or_raise(url: str) -> None:
    host = urllib.parse.urlparse(url).hostname or ""
    for fam, _, _, _, sa in socket.getaddrinfo(host, None):
        ip = ipaddress.ip_address(sa[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError(f"refusing to fetch non-public host {host} ({ip})")
```
Call it in each fetch helper. Keep a config opt-out for users who *do* capture from a
private wiki, defaulting to block.

- **Cons:** blocks legitimately-captured intranet pages unless opted in.
- **Risk of fix:** **Low–Med.** Adds a DNS round-trip per fetch; TOCTOU-imperfect (rebinding) but closes the common case.

---

## C2 — Frontmatter field reads match anywhere in the note  ★ Correctness / Medium

**Where:** `storage_engine._extract_frontmatter_field` (regex `^field:\s*(.+)$` with
`re.MULTILINE` over the whole text), used by `_find_scratchpad_item` and
`list_scratchpad` for `note_id` / `category`.

**Problem:** the pattern isn't anchored to the leading `---…---` block, so a note
whose **body** contains a line like `category: Finance` (e.g. a captured code snippet
or quoted YAML) is mis-read as that note's category — wrong inbox grouping, and a
wrong `note_id` extraction can mis-route approve/discard to the wrong file.

**Optimal fix:** extract the frontmatter block first, then match only within it
(reuse the F8 `strip_frontmatter`/`read_field` helper):
```python
m = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
block = m.group(1) if m else ""
field = re.search(rf"^{re.escape(name)}:\s*(.+)$", block, re.MULTILINE)
```

- **Risk of fix:** **Low.** Narrows matching to the correct region; pairs with F8.

---

## S3 — Auth silently disabled when secret unset; non-constant-time compare  ★ Security / Low–Med

**Where:** `server.py:_require_secret`.

**Problem:** two things. (1) When `OMNI_GUI_SECRET` is unset the check returns
immediately (`if not _GUI_SECRET: return`) — every endpoint is open to any local
process. The normal Rust launch always sets it, but a manually-started `uvicorn`
(documented in CLAUDE.md) runs wide open, which is also exactly the state S1's
traversal needs to be reachable without the secret. (2) The comparison
`x_omni_secret != _GUI_SECRET` is not constant-time.

**Optimal fix:** keep the dev-convenience bypass but log louder and bind only to
loopback (uvicorn already defaults to 127.0.0.1 — keep it, never `--host 0.0.0.0`);
compare with `hmac.compare_digest(x_omni_secret or "", _GUI_SECRET)`.

- **Risk of fix:** **Low.** `compare_digest` is a drop-in; the bypass behavior is unchanged for dev.

---

## S4 — No size cap on base64 image/audio decode  ★ Security / Low

**Where:** `server.py:_run_pipeline_blocking` — `base64.b64decode(content)` for
`image_b64` / `audio_b64` with no length check.

**Problem:** a single large payload is fully decoded into memory (and audio is then
written to a temp file) with no bound — a cheap local memory/disk DoS.

**Optimal fix:** reject oversized `content` early (e.g. cap encoded length to a
configurable few-MB ceiling) in the `CaptureRequest` handling before decode.

- **Risk of fix:** **Low.** A generous cap never hits a real screenshot/clip.

---

## C3 — `_safe_name` permits trailing dot/space  ★ Correctness / Low

**Where:** `server.py:_safe_name` (`re.sub(r"[^\w\-. ]", "_", name).strip()`).

**Problem:** `.strip()` removes leading/trailing whitespace but a name like `"Notes."`
or `"Notes "` (interior) can still yield a trailing dot/space, which Windows silently
strips when creating the directory — so `"Notes."` and `"Notes"` collide, and rename
round-trips can land on an unexpected folder.

**Optimal fix:** also strip trailing dots/spaces from the cleaned segment:
`cleaned = re.sub(r"[. ]+$", "", cleaned)` before the empty/`.`/`..` checks in
`_safe_category_dir`.

- **Risk of fix:** **Low.** Tightens an edge case; normal names unaffected.

---

## Explicitly NOT changed (intentional)

- **`main.py:run_pipeline()` ⟷ `server.py:_run_pipeline_blocking()`** — CLAUDE.md
  hard rule: hand-duplicated by design. F5 touches only the SSE *transport*
  wrappers, never the 4-stage body.
- **`models.build_capture_model` rebuilding the category Enum every capture** —
  required by the "categories are never hardcoded" hard rule; cheap, leave it.
- **`pre_resolver` hardcoded Finance/CRM fast paths** — deliberate heuristics,
  documented; gated on the folder actually existing.
- **`ponytail:`-marked shortcuts** (unbounded tag cache, full FTS rebuild,
  fixed-scale drag, `$HOME/**` open scope) — each names its ceiling; leave until hit.
- **Rust mini-TOML / keymap parser** — deliberate per CLAUDE.md, not a missing dep.
- **App.tsx window-geometry machinery / logger infrastructure** — dense but each
  block is a real DPI/crash-logging fix. Don't "simplify" without reproducing the
  original bug first.

---

## Suggested order

1. **F1** (init_db gate) + **F11** (drop JSONL dual-write) — biggest write/read-path wins, low risk.
2. **F4** (delete dead config) — free clarity.
3. **F3** (geoLog default-off) + **F19** (log level) + **F7** (warmup gate) — one-line latency/IO wins.
4. **F2 + F6** (vectorize + dedupe cosine) and **F14** (link-index cache) — the growth-path wins.
5. **F12** (SegmentedControl), **F5** (SSE dedup) — biggest LOC cuts.
6. **F8, F10, F13, F15–F18, F20, F21, F23, F24** — mop-up dedup/shrink once the above land.

`net: ~−700 lines possible (geoLog delete ~200, SettingsPanel SegmentedControl ~200,
SSE/cosine/frontmatter/api/notifier/chat dedup ~250, dead config + JSONL path ~50),
0 deps removed (numpy/stdlib already present). Largest runtime wins: F1, F2, F11, F14.`
