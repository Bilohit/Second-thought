# Graph Report - .  (2026-06-17)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 899 nodes · 1623 edges · 62 communities (58 shown, 4 thin omitted)
- Extraction: 83% EXTRACTED · 17% INFERRED · 0% AMBIGUOUS · INFERRED: 272 edges (avg confidence: 0.72)
- Token cost: 0 input · 0 output

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
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]

## God Nodes (most connected - your core abstractions)
1. `write_to_vault()` - 48 edges
2. `CaptureOutput` - 30 edges
3. `pre_resolve()` - 29 edges
4. `EnrichedPayload` - 28 edges
5. `TempVault` - 27 edges
6. `_vault()` - 24 edges
7. `_ep()` - 22 edges
8. `run_pipeline()` - 21 edges
9. `_make()` - 20 edges
10. `InputPayload` - 18 edges

## Surprising Connections (you probably didn't know these)
- `Second Thought Logo Icon` --references--> `Second Thought GUI Index`  [INFERRED]
  gui/src-tauri/icons/icon.png → gui/index.html
- `log_capture()` --calls--> `get_config()`  [INFERRED]
  omni_capture/capture_log.py → omni_capture/config.py
- `log_capture()` --calls--> `log_capture_db()`  [INFERRED]
  omni_capture/capture_log.py → omni_capture/index_writer.py
- `CaptureOutput` --uses--> `CaptureOutput`  [INFERRED]
  omni_capture/capture_log.py → omni_capture/models.py
- `CaptureOutput` --uses--> `EnrichedPayload`  [INFERRED]
  omni_capture/capture_log.py → omni_capture/models.py

## Import Cycles
- None detected.

## Communities (62 total, 4 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.06
Nodes (30): build_link_index(), inject_wikilinks(), _parse_aliases(), _protect(), Path, link_resolver.py ---------------- Vault-aware wikilink injector for Second Thoug, Return a mapping of ``{display_name: vault_relative_stem}`` for every     .md fi, Insert ``[[wikilinks]]`` into *content* where known note names appear.      Para (+22 more)

### Community 1 - "Community 1"
Cohesion: 0.06
Nodes (52): log_capture(), CaptureOutput, EnrichedPayload, Dual-write: append to captures.jsonl AND upsert into captures.db.     Fails sile, CaptureConfig, Config, load_config(), LogConfig (+44 more)

### Community 2 - "Community 2"
Cohesion: 0.11
Nodes (29): _file_hash(), get_db_path(), init_db(), log_capture_db(), migrate_jsonl(), Connection, Path, index_writer.py --------------- SQLite index for every Second Thought note.  Dat (+21 more)

### Community 3 - "Community 3"
Cohesion: 0.11
Nodes (21): NamedTuple, EnrichedPayload, _ep(), pre_resolve(), EnrichedPayload, Path, pre_resolver.py --------------- Cheap deterministic resolver for the Second Thou, John Smith' → 'john-smith (+13 more)

### Community 4 - "Community 4"
Cohesion: 0.11
Nodes (32): _append_general(), build_category_descriptions(), check_duplicate(), _content_hash(), _dedup_index_path(), discard_scratchpad_item(), discover_categories(), _find_scratchpad_item() (+24 more)

### Community 5 - "Community 5"
Cohesion: 0.13
Nodes (16): CaptureOutput, Base capture output schema.      Use build_capture_model(categories) to obtain a, Write/append a CaptureOutput to the vault.      Routing     -------     1. Dedup, write_to_vault(), _make(), CaptureOutput, Path, test_dedup_and_inbox.py ----------------------- Pytest suite covering:    1. Con (+8 more)

### Community 6 - "Community 6"
Cohesion: 0.12
Nodes (32): Path, _fake_capture_output(), _mock_llm(), tests/test_e2e.py ----------------- End-to-end test suite for Project Second Tho, A URL is enriched (web extract mocked) then written to the vault., A GitHub repo URL is enriched via the public API (mocked)., A clipboard image is base64-decoded, sent to LLaVA (_enrich_image mocked),     a, An audio file path is passed via --audio; _enrich_audio (Whisper) is mocked (+24 more)

### Community 7 - "Community 7"
Cohesion: 0.07
Nodes (28): dependencies, react, react-dom, @tauri-apps/api, @tauri-apps/plugin-clipboard-manager, @tauri-apps/plugin-dialog, @tauri-apps/plugin-global-shortcut, @tauri-apps/plugin-shell (+20 more)

### Community 8 - "Community 8"
Cohesion: 0.10
Nodes (24): Instructor, Namespace, ClipboardEmpty, ClipboardError, interceptor.py -------------- Step 1 — Trigger & Ingest  Reads the system clipbo, Read the current clipboard and return a typed InputPayload.      Priority order:, Raised when the clipboard cannot be accessed (backend/platform error)., Raised when the clipboard contains no usable text or image. (+16 more)

