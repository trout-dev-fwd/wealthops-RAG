# WealthOps RAG Assistant — Progress Tracker

## Phase 1: Data Foundation
- [x] `shared/schema.py` — knowledge DB schema (calls, chunks, chunks_fts, triggers)
- [x] `shared/schema.py` — chat history DB schema (sessions, messages)
- [x] `shared/schema.py` — idempotent creation (safe to call multiple times)
- [x] `shared/tiptap_parser.py` — Format A parser (h2/h3 headings + paragraphs)
- [x] `shared/tiptap_parser.py` — Format B parser (bulletList + listItems)
- [x] `shared/tiptap_parser.py` — topic_heading extraction (bold text / h3 minus timestamp prefix)
- [x] `shared/tiptap_parser.py` — speakers extraction (JSON array)
- [x] `shared/tiptap_parser.py` — timestamps extraction (JSON array)
- [x] `shared/tiptap_parser.py` — skip logic (file nodes, structural headings, empty paragraphs)
- [x] `tests/fixtures/` — sample tiptap JSON for both formats
- [x] `tests/test_schema.py` — all tests pass
- [x] `tests/test_parser.py` — all tests pass
- [x] Git commit: "Phase 1: Data foundation — schema and tiptap parser"
- [ ] **Opus review passed**

## Phase 2: Pipeline Script
- [x] `pipeline/pipeline.py` — interactive cookie prompt with validation loop
- [x] `pipeline/scraper.py` — pagination logic
- [x] `pipeline/scraper.py` — cookie validation before scraping (detect login form response)
- [x] `pipeline/scraper.py` — mid-scrape auth failure detection and abort
- [x] `pipeline/db_builder.py` — incremental processing (skip existing slugs)
- [x] `pipeline/db_builder.py` — additive-only constraint (never DELETE)
- [x] `pipeline/db_builder.py` — no-op when no new posts (no git operations)
- [x] `pipeline/pipeline.py` — `--dry-run` flag support
- [x] `pipeline/git_ops.py` — SHA256 checksum generation for checksums.txt
- [x] `pipeline/git_ops.py` — git add, commit (descriptive message), push
- [x] `.github/workflows/release.yml` — GH Action triggers on wealthops.db change
- [x] `tests/test_scraper.py` — all tests pass
- [x] `tests/test_db_builder.py` — all tests pass
- [x] `tests/test_git_ops.py` — all tests pass
- [x] Git commit: "Phase 2: Pipeline script — scraper, builder, git push"
- [ ] **Opus review passed**

## Phase 3: App Backend
- [x] `app/config.py` — config creation, loading, directory management
- [x] `app/config.py` — missing key handling (returns None, doesn't crash)
- [x] `app/updater.py` — GitHub Releases API fetching (latest release)
- [x] `app/updater.py` — checksums.txt parsing and comparison
- [x] `app/updater.py` — DB download with SHA256 verification
- [x] `app/updater.py` — handles: no local DB, outdated DB, matching DB, download failure, no internet
- [x] `app/retriever.py` — FTS5 search with JOIN to calls table
- [x] `app/retriever.py` — returns empty list on no matches (not error)
- [x] `app/llm.py` — request body construction with prompt caching (cache_control on system+context)
- [x] `app/llm.py` — follow-up context management (>50% overlap detection)
- [x] `app/llm.py` — streaming via client.messages.stream()
- [x] `app/llm.py` — error mapping to human-friendly messages (mentioning "Travis")
- [x] `app/chat_store.py` — session CRUD (create, list, get messages)
- [x] `app/chat_store.py` — message insertion with timestamp
- [x] `app/chat_store.py` — session title from first user message (truncated 60 chars)
- [x] `app/chat_store.py` — last_message_at updated on each message
- [x] All modules have zero GUI dependencies
- [x] `tests/test_config.py` — all tests pass
- [x] `tests/test_updater.py` — all tests pass
- [x] `tests/test_retriever.py` — all tests pass
- [x] `tests/test_llm.py` — all tests pass
- [x] `tests/test_chat_store.py` — all tests pass
- [x] Git commit: "Phase 3: App backend — config, updater, retriever, LLM, chat store"
- [ ] **Opus review passed**

## Phase 4: GUI + Integration
- [ ] `app/gui.py` — top bar with Clear Chat, History, Help buttons
- [ ] `app/gui.py` — welcome screen with instructions + clickable example questions
- [ ] `app/gui.py` — chat area with user/assistant message bubbles
- [ ] `app/gui.py` — input box (3+ lines, Segoe UI 13px)
- [ ] `app/gui.py` — loading state (dollar.gif + status text → streaming)
- [ ] `app/gui.py` — Stop button during streaming
- [ ] `app/gui.py` — History view (full-screen, read-only, grouped by date, ← Back)
- [ ] `app/gui.py` — Settings (gear icon, API key field)
- [ ] `app/irc_client.py` — IRC connection, send, receive
- [ ] `app/irc_client.py` — auto-reconnect with backoff
- [ ] `app/irc_client.py` — mailto: fallback on connection failure
- [ ] `app/gui.py` — Help view (IRC chat panel with "← Back")
- [ ] `app/main.py` — startup flow: config → API key validation → DB update → GUI
- [ ] `app/main.py` — first launch: API key screen → DB download → welcome screen
- [ ] Threading: API on background thread, IRC on background thread, GUI updates via root.after()
- [ ] dollar.gif bundled via PyInstaller --add-data, sys._MEIPASS handling
- [ ] PyInstaller build produces single .exe
- [ ] `tests/test_irc_client.py` — all tests pass
- [ ] `tests/test_integration.py` — all tests pass
- [ ] Git commit: "Phase 4: GUI, IRC help, PyInstaller packaging"
- [ ] **Opus review passed**
