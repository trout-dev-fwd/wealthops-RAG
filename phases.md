# WealthOps RAG Assistant — Phase Breakdown

## Phase Overview

| Phase | Name | Scope | Depends On |
|-------|------|-------|------------|
| 1 | Data foundation | SQLite schema, tiptap parser (both formats), chunk extraction | — |
| 2 | Pipeline script | Scraper, cookie validation, incremental processing, git push, dry-run | Phase 1 |
| 3 | App backend | Config, retriever, LLM client (caching + streaming), chat store, updater | Phase 1 (schema only) |
| 4 | GUI + Integration | tkinter GUI, welcome screen, chat, history, help/IRC, loading, packaging | Phase 3 |

Phases 2 and 3 are independent of each other — they both depend on Phase 1 but not on each other. They can be built in either order.

---

## Phase 1: Data Foundation

**Goal:** Build the shared data layer that both the pipeline and the desktop app depend on.

**Deliverables:**
- `shared/schema.py` — SQLite schema creation functions (knowledge DB + chat history DB)
- `shared/tiptap_parser.py` — Tiptap JSON → chunk extraction for both Format A and Format B
- `shared/__init__.py`
- `tests/test_schema.py` — Schema creation, table existence, FTS5 trigger verification
- `tests/test_parser.py` — Parser tests using real sample data from both formats
- `tests/fixtures/` — Sample tiptap JSON from a Format A post and a Format B post

**Key requirements:**
- Schema creation is idempotent (safe to call multiple times)
- Parser handles both formats and extracts: topic_heading, content, speakers (JSON array), timestamps (JSON array)
- Parser skips: file nodes (video embeds), structural headings ("Discussion Topics", "Key Search Terms"), empty paragraphs
- FTS5 uses `porter unicode61` tokenizer
- All tests pass

**Review gate:** Opus reviews schema design, parser edge cases (what if a listItem has no bold text? what if an h3 has no timestamp prefix?), and test coverage.

---

## Phase 2: Pipeline Script

**Goal:** Build the complete scraper-to-git-push pipeline that the maintainer runs locally.

**Deliverables:**
- `pipeline/pipeline.py` — Main entry point, interactive cookie prompt
- `pipeline/scraper.py` — Circle.so API client with pagination and auth validation
- `pipeline/db_builder.py` — Incremental DB population using shared parser
- `pipeline/git_ops.py` — Checksum generation and git commit/push
- `pipeline/requirements.txt` — (requests)
- `.github/workflows/release.yml` — GitHub Action for creating releases
- `tests/test_scraper.py` — Auth validation, pagination, error handling
- `tests/test_db_builder.py` — Incremental insert logic, additive-only verification
- `tests/test_git_ops.py` — Checksum generation, no-op when no changes

**Key requirements:**
- Cookie validation before scraping starts (detect `{"email": "", "password": null}` response)
- Mid-scrape auth failure aborts cleanly with no DB changes
- Incremental: only processes posts whose slugs aren't already in the DB
- Additive-only: never DELETEs from chunks or calls tables
- No-op when no new posts found (no git operations)
- `--dry-run` flag that scrapes and parses but doesn't save or push
- Git operations: add wealthops.db + checksums.txt, commit with descriptive message, push

**Review gate:** Opus reviews error handling paths (cookie expiration, network failures, partial scrapes), incremental logic correctness, and whether the additive-only constraint is enforced at the right level.

---

## Phase 3: App Backend

**Goal:** Build all non-GUI components of the desktop app as independently testable modules.

**Deliverables:**
- `app/config.py` — Config management (~/.wealthops/config.json), path constants
- `app/updater.py` — GitHub Releases API checker, checksums.txt comparison, DB download with integrity verification
- `app/retriever.py` — FTS5 search with JOIN to calls table, returns structured dicts
- `app/llm.py` — Claude API client with prompt caching, streaming, context management for follow-ups
- `app/chat_store.py` — Session and message CRUD on the separate chats.db
- `app/requirements.txt` — (anthropic, irc)
- `tests/test_config.py` — Config creation, loading, missing key handling
- `tests/test_updater.py` — Checksum comparison, download trigger logic (mock GitHub API)
- `tests/test_retriever.py` — FTS5 search against a pre-populated test DB, zero-results handling
- `tests/test_llm.py` — Request body construction, prompt caching structure, context overlap detection, error mapping
- `tests/test_chat_store.py` — Session creation, message insertion, history retrieval, ordering

**Key requirements:**
- Config: creates ~/.wealthops/ directory if missing, handles missing keys gracefully
- Updater: forces silent update, no user prompt. Handles: no local DB (first launch), outdated DB, matching DB, download failure, no internet
- Retriever: returns empty list (not error) when FTS5 has no matches. Caller decides what to do.
- LLM: system prompt + context block gets `cache_control: {"type": "ephemeral"}`. Follow-up logic: if >50% chunk ID overlap with existing context, keep original context and append new. Streaming via `client.messages.stream()`. Error responses mapped to human-friendly strings with "Travis" as the contact name.
- Chat store: separate SQLite file from knowledge DB. Session title auto-generated from first user message (truncated 60 chars). `last_message_at` updated on each message.
- All modules have zero GUI dependencies — they can be tested headlessly

**Review gate:** Opus reviews prompt caching correctness (is the cache_control in the right position?), the follow-up context overlap logic, error handling completeness, and thread safety of each module.

---

## Phase 4: GUI + Integration

**Goal:** Build the tkinter GUI, integrate all backend modules, add IRC help, package with PyInstaller.

**Deliverables:**
- `app/gui.py` — Main GUI: top bar, chat area, input box, welcome screen, history view, help view
- `app/irc_client.py` — Embedded IRC client with auto-reconnect and mailto: fallback
- `app/main.py` — Entry point: startup flow (config → API key validation → DB update → GUI)
- `app/assets/icon.ico` — App icon
- `app/assets/dollar.gif` — Loading animation
- `app/build.py` or `Makefile` — PyInstaller build command
- `tests/test_irc_client.py` — Connection, send, receive, disconnect, reconnect logic (mock server)
- `tests/test_integration.py` — End-to-end: config → retrieve → LLM request construction (mock API)

**Key requirements:**
- Font: Segoe UI 13px, line-height 1.6+, input box at least 3 lines tall
- Welcome screen fills blank chat area with instructions + clickable example questions
- Loading: dollar.gif + "Searching recordings..." → "Thinking..." → streaming response
- History: full-screen read-only list, grouped by date, click to view past sessions, "← Back" to return
- Help: IRC panel with "Travis may not see your message right away" notice. Connect on click, not on startup. Fallback to mailto: if connection fails.
- Clear Chat: saves current session, creates new session, shows welcome screen
- Settings: accessible via gear icon, only contains API key field + "Check for updates" button
- Threading: GUI on main thread, API streaming on background thread, IRC reactor on background thread, DB update on background thread. All GUI updates via `root.after()`
- Stop button during streaming that sets a cancellation flag
- PyInstaller: `--onefile --windowed`, bundle dollar.gif via `--add-data`, handle `sys._MEIPASS` for asset paths
- First launch flow: API key screen (with validation) → "Downloading database..." → welcome screen

**Review gate:** Opus reviews threading safety (especially tkinter's single-thread requirement), the first-launch flow for edge cases (no internet, invalid key, download failure), and IRC client robustness (reconnection, graceful degradation).
