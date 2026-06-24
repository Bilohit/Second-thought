# SKILLS.md

Reference list of skills available to Claude Code in this environment. Invoke any of these with `/<name>` (or via the Skill tool).

## General-purpose

- **accesslint** — Set up and run automated accessibility and compliance linting for the codebase.
- **animotion** — Set up a motion library and animation patterns for smooth UI transitions and interactions.
- **graphify** — Turn any input (code, docs, papers, images, videos) into a persistent knowledge graph with god nodes, community detection, and query/path/explain tools. Use for any question about a codebase's architecture or file relationships, especially when `graphify-out/` already exists.
- **uiux-pro-max** — Design intelligence review: visual hierarchy, micro-interactions, accessibility, and modern aesthetic standards.

## Review & verification

- **code-review** — Review the current diff for correctness bugs and reuse/simplification/efficiency cleanups, at a chosen effort level (`low`/`medium`/`high`/`max`/`ultra`). `ultra` runs a deep multi-agent review in the cloud. Supports `--comment` (post inline PR comments) and `--fix` (apply findings to the working tree).
- **simplify** — Review changed code for reuse, simplification, efficiency, and "altitude" cleanups, then apply the fixes directly. Quality-only; does not hunt for bugs (use `code-review` for that).
- **review** — Review a GitHub pull request. For reviewing your own working diff, use `code-review` instead.
- **security-review** — Complete a security review of the pending changes on the current branch.
- **verify** — Launch and drive the app to confirm a change actually works in practice (not just via tests). Use when asked to verify a PR, confirm a fix, or validate local changes before pushing.
- **run** — Launch and drive this project's app to see a change working end-to-end. Looks for a project-specific launch skill first, then falls back to built-in patterns (CLI, server, TUI, Electron, browser-driven, library).

## Claude / Anthropic / LLM reference

- **claude-api** — Reference for the Claude API / Anthropic SDK: model IDs, pricing, parameters, streaming, tool use, MCP, agents, caching, token counting, model migration. Trigger whenever Claude/Anthropic/model names are mentioned, or the task is LLM-shaped with no provider stated. Skip if another provider (OpenAI, Gemini, Llama, etc.) is already in use for that code path.

## Environment / config

- **update-config** — Configure the Claude Code harness via `settings.json`: hooks for automated behaviors ("whenever X, do Y"), permissions, environment variables, hook troubleshooting. For simple settings like theme/model, suggest `/config` instead.
- **keybindings-help** — Customize keyboard shortcuts, rebind keys, add chord bindings, or modify `~/.claude/keybindings.json`.
- **fewer-permission-prompts** — Scan transcripts for common read-only Bash/MCP tool calls and add a prioritized allowlist to `.claude/settings.json` to cut down on permission prompts.
- **init** — Initialize a new `CLAUDE.md` file with generated codebase documentation.

## Scheduling / automation

- **loop** — Run a prompt or slash command on a recurring interval (e.g. `/loop 5m /foo`); omit the interval to let the model self-pace. Use for recurring checks/polling, not one-off tasks.
- **schedule** — Create, update, list, or run scheduled cloud agents (cron-based routines), including one-time scheduled runs.

---

This file is hand-maintained — regenerate it by asking Claude to refresh it against the current skill list when new skills are added or removed.
