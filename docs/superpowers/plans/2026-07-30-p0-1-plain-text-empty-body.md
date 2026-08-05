# P0-1 — Plain-Text Capture Empty Body Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every plain-text desktop capture currently writes a byte-empty note body when the LLM returns an empty `markdown_content`. Add the same raw-text preservation fallback that audio (`## Transcript`) and large-text (`## Full Original Text`) captures already get, so a plain-text capture never loses the user's raw content, and add the test that would have caught this from day one.

**Architecture:** Mirror the existing `_append_transcript` pattern (private helper, hand-duplicated in `main.py` and `server.py` per this repo's CLAUDE.md hard rule) with a new `_append_original_text` helper that always appends `## Original Text\n\n{enriched.enriched_text}` below the LLM's `markdown_content` when `enriched.input_type == "text"` — unconditionally, not just when the body is empty, matching the "nothing is lost" philosophy the audio/large-text paths already use. Call it at the exact same call site as `_append_transcript`, in both files.

**Tech Stack:** Python, pytest, Pydantic v2 `CaptureOutput` (`models.py`).

## Global Constraints

- `main.py:run_pipeline()` and `server.py:_run_pipeline_blocking()` are hand-duplicated by design and must stay that way — every change here is made in BOTH files by hand (CLAUDE.md hard rule).
- No new dependency, no new config, no new class/abstraction for a single call site.
- Test must assert the actual regression: non-empty input text → non-empty written body. Mocking the LLM to return a real `markdown_content` (as every existing e2e test does) would not exercise this fix — the new test's mock LLM output MUST have `markdown_content=""`.
- Run from `omni_capture/`: `pytest` (desktop's full gate, currently 1119 passed) must stay green; run the target test file directly first.

---

### Task 1: Add `_append_original_text` to `main.py`, mirror to `server.py`, add the regression test

**Files:**
- Modify: `Second Thought/omni_capture/main.py` (add helper near existing `_append_transcript`, call it at the same point `_append_transcript` is called, ~line 445-450)
- Modify: `Second Thought/omni_capture/server.py` (identical helper + call site, ~line 932, next to `_append_transcript` def at line 1007)
- Test: `Second Thought/omni_capture/tests/test_e2e.py` (new test near `test_text_input_writes_vault_file`)

**Interfaces:**
- Consumes: `enriched.input_type` (str, `"text"` for plain-text captures — set in `enrichment_router.py:910`), `enriched.enriched_text` (str, the raw captured text — set verbatim at `enrichment_router.py:911` as `payload.raw`), `output.markdown_content` (str, the LLM's structured-output field, may be empty).
- Produces: `_append_original_text(markdown: str, enriched) -> str` — same signature shape as the existing `_append_transcript(markdown: str, enriched) -> str` in both files. Later tasks (none in this plan) would call it the same way.

- [ ] **Step 1: Write the failing test in `tests/test_e2e.py`**

Add this test directly after `test_text_input_writes_vault_file` (around line 113):

```python
def test_text_input_empty_llm_body_preserves_raw_text(vault: Path):
    """P0-1 regression: an empty markdown_content from the LLM must not lose
    the user's original captured text. main.py must append it as a fallback,
    the same way audio appends '## Transcript' and large-text appends
    '## Full Original Text'."""
    from main import run_pipeline

    fake_out = _fake_capture_output()
    fake_out.markdown_content = ""  # the exact failure mode: LLM returns an empty body

    raw_text = "Python asyncio is awesome for concurrent I/O."
    with _mock_llm(fake_out):
        result = run_pipeline(
            text=raw_text,
            vault_root=str(vault),
            dry_run=False,
            notify=False,
        )

    assert result["_written_to"] is not None
    written = Path(result["_written_to"])
    assert written.exists()
    body = written.read_text()
    assert body.strip() != "", "body must not be byte-empty (P0-1)"
    assert raw_text in body, "raw captured text must be preserved as a fallback"
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `Second Thought/omni_capture/`): `pytest tests/test_e2e.py -k test_text_input_empty_llm_body_preserves_raw_text -v`
Expected: FAIL — `body.strip() != ""` assertion fails (empty file written), proving the bug reproduces under test.

- [ ] **Step 3: Add `_append_original_text` to `main.py` and call it**

In `main.py`, immediately after the existing `_append_transcript` helper definition (around line 443-449), add:

```python
    # mirrored from server.py by design (main.py cannot import server.py --
    # see CLAUDE.md's hand-duplication rule for main.py/server.py).
    def _append_original_text(markdown: str, enriched) -> str:
        """Plain-text captures keep the raw input below the LLM summary --
        the ONE input type that previously had no raw-text fallback, unlike
        audio's '## Transcript' and large-text's '## Full Original Text'."""
        if enriched.input_type != "text":
            return markdown
        return f"{markdown}\n\n## Original Text\n\n{enriched.enriched_text}"
```

Then, immediately after the existing line:
```python
    output.markdown_content = _append_transcript(output.markdown_content, enriched)
```
add:
```python
    output.markdown_content = _append_original_text(output.markdown_content, enriched)
```

- [ ] **Step 4: Mirror the identical change into `server.py`**

In `server.py`, add the same `_append_original_text` function immediately after `_append_transcript`'s definition (around line 1007-1011):

```python
def _append_original_text(markdown: str, enriched) -> str:
    """Plain-text captures keep the raw input below the LLM summary -- the ONE
    input type that previously had no raw-text fallback, unlike audio's
    '## Transcript' and large-text's '## Full Original Text'."""
    if enriched.input_type != "text":
        return markdown
    return f"{markdown}\n\n## Original Text\n\n{enriched.enriched_text}"
```

Then, immediately after the existing line in `_run_pipeline_blocking` (around line 932):
```python
        output.markdown_content = _append_transcript(output.markdown_content, enriched)
```
add:
```python
        output.markdown_content = _append_original_text(output.markdown_content, enriched)
```

- [ ] **Step 5: Run the new test to verify it passes**

Run: `pytest tests/test_e2e.py -k test_text_input_empty_llm_body_preserves_raw_text -v`
Expected: PASS.

- [ ] **Step 6: Add the mirrored assertion for `server.py`'s `_run_pipeline_blocking`**

Add a second test right after the one above (mirrors `test_server_run_pipeline_blocking_does_not_pollute_ollama_base_url_env` at line 591 for the calling pattern):

```python
def test_server_run_pipeline_blocking_empty_llm_body_preserves_raw_text(vault: Path):
    """Same P0-1 regression, exercised through server.py's hand-duplicated
    pipeline (_run_pipeline_blocking), not just main.py's."""
    import asyncio
    import server as srv_mod

    fake_out = _fake_capture_output()
    fake_out.markdown_content = ""
    raw_text = "hello from server pipeline, preserve me"

    q: asyncio.Queue = asyncio.Queue()
    loop = asyncio.new_event_loop()
    srv_mod.cfg.vault.root = str(vault)

    with _mock_llm(fake_out):
        srv_mod._run_pipeline_blocking("text", raw_text, q, loop)

    # drain the SSE queue for the "done" event to find the written path
    written_path = None
    while not q.empty():
        item = q.get_nowait()
        if item is not None and item[0] == "done":
            written_path = item[1].get("path")
    loop.close()

    assert written_path is not None
    body = Path(written_path).read_text()
    assert body.strip() != "", "body must not be byte-empty (P0-1, server path)"
    assert raw_text in body
```

Note for the implementer: read `_run_pipeline_blocking`'s actual `emit()` queue-item shape (`main.py`/`server.py` "SSE `emit()`" convention, CLAUDE.md hard rule) before finalizing this test's draining logic — the sketch above assumes `emit("done", path=...)` puts a `("done", {"path": ...})`-shaped tuple on the queue; adjust the unpacking to match the real `emit()` signature in `server.py` if it differs (e.g. it may be a dict with a `"type"` key rather than a tuple). Do not guess — read `server.py`'s `emit()` definition first.

- [ ] **Step 7: Run it to verify it fails, then passes**

Run: `pytest tests/test_e2e.py -k test_server_run_pipeline_blocking_empty_llm_body_preserves_raw_text -v`
Expected: FAILs before Step 4's server.py change is in place (it already is, from Step 4) — so this should PASS immediately since Step 4 already fixed `server.py`. If it fails, the queue-draining logic in Step 6 is wrong, not the fix — debug the harness, not the product code.

- [ ] **Step 8: Run the full desktop gate**

Run (from `Second Thought/omni_capture/`): `pytest`
Expected: all tests pass, count ≥ 1121 (1119 baseline + 2 new tests). Re-run yourself; do not trust a subagent's reported number.

- [ ] **Step 9: Commit**

```bash
git add omni_capture/main.py omni_capture/server.py omni_capture/tests/test_e2e.py
git commit -m "fix: preserve raw text as a fallback when the LLM returns an empty plain-text body (P0-1)"
```

---

## Acceptance criteria (what "done" means for P0-1)

- [ ] A real hotkey plain-text capture with a real (non-mocked) Ollama call that returns an empty `markdown_content` still writes a non-empty body containing the original clipboard text under an `## Original Text` heading — verified via `pytest tests/test_e2e.py -k empty_llm_body -v` passing in BOTH the `main.py` and `server.py` code paths.
- [ ] `main.py:run_pipeline()` and `server.py:_run_pipeline_blocking()` carry byte-identical new logic (same function body, same call site relative to `_append_transcript`) — grep both files for `_append_original_text` to confirm two definitions, two call sites.
- [ ] Full desktop gate (`pytest` from `omni_capture/`) green, count re-run and read by you, not quoted from a subagent.
- [ ] No change to `enrichment_router.py`, `models.py`, or any dedup/hash logic — the fix is purely a body-assembly fallback, the same shape as the two fallbacks that already exist.
