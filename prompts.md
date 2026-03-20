# WealthOps RAG Assistant — Handoff Prompts

## Phase 1: Data Foundation

### Claude Code Prompt

```
Read SPEC.md, PROGRESS.md, and DESIGN_v2.md before starting.

Build Phase 1: Data Foundation.

Create the shared data layer in `shared/`:

1. `shared/schema.py`:
   - `create_knowledge_db(db_path)` — creates the calls table, chunks table, chunks_fts virtual table (FTS5 with porter unicode61 tokenizer), and the three sync triggers (INSERT, UPDATE, DELETE). Must be idempotent (use IF NOT EXISTS).
   - `create_chat_db(db_path)` — creates the sessions and messages tables with the idx_messages_session index. Must be idempotent.

2. `shared/tiptap_parser.py`:
   - `parse_tiptap_to_chunks(tiptap_body: dict, call_title: str, call_url: str) -> list[dict]`
   - Must handle BOTH Format A (h3 headings + paragraphs, newer posts) and Format B (bulletList + listItems, older posts). See SPEC.md for the full format descriptions.
   - Each chunk dict has keys: topic_heading, content, speakers (list), timestamps (list)
   - Skip file nodes, structural h2s ("Discussion Topics", "Key Search Terms"), empty paragraphs
   - For Format A: strip timestamp prefix from h3 headings (e.g., "01:08 Travel Delays" → "Travel Delays")
   - For Format B: extract bold text as topic heading, concatenate remaining text as content

3. Tests in `tests/`:
   - `tests/fixtures/format_a_sample.json` — a real tiptap_body dict from a Format A post (use the March 17, 2026 example structure from DESIGN_v2.md)
   - `tests/fixtures/format_b_sample.json` — a real tiptap_body dict from a Format B post (use the January 16, 2026 example structure from DESIGN_v2.md)
   - `tests/test_schema.py` — verify both DBs create successfully, tables exist, FTS5 table works, triggers fire on insert/delete
   - `tests/test_parser.py` — verify both formats parse correctly, speakers extracted, timestamps extracted, skip logic works, edge cases handled (no bold text, no timestamp prefix, empty content)

All tests must pass. When complete, update PROGRESS.md to check off Phase 1 items. Commit with message: "Phase 1: Data foundation — schema and tiptap parser"
```

### Opus Review Prompt

```
You are reviewing Phase 1 of the WealthOps RAG Assistant project. Read SPEC.md and DESIGN_v2.md for full context.

Review the following files for correctness, edge cases, and test coverage:
- shared/schema.py
- shared/tiptap_parser.py
- tests/test_schema.py
- tests/test_parser.py
- tests/fixtures/

Check for:
1. Schema: Are the FTS5 triggers correct? Will they actually keep the index in sync? Is the tokenizer configuration right? Is schema creation truly idempotent?
2. Parser Format A: Does it correctly identify h3 boundaries (topic starts at h3, ends at next h3 or h2)? Does the timestamp prefix stripping handle all patterns (e.g., "01:08", "1:01:41")? What happens with h3s that have no timestamp prefix?
3. Parser Format B: Does it correctly extract the first bold text node as the topic heading? What if a listItem has multiple bold sections? What if there's no bold text at all?
4. Speaker extraction: Is it robust? Speakers appear as "(Name):" in Format A and as plain names in Format B content. Are common patterns covered?
5. Skip logic: Does it correctly skip file nodes, structural headings, empty paragraphs? What about paragraphs that only contain bold text with no content?
6. Test coverage: Are both formats tested with realistic data? Are edge cases covered? Are there negative tests (malformed input, empty input)?

Report any bugs, missing edge cases, or improvements needed.
```

---

## Phase 2: Pipeline Script

### Claude Code Prompt

