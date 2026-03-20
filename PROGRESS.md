# WealthOps RAG Assistant — Phase Progress

## Phase 1: Shared Data Layer ✅
- `shared/schema.py` — knowledge DB + chat DB creation (idempotent)
- `shared/tiptap_parser.py` — Format A (h2/h3) + Format B (bulletList) parsing
- `tests/test_schema.py`, `tests/test_parser.py` — all passing

## Phase 2: Pipeline ✅
- `pipeline/scraper.py` — Circle.so API client with cookie auth + pagination
- `pipeline/db_builder.py` — incremental inserts, FTS5 rebuild
- `pipeline/git_ops.py` — SHA256 checksum + git commit/push
- `pipeline/pipeline.py` — interactive entry point, --dry-run support
- `.github/workflows/release.yml` — auto-release on wealthops.db push
- `tests/test_scraper.py`, `tests/test_db_builder.py`, `tests/test_git_ops.py`

## Phase 3: App Backend ✅
- `app/config.py` — config.json management, path constants, IRC defaults
- `app/updater.py` — GitHub Releases checker + atomic DB download
- `app/retriever.py` — FTS5 search with query sanitization
- `app/llm.py` — Claude API client, build_request, stream_response (yields tuples), caching
- `app/chat_store.py` — sessions + messages CRUD
- `tests/test_config.py`, `tests/test_updater.py`, `tests/test_retriever.py`,
  `tests/test_llm.py`, `tests/test_chat_store.py`

## Phase 4: GUI + IRC + Packaging ✅
- `app/irc_client.py` — HelpChat with TLS, daemon reactor thread, exponential backoff reconnect
- `app/gui.py` — tkinter GUI: chat/history/help views, welcome screen, loading animation,
  streaming with stop button, settings dialog, mid-stream error handling
- `app/main.py` — startup flow: API key validation, DB download, session init
- `app/requirements.txt` — anthropic, irc
- `app/assets/dollar.gif` — loading animation placeholder
- `app/assets/icon.ico` — app icon placeholder
- `build.sh` — PyInstaller one-file build command
- `tests/test_irc_client.py` — 24 IRC client tests (mock-based)
- `tests/test_integration.py` — 21 end-to-end flow tests

### Total tests: 223 passing

## Key Gotchas (carried forward)

### From Phase 3
- FTS5 query sanitization wraps each token in double quotes. Multi-token queries
  require ALL tokens to appear in the chunk (AND semantics). Use short focused
  queries in tests.
- `stream_response` now yields `(text, is_error)` tuples (changed in Phase 4).
  The GUI uses `is_error=True` to render error messages on a separate line with
  distinct styling, rather than concatenating them to the partial response.

### From Phase 4
- `app/gui.py` imports tkinter at the top level. Do not import it in headless
  test environments. The `NO_RESULTS_MSG` constant is defined in gui.py; tests
  that need it should copy the string inline rather than importing from gui.
- IRC `HelpChat.connect()` registers global handlers on the reactor once in
  `__init__`. Do not call `add_global_handler` again after construction or
  handlers will fire multiple times per event.
- The `_animate()` helper in gui.py is a module-level function (not a method)
  so it can be used by both `WealthOpsApp` and `show_download_screen`.
