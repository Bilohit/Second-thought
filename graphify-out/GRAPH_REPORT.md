# Graph Report - .  (2026-06-19)

## Corpus Check
- 0 files · ~0 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1073 nodes · 1998 edges · 75 communities (70 shown, 5 thin omitted)
- Extraction: 84% EXTRACTED · 16% INFERRED · 0% AMBIGUOUS · INFERRED: 310 edges (avg confidence: 0.7)
- Token cost: 1,200 input · 2,800 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 68|Community 68]]
- [[_COMMUNITY_Community 69|Community 69]]

## God Nodes (most connected - your core abstractions)
1. `write_to_vault()` - 51 edges
2. `CaptureOutput` - 40 edges
3. `EnrichedPayload` - 38 edges
4. `pre_resolve()` - 29 edges
5. `TempVault` - 27 edges
6. `run_pipeline()` - 25 edges
7. `_vault()` - 24 edges
8. `_ep()` - 22 edges
9. `_make()` - 20 edges
10. `InputPayload` - 18 edges

## Surprising Connections (you probably didn't know these)
- `Path` --uses--> `EnrichedPayload`  [INFERRED]
  omni_capture/pre_resolver.py → omni_capture/models.py
- `CaptureOutput` --uses--> `CaptureOutput`  [INFERRED]
  omni_capture/test_dedup_and_inbox.py → omni_capture/models.py
- `log_capture()` --calls--> `get_config()`  [INFERRED]
  omni_capture/capture_log.py → omni_capture/config.py
- `log_capture()` --calls--> `log_capture_db()`  [INFERRED]
  omni_capture/capture_log.py → omni_capture/index_writer.py
- `run_pipeline()` --calls--> `log_capture()`  [INFERRED]
  omni_capture/main.py → omni_capture/capture_log.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Content Processing Pipeline** —  [INFERRED]
- **User Interaction Methods** —  [INFERRED]

## Communities (75 total, 5 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.05
Nodes (28): build_link_index(), inject_wikilinks(), _parse_aliases(), _protect(), Path, link_resolver.py ---------------- Vault-aware wikilink injector for Second Thoug, Return a mapping of ``{display_name: vault_relative_stem}`` for every     .md fi, Insert ``[[wikilinks]]`` into *content* where known note names appear.      Para (+20 more)

### Community 1 - "Community 1"
Cohesion: 0.06
Nodes (59): Execute the full Second Thought pipeline.      Returns the dict representation o, run_pipeline(), best_match(), _connect(), _cosine_top_k(), count(), _db_path(), _embed() (+51 more)

### Community 2 - "Community 2"
Cohesion: 0.10
Nodes (31): _file_hash(), get_db_path(), init_db(), log_capture_db(), migrate_jsonl(), Connection, Path, index_writer.py --------------- SQLite index for every Second Thought note.  Dat (+23 more)

### Community 3 - "Community 3"
Cohesion: 0.10
Nodes (20): NamedTuple, _ep(), pre_resolve(), EnrichedPayload, Path, pre_resolver.py --------------- Cheap deterministic resolver for the Second Thou, John Smith' â†’ 'john-smith, Examine enriched_text and infer the likely target path + existing context     wi (+12 more)

### Community 4 - "Community 4"
Cohesion: 0.10
Nodes (41): App, AppHandle, Arc, Child, File, Path, Mutex, Option (+33 more)

### Community 5 - "Community 5"
Cohesion: 0.08
Nodes (30): _check_vision_model_available(), _degraded_image_payload(), _downscale_image(), _enrich_github_url(), _enrich_image(), _enrich_web_url(), _enrich_youtube_url(), _extract_code_blocks_from_transcript() (+22 more)

### Community 6 - "Community 6"
Cohesion: 0.08
Nodes (30): Namespace, CaptureConfig, Config, load_config(), LogConfig, NotificationConfig, OCRConfig, OllamaConfig (+22 more)

### Community 7 - "Community 7"
Cohesion: 0.10
Nodes (30): get_config(), approve_inbox(), capture_stats(), create_category(), delete_category(), discard_inbox(), _get_job(), _get_vault_root() (+22 more)

### Community 8 - "Community 8"
Cohesion: 0.07
Nodes (29): dependencies, @fontsource/geist-mono, react, react-dom, @tauri-apps/api, @tauri-apps/plugin-clipboard-manager, @tauri-apps/plugin-dialog, @tauri-apps/plugin-global-shortcut (+21 more)

### Community 9 - "Community 9"
Cohesion: 0.11
Nodes (27): _build_deterministic_append(), _content_hash(), create_youtube_note(), ensure_category(), init_vault(), _normalize_content(), _normalize_url(), storage_engine.py  -- Step 4: Storage Engine  Dynamic category edition --------- (+19 more)