```
Read SPEC.md, PROGRESS.md, and DESIGN_v2.md before starting. Check the Gotchas section of SPEC.md for any findings from Phase 1.

Build Phase 2: Pipeline Script.

Create the pipeline in `pipeline/`:

1. `pipeline/scraper.py`:
   - `validate_cookie(session, base_url, space_id) -> bool` — fetches page 1 with per_page=1, returns True if response has "records" key, False if it looks like a login form ({"email": "", "password": null} pattern)
   - `fetch_all_posts(session, base_url, space_id) -> list[dict]` — paginates through all posts, 15 per page, 1-second delay between pages. If any page returns non-200 or a login form response, raise an exception immediately (do not return partial results)
   - Auth: set the cookie string as a raw "cookie" header on the requests.Session (not via session.cookies.set — that double-encodes URL-encoded values)

2. `pipeline/db_builder.py`:
   - `get_existing_slugs(db_path) -> set[str]` — returns all slugs currently in the calls table
   - `insert_new_posts(db_path, new_posts: list[dict]) -> int` — uses shared.tiptap_parser to parse each post's tiptap_body, inserts into calls + chunks tables. Returns count of new chunks inserted. NEVER deletes existing data.

3. `pipeline/git_ops.py`:
   - `compute_checksum(db_path) -> str` — returns SHA256 hex digest
   - `write_checksums_file(db_path, checksums_path)` — writes "sha256:{hash}  wealthops.db\n" format
   - `git_commit_and_push(message: str)` — runs git add, commit, push via subprocess. If any step fails, print the error and abort (don't continue to push if commit failed).

4. `pipeline/pipeline.py`:
   - Interactive entry point. Prompts for cookie string in a loop until valid.
   - Calls validate_cookie, then fetch_all_posts, then checks for new posts, then inserts, then pushes.
   - Supports `--dry-run` flag (via argparse) that does everything except DB writes and git operations.
   - If no new posts found, prints message and exits without git operations.

5. `.github/workflows/release.yml` — triggers on push to main when wealthops.db changes. Creates a timestamped release with wealthops.db and checksums.txt as assets. Use softprops/action-gh-release@v2.

6. Tests:
   - `tests/test_scraper.py` — mock the requests to test: valid cookie detection, invalid cookie detection, pagination, mid-scrape auth failure
   - `tests/test_db_builder.py` — test: incremental insert (skip existing slugs), additive-only (verify no DELETEs happen), correct chunk counts
   - `tests/test_git_ops.py` — test: checksum computation matches known value, checksums.txt format

All tests must pass. Update PROGRESS.md. Commit with message: "Phase 2: Pipeline script — scraper, builder, git push"
```

### Opus Review Prompt

```
You are reviewing Phase 2 of the WealthOps RAG Assistant project. Read SPEC.md and DESIGN_v2.md for full context.

Review the following files:
- pipeline/pipeline.py
- pipeline/scraper.py
- pipeline/db_builder.py
- pipeline/git_ops.py
- .github/workflows/release.yml
- tests/test_scraper.py
- tests/test_db_builder.py
- tests/test_git_ops.py

Check for:
1. Cookie validation: Does it correctly distinguish between a valid response (has "records") and the login form ({"email":"","password":null})? Is there any other response shape it should handle?
2. Mid-scrape failure: If page 2 of 3 fails auth, does the entire scrape abort cleanly? Are no partial results written to the DB? Is the error message clear?
3. Incremental logic: Is the slug comparison correct? Could there be a race condition if two posts share slugs? (Unlikely but worth checking)
4. Additive-only: Is it structurally impossible for the pipeline to delete data, or is it just "we don't call DELETE"? Could a schema change or recreation accidentally drop data?
5. Dry-run: Does --dry-run actually prevent ALL side effects (no DB writes, no git operations)? Or could it accidentally modify the DB?
6. Git operations: What happens if the git repo has uncommitted changes? What if push fails due to network? Are these handled?
7. GitHub Action: Is the trigger path correct? Will it fire on every push to main that changes wealthops.db? Is the tag format unique enough to avoid collisions?
8. Test quality: Are the mocks realistic? Do they test failure paths, not just happy paths?

Report any bugs, race conditions, or missing error handling.
```

---

## Phase 3: App Backend

### Claude Code Prompt