### Community 9 - "Community 9"
Cohesion: 0.10
Nodes (17): BTN_GHOST, CategoryCardProps, INPUT_STYLE, ModalState, Props, CaptureEvent, createVaultCategory(), deleteVaultCategory() (+9 more)

### Community 10 - "Community 10"
Cohesion: 0.13
Nodes (22): Second Thought — Dashboard, Omni-Capture Dependencies, capture_stats(), CategoryDescriptionPatch, create_category(), delete_category(), _get_vault_root(), list_categories() (+14 more)

### Community 11 - "Community 11"
Cohesion: 0.11
Nodes (11): _make(), test_routing_and_merge.py ------------------------- Tests for the file-routing b, Genuine re-capture into the same decided category still dedups., Two gaming-mice captures with different filenames but strong shared         tags, No shared tags -> never merge, even in the same category., A single shared tag is not enough confidence on its own., The reported bug: two unrelated captures sharing a source URL were         treat, The reported bug: a capture decided as CRM was silently short-circuited (+3 more)

### Community 12 - "Community 12"
Cohesion: 0.13
Nodes (14): Props, Props, BLANK_STATE, CaptureState, CaptureStep, ContentPreview, INITIAL_STEPS, STEP_DEFS (+6 more)

### Community 13 - "Community 13"
Cohesion: 0.08
Nodes (23): app, security, trayIcon, windows, build, beforeBuildCommand, beforeDevCommand, devUrl (+15 more)

### Community 14 - "Community 14"
Cohesion: 0.14
Nodes (21): InputPayload, Match, _enrich_audio(), _enrich_github_url(), _enrich_image(), _enrich_web_url(), _enrich_youtube_url(), _extract_code_blocks_from_transcript() (+13 more)

### Community 15 - "Community 15"
Cohesion: 0.25
Nodes (6): _entry(), Path, test_search_endpoint.py ----------------------- Integration tests for the /searc, Each test creates an isolated temporary vault, seeds the DB,     then monkeypatc, TestSearchEndpoint, TestStatsEndpoint

### Community 16 - "Community 16"
Cohesion: 0.19
Nodes (9): approve_scratchpad_item(), _extract_frontmatter_field(), list_scratchpad(), Return metadata for all notes in the scratchpad folder., Move a scratchpad note to its final category directory.     Strips status: needs, Remove status: needs_review and note_id from frontmatter., _rewrite_frontmatter_for_approval(), _unique_file_path collision avoidance is exercised by approve_scratchpad_item (+1 more)

### Community 17 - "Community 17"
Cohesion: 0.11
Nodes (18): action, default_icon, default_popup, background, service_worker, 128, 16, 48 (+10 more)

### Community 18 - "Community 18"
Cohesion: 0.16
Nodes (17): App, AppHandle, Arc, Child, Mutex, Option, PathBuf, R (+9 more)

### Community 19 - "Community 19"
Cohesion: 0.11
Nodes (17): compilerOptions, allowImportingTsExtensions, isolatedModules, jsx, lib, module, moduleResolution, noEmit (+9 more)

### Community 20 - "Community 20"
Cohesion: 0.26
Nodes (14): date, build_digest(), _format_date_iso(), _format_date_label(), main(), _obsidian_link(), Path, daily_digest.py --------------- Generates a daily journal entry summarising toda (+6 more)

### Community 21 - "Community 21"
Cohesion: 0.13
Nodes (15): definitions, Identifier, Number, PermissionEntry, ShellScopeEntryAllowedArg, Target, oneOf, anyOf (+7 more)

### Community 22 - "Community 22"
Cohesion: 0.19
Nodes (12): BaseModel, InputPayload, Raw, unprocessed input from the clipboard., capture(), CaptureRequest, CategoryCreate, CategoryRename, ConfigPatch (+4 more)

### Community 23 - "Community 23"
Cohesion: 0.18
Nodes (11): properties, description, type, default, description, type, identifier, local (+3 more)

### Community 24 - "Community 24"
Cohesion: 0.17
Nodes (9): Second Thought GUI Index, Second Thought Logo Icon, useCapture(), getVaultCategories(), App(), Theme, THEME_LABELS, THEMES (+1 more)

### Community 25 - "Community 25"
Cohesion: 0.13
Nodes (15): definitions, Identifier, Number, PermissionEntry, Target, Value, oneOf, anyOf (+7 more)

### Community 26 - "Community 26"
Cohesion: 0.23
Nodes (8): BTN_SECONDARY, HotkeyRecorder(), INPUT_STYLE, Props, Config, getConfig(), patchConfig(), formatHotkey()

### Community 27 - "Community 27"
Cohesion: 0.24
Nodes (11): _build_frontmatter(), _category_str(), find_merge_target(), CaptureOutput, Return category as a plain string (handles str-Enum members safely)., Build YAML frontmatter with a flat schema shared across all categories.      Fie, Locate an existing note in the capture's category that this content     should b, read_existing_context() (+3 more)