### Community 10 - "Community 10"
Cohesion: 0.13
Nodes (20): Props, approveInboxItem(), authHeaders(), CaptureEvent, createVaultCategory(), deleteVaultCategory(), discardInboxItem(), DoneEvent (+12 more)

### Community 11 - "Community 11"
Cohesion: 0.19
Nodes (22): AsyncOpenAI, BaseModel, InputPayload, Match, CaptureOutput, InputPayload, Raw, unprocessed input from the clipboard., CaptureOutput (+14 more)

### Community 12 - "Community 12"
Cohesion: 0.17
Nodes (11): Write/append a CaptureOutput to the vault.      Routing     -------     1. Dedup, write_to_vault(), _make(), CaptureOutput, test_dedup_and_inbox.py ----------------------- Pytest suite covering:    1. Con, For appendable categories (Tech_Notes etc.), a second capture with the         s, _unique_file_path collision avoidance is exercised by approve_scratchpad_item, Query params in different order â†’ same hash. (+3 more)

### Community 13 - "Community 13"
Cohesion: 0.08
Nodes (23): app, security, trayIcon, windows, build, beforeBuildCommand, beforeDevCommand, devUrl (+15 more)

### Community 14 - "Community 14"
Cohesion: 0.12
Nodes (16): Props, Props, statusConfig, StatusMeta, BackgroundJobState, BLANK_STATE, CaptureState, CaptureStep (+8 more)

### Community 15 - "Community 15"
Cohesion: 0.13
Nodes (19): _append_general(), build_category_descriptions(), check_duplicate(), _dedup_index_path(), discover_categories(), _is_same_topic(), _load_dedup_index(), Path (+11 more)

### Community 16 - "Community 16"
Cohesion: 0.25
Nodes (6): _entry(), Path, test_search_endpoint.py ----------------------- Integration tests for the /searc, Each test creates an isolated temporary vault, seeds the DB,     then monkeypatc, TestSearchEndpoint, TestStatsEndpoint

### Community 17 - "Community 17"
Cohesion: 0.11
Nodes (18): action, default_icon, default_popup, background, service_worker, 128, 16, 48 (+10 more)

### Community 18 - "Community 18"
Cohesion: 0.16
Nodes (17): Exception, Instructor, _build_system_prompt(), _make_client(), _mock_client(), _normalize_base_url(), llm_engine.py - Step 3: LLM Decision Engine (Read-Before-Write)  Category-agnost, Sync wrapper around summarize_async for the single-pass path and tests. (+9 more)

### Community 19 - "Community 19"
Cohesion: 0.11
Nodes (17): compilerOptions, allowImportingTsExtensions, isolatedModules, jsx, lib, module, moduleResolution, noEmit (+9 more)

### Community 20 - "Community 20"
Cohesion: 0.17
Nodes (10): discard_scratchpad_item(), _extract_frontmatter_field(), _find_scratchpad_item(), list_scratchpad(), Return metadata for all notes in the scratchpad folder., Permanently delete a scratchpad note., Path, TestDiscardInbox (+2 more)

### Community 21 - "Community 21"
Cohesion: 0.26
Nodes (14): date, build_digest(), _format_date_iso(), _format_date_label(), main(), _obsidian_link(), Path, daily_digest.py --------------- Generates a daily journal entry summarising toda (+6 more)

### Community 22 - "Community 22"
Cohesion: 0.13
Nodes (15): definitions, Identifier, Number, PermissionEntry, ShellScopeEntryAllowedArgs, Target, oneOf, anyOf (+7 more)

### Community 23 - "Community 23"
Cohesion: 0.13
Nodes (15): definitions, Identifier, Number, PermissionEntry, ShellScopeEntryAllowedArgs, Target, oneOf, anyOf (+7 more)

### Community 24 - "Community 24"
Cohesion: 0.21
Nodes (9): HotkeyRecorder(), Props, Config, getConfig(), patchConfig(), formatHotkey(), getGuiSecret(), setHotkey() (+1 more)

### Community 25 - "Community 25"
Cohesion: 0.30
Nodes (5): approve_scratchpad_item(), Move a scratchpad note to its final category directory.     Strips status: needs, Remove status: needs_review and note_id from frontmatter.     If the target cate, _rewrite_frontmatter_for_approval(), TestApproveInbox

### Community 26 - "Community 26"
Cohesion: 0.23
Nodes (12): _applescript_escape(), notify_capture_error(), notify_capture_success(), _notify_linux(), _notify_macos(), _notify_windows(), notifier.py ----------- Cross-platform desktop notifications for Second Thought., Convenience wrapper for a successful vault write. (+4 more)