```
Read SPEC.md, PROGRESS.md, and DESIGN_v2.md before starting. Check the Gotchas section of SPEC.md for findings from Phases 1 and 2.

Build Phase 3: App Backend.

Create the app backend modules in `app/`. CRITICAL: None of these modules may import tkinter or any GUI library. They must all be testable headlessly.

1. `app/config.py`:
   - Constants: CONFIG_DIR (~/.wealthops/), CONFIG_FILE, KNOWLEDGE_DB_PATH, CHATS_DB_PATH, GITHUB_REPO
   - `load_config() -> dict` — reads config.json, creates directory if missing, returns empty dict (not crash) if file missing
   - `save_config(config: dict)` — writes config.json
   - `get_api_key() -> str | None` — convenience wrapper
   - IRC config constants: server (`irc.greed.software`), port (6697), channel (`#wealthops`), nickname, help_email (from config or defaults)

2. `app/updater.py`:
   - `get_latest_release_info(github_repo: str) -> dict | None` — hits GitHub Releases API, returns {checksum: str, db_download_url: str} or None on failure
   - `get_local_checksum(db_path: str) -> str | None` — SHA256 of local file, or None if file doesn't exist
   - `download_db(url: str, dest_path: str, expected_checksum: str) -> bool` — downloads file, verifies SHA256, returns True on success. On checksum mismatch, deletes the downloaded file and returns False.
   - `check_and_update(github_repo: str, db_path: str) -> str` — orchestrator, returns one of: "updated", "up_to_date", "downloaded" (first launch), "failed", "no_internet"

3. `app/retriever.py`:
   - `search_chunks(db_path: str, query: str, limit: int = 8) -> list[dict]` — FTS5 MATCH query with JOIN to calls table. Returns list of dicts with keys: id, topic_heading, content, speakers, call_title, call_date, call_url. Returns empty list (not error) on no matches.

4. `app/llm.py`:
   - `SYSTEM_PROMPT` constant (the conversational system prompt from DESIGN_v2.md)
   - `ERROR_MESSAGES` dict mapping status codes and error types to human-friendly strings
   - `build_request(context_chunks, conversation_history, user_query) -> dict` — builds the full API request body with cache_control on the system+context block
   - `should_replace_context(old_chunk_ids: set, new_chunk_ids: set) -> bool` — returns True if <50% overlap (context should be replaced entirely)
   - `stream_response(api_key, request_body) -> Generator[str, None, None]` — yields text tokens from Claude streaming API. On error, yields the mapped human-friendly error message as a single string.
   - Uses the anthropic Python package with client.messages.stream()

5. `app/chat_store.py`:
   - `init_chat_db(db_path)` — creates tables if needed (uses shared.schema.create_chat_db)
   - `create_session(db_path) -> int` — creates new session, returns session_id
   - `add_message(db_path, session_id, role, content)` — inserts message, updates session.last_message_at, sets session.title from first user message (truncated 60 chars)
   - `get_session_messages(db_path, session_id) -> list[dict]` — returns all messages in order
   - `list_sessions(db_path) -> list[dict]` — returns all sessions sorted by last_message_at desc, with message count

6. Tests:
   - `tests/test_config.py` — config creation in temp dir, loading, missing file handling
   - `tests/test_updater.py` — mock GitHub API responses: normal update, up to date, no internet, checksum mismatch, missing release
   - `tests/test_retriever.py` — create a test DB with known chunks, verify search returns correct results, verify empty results on no match
   - `tests/test_llm.py` — test build_request structure (verify cache_control position), test should_replace_context with various overlap percentages, test error message mapping
   - `tests/test_chat_store.py` — session creation, message insertion, title auto-generation, list ordering, multiple sessions

All tests must pass. All modules must work without any GUI imports. Update PROGRESS.md. Commit with message: "Phase 3: App backend — config, updater, retriever, LLM, chat store"
```

### Opus Review Prompt

```
You are reviewing Phase 3 of the WealthOps RAG Assistant project. Read SPEC.md and DESIGN_v2.md for full context.