### Community 28 - "Community 28"
Cohesion: 0.18
Nodes (11): properties, description, type, default, description, type, identifier, local (+3 more)

### Community 29 - "Community 29"
Cohesion: 0.20
Nodes (10): $ref, description, items, type, uniqueItems, description, items, type (+2 more)

### Community 30 - "Community 30"
Cohesion: 0.20
Nodes (10): type, webviews, windows, items, description, items, type, description (+2 more)

### Community 31 - "Community 31"
Cohesion: 0.20
Nodes (10): $ref, description, items, type, uniqueItems, description, items, type (+2 more)

### Community 32 - "Community 32"
Cohesion: 0.20
Nodes (10): type, webviews, windows, items, description, items, type, description (+2 more)

### Community 33 - "Community 33"
Cohesion: 0.32
Nodes (7): buildCommands(), Command, CommandPalette(), filterCommands(), PaletteAction, Props, STATIC_COMMANDS

### Community 34 - "Community 34"
Cohesion: 0.25
Nodes (8): get_config(), approve_inbox(), discard_inbox(), InboxApprove, list_inbox_items(), List all notes pending review in the scratchpad folder., Move a scratchpad note to its final category., Permanently delete a scratchpad note.

### Community 35 - "Community 35"
Cohesion: 0.25
Nodes (8): description, properties, required, type, CapabilityRemote, urls, description, type

### Community 36 - "Community 36"
Cohesion: 0.25
Nodes (8): description, properties, required, type, CapabilityRemote, urls, description, type

### Community 37 - "Community 37"
Cohesion: 0.29
Nodes (7): _is_duplicate_request(), Return True and log if this request was already accepted recently., Browser-extension / OS share-target endpoint.      Accepts a URL + optional sele, _request_hash(), share(), _sse(), _stream_capture()

### Community 39 - "Community 39"
Cohesion: 0.33
Nodes (5): description, identifier, permissions, $schema, windows

### Community 40 - "Community 40"
Cohesion: 0.47
Nodes (5): print_recent(), print_stats(), capture_log.py -------------- Dual-write audit trail for every Second Thought ru, Return the last n log entries, newest first., read_log()

### Community 41 - "Community 41"
Cohesion: 0.40
Nodes (4): anyOf, description, $schema, title

### Community 42 - "Community 42"
Cohesion: 0.40
Nodes (4): anyOf, description, $schema, title

### Community 43 - "Community 43"
Cohesion: 0.50
Nodes (4): default, description, type, description

### Community 44 - "Community 44"
Cohesion: 0.50
Nodes (4): description, required, type, Capability

### Community 45 - "Community 45"
Cohesion: 0.50
Nodes (4): default, description, type, description

### Community 48 - "Community 48"
Cohesion: 0.67
Nodes (3): ShellScopeEntryAllowedArg, anyOf, description

### Community 49 - "Community 49"
Cohesion: 0.67
Nodes (3): ShellScopeEntryAllowedArgs, anyOf, description

### Community 50 - "Community 50"
Cohesion: 0.50
Nodes (4): description, required, type, Capability

### Community 51 - "Community 51"
Cohesion: 0.67
Nodes (3): Value, anyOf, description

### Community 52 - "Community 52"
Cohesion: 0.67
Nodes (3): ShellScopeEntryAllowedArgs, anyOf, description

## Knowledge Gaps
- **209 isolated node(s):** `manifest_version`, `name`, `version`, `description`, `permissions` (+204 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **4 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `log_capture()` connect `Community 1` to `Community 40`, `Community 34`, `Community 2`?**
  _High betweenness centrality (0.097) - this node is a cross-community bridge._
- **Why does `log_capture_db()` connect `Community 2` to `Community 1`, `Community 15`?**
  _High betweenness centrality (0.088) - this node is a cross-community bridge._
- **Why does `write_to_vault()` connect `Community 5` to `Community 0`, `Community 1`, `Community 4`, `Community 11`, `Community 16`, `Community 27`?**
  _High betweenness centrality (0.083) - this node is a cross-community bridge._
- **Are the 32 inferred relationships involving `write_to_vault()` (e.g. with `run_pipeline()` and `_run_pipeline_blocking()`) actually correct?**
  _`write_to_vault()` has 32 INFERRED edges - model-reasoned connections that need verification._
- **Are the 26 inferred relationships involving `CaptureOutput` (e.g. with `Instructor` and `CaptureOutput`) actually correct?**
  _`CaptureOutput` has 26 INFERRED edges - model-reasoned connections that need verification._
- **Are the 23 inferred relationships involving `pre_resolve()` (e.g. with `run_pipeline()` and `_run_pipeline_blocking()`) actually correct?**
  _`pre_resolve()` has 23 INFERRED edges - model-reasoned connections that need verification._
- **Are the 26 inferred relationships involving `EnrichedPayload` (e.g. with `InputPayload` and `Instructor`) actually correct?**
  _`EnrichedPayload` has 26 INFERRED edges - model-reasoned connections that need verification._