### Community 27 - "Community 27"
Cohesion: 0.18
Nodes (6): CategoryCardProps, ModalState, Props, updateCategoryDescription(), VaultCategory, VaultFile

### Community 28 - "Community 28"
Cohesion: 0.24
Nodes (12): YouTubeConfig, _build_frontmatter(), _category_str(), find_merge_target(), CaptureOutput, Return category as a plain string (handles str-Enum members safely)., Build YAML frontmatter with a flat schema shared across all categories.      Fie, Locate an existing note in the capture's category that this content     should b (+4 more)

### Community 29 - "Community 29"
Cohesion: 0.17
Nodes (12): Background worker driving the four-phase async YouTube pipeline:        fetching, _run_youtube_job(), finalize_youtube_note(), _postprocess_content(), Phase 4: replace the placeholder summary region (marked by     _YOUTUBE_SUMMARY_, Remove common LLM preamble padding (e.g. "Here is a summary:") when it     appea, Truncate on a paragraph boundary and mark truncation. No-op when     max_chars <, Markdown-aware content trim: strip trailing whitespace per line, collapse     3+ (+4 more)

### Community 30 - "Community 30"
Cohesion: 0.24
Nodes (8): CaptureOverlay(), confidenceColor(), Footer(), JOB_STATUS_LABEL, ThinkingPanel(), useHotkeyLabel(), useTrayHintVisible(), ThinkingState

### Community 31 - "Community 31"
Cohesion: 0.22
Nodes (9): buildCommands(), Command, CommandPalette(), filterCommands(), PaletteAction, Props, STATIC_COMMANDS, searchCaptures() (+1 more)

### Community 32 - "Community 32"
Cohesion: 0.18
Nodes (11): properties, description, type, default, description, type, identifier, local (+3 more)

### Community 33 - "Community 33"
Cohesion: 0.18
Nodes (11): properties, description, type, default, description, type, identifier, local (+3 more)

### Community 34 - "Community 34"
Cohesion: 0.20
Nodes (10): Browser Extension, Clipboard-Free Design, Community Skills, Developer Mode Setup, Extension Settings, Manifest V3, OMNI_GUI_SECRET, Second Thought Project (+2 more)

### Community 35 - "Community 35"
Cohesion: 0.22
Nodes (6): useCapture(), App(), Theme, THEME_LABELS, THEMES, View

### Community 36 - "Community 36"
Cohesion: 0.40
Nodes (9): Get-NewestWriteTime(), Invoke-BuildIfStale(), Start-App(), Start-DevMode(), Test-AlreadyRunning(), Test-Port7070(), Test-Preconditions(), Wait-ForReady() (+1 more)

### Community 37 - "Community 37"
Cohesion: 0.29
Nodes (5): _make(), Two gaming-mice captures with different filenames but strong shared         tags, No shared tags -> never merge, even in the same category., A single shared tag is not enough confidence on its own., TestSmartMerge

### Community 38 - "Community 38"
Cohesion: 0.20
Nodes (10): $ref, description, items, type, uniqueItems, description, items, type (+2 more)

### Community 39 - "Community 39"
Cohesion: 0.20
Nodes (10): type, webviews, windows, items, description, items, type, description (+2 more)

### Community 40 - "Community 40"
Cohesion: 0.20
Nodes (10): $ref, description, items, type, uniqueItems, description, items, type (+2 more)

### Community 41 - "Community 41"
Cohesion: 0.20
Nodes (10): type, webviews, windows, items, description, items, type, description (+2 more)

### Community 42 - "Community 42"
Cohesion: 0.22
Nodes (4): Props, TILE_LABEL, getStats(), Stats

### Community 43 - "Community 43"
Cohesion: 0.28
Nodes (8): log_capture(), print_recent(), print_stats(), EnrichedPayload, capture_log.py -------------- Dual-write audit trail for every Second Thought ru, Dual-write: append to captures.jsonl AND upsert into captures.db.     Fails sile, Return the last n log entries, newest first., read_log()

### Community 44 - "Community 44"
Cohesion: 0.22
Nodes (4): Genuine re-capture into the same decided category still dedups., The reported bug: two unrelated captures sharing a source URL were         treat, The reported bug: a capture decided as CRM was silently short-circuited, TestRoutingBugFix

### Community 45 - "Community 45"
Cohesion: 0.29
Nodes (8): Enrichment Router, LLM Engine, server.py, /share Endpoint, Storage Engine, Text Path, URL Path, Vault

### Community 46 - "Community 46"
Cohesion: 0.25
Nodes (8): capture(), _is_duplicate_request(), Return True and log if this request was already accepted recently., Browser-extension / OS share-target endpoint.      Accepts a URL + optional sele, _request_hash(), share(), _sse(), _stream_capture()

### Community 47 - "Community 47"
Cohesion: 0.25
Nodes (8): description, properties, required, type, CapabilityRemote, urls, description, type

### Community 48 - "Community 48"
Cohesion: 0.25
Nodes (8): description, properties, required, type, CapabilityRemote, urls, description, type

### Community 49 - "Community 49"
Cohesion: 0.29
Nodes (7): Capture Feature, Content Capture, Content Enrichment, Pipeline Animation, Popup UI, Right-Click Menu, Status Badge

### Community 51 - "Community 51"
Cohesion: 0.33
Nodes (5): description, identifier, permissions, $schema, windows

### Community 53 - "Community 53"
Cohesion: 0.40
Nodes (5): _enrich_audio(), Transcribe an audio file using a locally running Whisper model.      Requires: `, Path, _run_pipeline_blocking(), _set_job()

### Community 54 - "Community 54"
Cohesion: 0.40
Nodes (4): anyOf, description, $schema, title

### Community 55 - "Community 55"
Cohesion: 0.40
Nodes (4): anyOf, description, $schema, title

### Community 56 - "Community 56"
Cohesion: 0.50
Nodes (3): build_capture_model(), models.py - Pydantic schemas for the LLM Decision Engine structured output.  Cat, Return a CaptureOutput subclass whose 'category' field is constrained     to exa

### Community 57 - "Community 57"
Cohesion: 0.50
Nodes (4): description, required, type, Capability

### Community 58 - "Community 58"
Cohesion: 0.50
Nodes (4): default, description, type, description

### Community 59 - "Community 59"
Cohesion: 0.50
Nodes (4): description, required, type, Capability

### Community 60 - "Community 60"
Cohesion: 0.50
Nodes (4): default, description, type, description

### Community 62 - "Community 62"
Cohesion: 0.67
Nodes (3): ShellScopeEntryAllowedArg, anyOf, description

### Community 63 - "Community 63"
Cohesion: 0.67
Nodes (3): Value, anyOf, description

### Community 64 - "Community 64"
Cohesion: 0.67
Nodes (3): ShellScopeEntryAllowedArg, anyOf, description

### Community 65 - "Community 65"
Cohesion: 0.67
Nodes (3): Value, anyOf, description

### Community 66 - "Community 66"
Cohesion: 0.67
Nodes (3): .claude/skills/, Skills Management, Community Registry

## Knowledge Gaps
- **208 isolated node(s):** `manifest_version`, `name`, `version`, `description`, `permissions` (+203 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **5 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `write_to_vault()` connect `Community 12` to `Community 0`, `Community 1`, `Community 37`, `Community 9`, `Community 44`, `Community 15`, `Community 20`, `Community 53`, `Community 25`, `Community 28`, `Community 29`?**
  _High betweenness centrality (0.073) - this node is a cross-community bridge._
- **Why does `run_pipeline()` connect `Community 1` to `Community 3`, `Community 5`, `Community 6`, `Community 9`, `Community 43`, `Community 12`, `Community 15`, `Community 18`, `Community 53`, `Community 26`, `Community 28`?**
  _High betweenness centrality (0.072) - this node is a cross-community bridge._
- **Why does `CaptureOutput` connect `Community 11` to `Community 0`, `Community 37`, `Community 43`, `Community 12`, `Community 44`, `Community 15`, `Community 18`, `Community 50`, `Community 20`, `Community 53`, `Community 56`, `Community 25`, `Community 28`?**
  _High betweenness centrality (0.064) - this node is a cross-community bridge._
- **Are the 32 inferred relationships involving `write_to_vault()` (e.g. with `run_pipeline()` and `_run_pipeline_blocking()`) actually correct?**
  _`write_to_vault()` has 32 INFERRED edges - model-reasoned connections that need verification._
- **Are the 36 inferred relationships involving `CaptureOutput` (e.g. with `AsyncOpenAI` and `Instructor`) actually correct?**
  _`CaptureOutput` has 36 INFERRED edges - model-reasoned connections that need verification._
- **Are the 36 inferred relationships involving `EnrichedPayload` (e.g. with `AsyncOpenAI` and `InputPayload`) actually correct?**
  _`EnrichedPayload` has 36 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `Path` (e.g. with `YouTubeConfig` and `CaptureOutput`) actually correct?**
  _`Path` has 2 INFERRED edges - model-reasoned connections that need verification._