Review the following files:
- app/config.py
- app/updater.py
- app/retriever.py
- app/llm.py
- app/chat_store.py
- All tests in tests/

Check for:
1. Config: Is the config directory creation safe on Windows? Does ~ expand correctly? What if the directory exists but config.json is corrupted JSON?
2. Updater: Is the GitHub API response parsing robust? What if the release has no assets? What if checksums.txt has an unexpected format? Is the download-then-verify-then-replace sequence atomic (no partial file left on crash)?
3. Retriever: Is the FTS5 MATCH query safe from SQL injection? (It should be parameterized.) Does the query handle special characters in user input? What if the DB file doesn't exist or is corrupted?
4. LLM: Is the cache_control in the correct position (on the second system content block, not the first)? Does the overlap detection correctly handle edge cases (empty old set, empty new set, identical sets)? Does the streaming generator properly close the stream on error? Does the error mapping cover all realistic error types from the anthropic package?
5. Chat store: Is the session title truncation correct for multi-byte characters? Are all DB operations using parameterized queries? Is there a race condition if two threads try to add messages to the same session simultaneously?
6. Thread safety: Are any of these modules using shared state that could cause issues when called from background threads? (They shouldn't have any global mutable state.)
7. Test quality: Do tests cover failure paths? Are mocks realistic? Is the test DB created fresh for each test (no test pollution)?

Report any bugs, thread safety issues, or missing error handling.
```

---

## Phase 4: GUI + Integration

### Claude Code Prompt

```
Read SPEC.md, PROGRESS.md, and DESIGN_v2.md before starting. Check the Gotchas section of SPEC.md for findings from all previous phases.

Build Phase 4: GUI + Integration.

This phase wires everything together with the tkinter GUI and adds the IRC help client.

1. `app/irc_client.py`:
   - Uses the `irc` Python package (add to requirements.txt)
   - `HelpChat` class with: connect(), send(message), disconnect(), on_message callback
   - Connects to configured IRC server/port/channel with TLS
   - Runs reactor loop in a daemon background thread
   - Auto-reconnect on disconnect with exponential backoff (1s, 2s, 4s, max 30s)
   - If initial connection fails, raise an exception (caller shows mailto: fallback)

2. `app/gui.py`:
   - tkinter GUI. Font: Segoe UI 13px on Windows (fallback to system default on other OS). Line height 1.6+.
   - Top bar: app title on left, Clear Chat / History / Help buttons on right, small gear icon for Settings
   - Chat area (main view): scrollable frame showing message bubbles. User messages right-aligned or labeled "You", assistant messages labeled "Assistant".
   - Welcome screen: shown when current session has no messages. Contains welcome text, 4 clickable example questions (clicking sends immediately), and tips explaining Clear Chat, History, and Help. Welcome screen disappears once first message is sent.
   - Input area: Text widget at least 3 lines tall, Send button. Enter key sends (Shift+Enter for newline). Send button disables during API call. Stop button appears during streaming.
   - Loading animation: dollar.gif (from assets/) displayed in chat area with text "Searching recordings..." then "Thinking..." then disappears when first token arrives. Use asset_path() helper for PyInstaller compatibility.
   - History view: replaces chat area. Shows past sessions grouped by date (Today, Yesterday, Last week, Older). Each session shows title + date + message count. Click opens read-only view. "← Back" returns to active session.
   - Help view: replaces chat area. IRC chat interface. Shows "Travis may not see your message right away" notice. If IRC connection fails, shows "Can't connect to help chat" with clickable "Email Travis instead" (mailto: link). "← Back" returns to active session.
   - Settings: simple dialog/panel with API key field and "Check for updates" button.

3. `app/main.py`:
   - Entry point. Startup flow:
     a. Load config
     b. If no API key → show API key entry screen. Validate with a 1-token Claude API call. Don't proceed until valid key is saved.
     c. Check for DB updates (background thread). If no local DB, show "Downloading database..." with dollar.gif on main screen. Block until download completes or fails.
     d. Initialize chat DB
     e. Show main GUI with welcome screen
   - Wire together: user sends message → retriever.search_chunks → if no results, show "I couldn't find anything" message (no API call) → else build_request → stream_response on background thread → tokens pushed to GUI via root.after() → save messages to chat_store

4. Threading:
   - Main thread: tkinter mainloop
   - Background thread for API streaming: started on each Send, tokens pushed via root.after(0, callback)
   - Background thread for IRC: daemon thread, started when Help is opened
   - Background thread for DB update: on startup only
   - Stop button sets a threading.Event, streaming thread checks it between token yields
   - Send button disabled while streaming, re-enabled when complete or stopped

5. PyInstaller:
   - `app/build.py`: script that runs the pyinstaller command
   - Bundle dollar.gif with --add-data "app/assets/dollar.gif:assets"
   - Use --onefile --windowed --name "WealthOps Assistant" --icon app/assets/icon.ico
   - asset_path() helper in gui.py that checks sys._MEIPASS

6. Tests:
   - `tests/test_irc_client.py` — test connection (mock), message send/receive, disconnect, reconnect logic
   - `tests/test_integration.py` — end-to-end flow: create config → create test DB with known data → search → build request → verify request structure. Mock the API call itself.

All tests must pass. Update PROGRESS.md. Commit with message: "Phase 4: GUI, IRC help, PyInstaller packaging"
```

### Opus Review Prompt

```
You are reviewing Phase 4 of the WealthOps RAG Assistant project. Read SPEC.md and DESIGN_v2.md for full context.

Review the following files:
- app/gui.py
- app/irc_client.py
- app/main.py
- tests/test_irc_client.py
- tests/test_integration.py

Check for:
1. Threading safety: Are ALL tkinter widget modifications happening on the main thread via root.after()? Is there any place where a background thread directly touches a widget? This is the #1 source of crashes in tkinter apps.
2. Streaming cancellation: When the Stop button is pressed, does the streaming thread actually stop? Does it clean up the API connection? Is there a race condition between the stop flag being set and the GUI being updated?
3. First-launch flow: What happens if the API key validation succeeds but the DB download fails? What if both fail? Is every combination handled without leaving the user stuck?
4. IRC client: Is the reconnection backoff correctly implemented? Does disconnect() properly terminate the reactor thread? What happens if send() is called before connect() completes? Is TLS configured correctly?
5. Welcome screen: Do the clickable example questions actually send the message and trigger the full RAG flow? Does the welcome screen properly disappear after the first message?
6. History view: Is the transition between active chat → history → past session → back clean? Does "← Back" correctly restore the active session's state? Is there a memory issue if she has hundreds of past sessions?
7. dollar.gif: Is it properly loaded in both dev mode and PyInstaller mode? Does the animation actually play in tkinter? (tkinter's GIF support requires frame-by-frame animation — verify this is handled.)
8. Input handling: Does Enter send and Shift+Enter add newline? Is the input cleared after sending? Is there protection against sending empty messages?
9. PyInstaller: Will the build actually produce a working .exe? Is the --add-data path correct for Windows? Does asset_path() handle both frozen and unfrozen correctly?

Report any threading bugs, UX issues, or packaging problems.
```

---

## General Follow-up Prompts

### If Tests Fail

```
Tests are failing. Here is the output:

[paste test output]

Fix the failing tests. The fix should address the root cause, not just make the test pass. If the test expectation is wrong (the code is correct but the test is testing the wrong thing), fix the test and explain why. Commit the fix with a descriptive message.
```

### If Opus Review Finds Issues

```
The Opus review found the following issues:

[paste relevant findings]

Address each issue. For each one, either fix it (and explain what you changed) or explain why the current implementation is correct and the review finding doesn't apply. Update tests if the fixes change behavior. Commit each fix separately with a descriptive message.
```

### If Manual Testing Finds a Bug

```
I found a bug during manual testing:

[describe the bug — what you did, what you expected, what actually happened]

Fix this bug. Add a test that reproduces the bug before fixing it (the test should fail first, then pass after the fix). Commit with message: "Fix: [brief description of the bug]"
```
