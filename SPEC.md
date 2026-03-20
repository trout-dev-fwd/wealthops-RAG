# WealthOps RAG Assistant — Development Spec

## Architecture Rules

1. **Data is separate from business logic, which is separate from the GUI.**
   - `shared/` — data layer (schema, parser). No I/O, no network, no GUI.
   - `pipeline/` — business logic for scraping and DB building. No GUI.
   - `app/` backend modules (`config.py`, `updater.py`, `retriever.py`, `llm.py`, `chat_store.py`) — business logic for the desktop app. No GUI imports. Every module must be testable headlessly.
   - `app/gui.py` — GUI only. Calls backend modules but contains no business logic itself.
   - `app/main.py` — orchestration and startup flow. Wires backend to GUI.

2. **Every phase needs accompanying tests that pass before completion.**

3. **Each phase is committed to the GH repo with a descriptive commit message.**

4. **Each bugfix or feature enhancement gets its own commit with relevant details.**

5. **Two separate SQLite databases. This is non-negotiable.**
   - `wealthops.db` — knowledge base (calls, chunks, chunks_fts). Gets replaced wholesale from GitHub Releases.
   - `chats.db` — chat history (sessions, messages). Permanent, local-only, never overwritten by updates.
   - These two files must never be conflated, merged, or cross-referenced at the schema level.

6. **The pipeline is additive-only.** It INSERTs new records but never DELETEs existing ones. If a post disappears from Circle.so, its chunks remain in the DB.

7. **All network operations must handle failure gracefully.** No unhandled exceptions for network errors, timeouts, or auth failures. Every failure path has a human-readable message.

## Project Structure

```
wealthops-rag/
├── shared/
│   ├── __init__.py
│   ├── schema.py           # DB creation functions
│   └── tiptap_parser.py    # Tiptap JSON → chunks
├── pipeline/
│   ├── pipeline.py         # Entry point (interactive)
│   ├── scraper.py          # Circle.so API client
│   ├── db_builder.py       # Incremental DB population
│   ├── git_ops.py          # Checksum + git operations
│   └── requirements.txt    # requests
├── app/
│   ├── main.py             # Entry point + startup flow
│   ├── config.py           # Config management
│   ├── updater.py          # GitHub release checker
│   ├── retriever.py        # FTS5 search
│   ├── llm.py              # Claude API client
│   ├── chat_store.py       # Chat history DB
│   ├── irc_client.py       # IRC help client
│   ├── gui.py              # tkinter GUI
│   ├── requirements.txt    # anthropic, irc
│   └── assets/
│       ├── icon.ico
│       └── dollar.gif
├── tests/
│   ├── fixtures/           # Sample tiptap JSON, test DBs
│   ├── test_schema.py
│   ├── test_parser.py
│   ├── test_scraper.py
│   ├── test_db_builder.py
│   ├── test_git_ops.py
│   ├── test_config.py
│   ├── test_updater.py
│   ├── test_retriever.py
│   ├── test_llm.py
│   ├── test_chat_store.py
│   ├── test_irc_client.py
│   └── test_integration.py
├── .github/
│   └── workflows/
│       └── release.yml
├── DESIGN_v2.md            # Full design document
├── SPEC.md                 # This file
├── PROGRESS.md             # Phase progress tracker
└── README.md
```

## Key Technical Decisions

### Tiptap Parser — Two Formats

The 31 existing posts use two different tiptap structures. The parser MUST handle both.

**Format A (newer, ~March 2026):**
- `doc` → `heading` (h2, structural) → `heading` (h3, topic with timestamp prefix) → `paragraph` (content with speaker names)
- Topic heading: h3 text with timestamp prefix stripped. E.g., "01:08 Travel Delays" → "Travel Delays"
- Content: all paragraphs following the h3 until the next h3 or h2
- Speakers: extracted from "(Speaker Name):" pattern at the start of paragraphs

**Format B (older, ~Oct 2025 - Jan 2026):**
- `doc` → `bulletList` → `listItem` → `paragraph` with mixed inline nodes
- Topic heading: first bold text node in the paragraph
- Content: all text nodes concatenated (excluding timestamp links for cleaner text)
- Speakers: names found in the text, typically before or after bold markers

**Edge cases to handle:**
- listItem with no bold text → use first 60 chars of content as topic heading
- h3 with no timestamp prefix → use full h3 text as topic heading
- Empty paragraphs → skip
- Paragraphs that only contain links (search terms) → skip
- `file` nodes → always skip (these are video embeds)
- Structural h2 headings ("Discussion Topics", "Key Search Terms") → skip
- Multiple bulletLists in one document → process all of them
- Nested content in paragraph nodes → flatten to plain text

### FTS5 Configuration

```sql
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    topic_heading,
    content,
    content='chunks',
    content_rowid='id',
    tokenize='porter unicode61'
);
```

- `porter` tokenizer handles stemming ("investing" matches "investment")
- `unicode61` handles unicode normalization
- `content='chunks'` creates a content table reference (content-sync)
- Triggers keep FTS5 in sync on INSERT/UPDATE/DELETE

### Prompt Caching Structure

The Claude API request must place `cache_control` on the system message content block that contains the retrieved context:

```python
system = [
    {"type": "text", "text": system_prompt},
    {"type": "text", "text": context_block, "cache_control": {"type": "ephemeral"}}
]
```

This caches the system prompt + context for 5 minutes. Follow-up questions in the same session reuse the cache if the context doesn't change significantly.

**Follow-up overlap logic:** When a new question comes in during a session:
1. Run FTS5 search with the new query
2. Get the set of chunk IDs from the new search
3. Compare with the chunk IDs already in the current context
4. If >50% of new chunk IDs are already in the context → keep existing context, append only new chunks
5. If ≤50% overlap → replace context entirely (topic changed)

### Error Message Mapping

All user-facing error messages must be non-technical and include "Travis" as the support contact. The error mapping lives in `app/llm.py`:

```python
ERROR_MESSAGES = {
    401: "Your API key doesn't seem to be working. Go to Settings to update it, or ask Travis for help.",
    403: "Your API key doesn't seem to be working. Go to Settings to update it, or ask Travis for help.",
    429: "You're sending questions too quickly. Wait a minute and try again.",
    500: "Something went wrong on Claude's end. Try again in a moment.",
    502: "Something went wrong on Claude's end. Try again in a moment.",
    503: "Something went wrong on Claude's end. Try again in a moment.",
    "connection": "Can't reach the internet. Check your WiFi and try again.",
    "timeout": "That's taking too long. Try again with a shorter question.",
}
```

### GUI Threading

tkinter is single-threaded. All GUI updates MUST happen on the main thread.

- **Background threads** for: Claude API streaming, IRC reactor, DB update download
- **Use `root.after()`** to safely push updates from background threads to GUI
- **Never access tkinter widgets from background threads** — always schedule via `root.after()`
- **Streaming pattern:** background thread yields tokens → calls `root.after(0, append_token, token)` for each one
- **Stop button:** sets a threading.Event that the streaming thread checks between tokens

### PyInstaller Asset Handling

The dollar.gif and icon.ico must be accessible at runtime:

```python
import sys, os

def asset_path(relative_path):
    """Get path to bundled asset, works for dev and PyInstaller."""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(__file__), relative_path)
```

Build command:
```bash
pyinstaller --onefile --windowed \
    --name "WealthOps Assistant" \
    --icon app/assets/icon.ico \
    --add-data "app/assets/dollar.gif:assets" \
    app/main.py
```

### GitHub Releases API

The updater uses unauthenticated GitHub API (60 requests/hour limit):

```
GET https://api.github.com/repos/{owner}/{repo}/releases/latest
```

Response includes `assets` array. Find the asset with name `checksums.txt`, download its `browser_download_url`, parse the SHA256. Then find `wealthops.db` asset and download if needed.

**No authentication required for public repos.** If the repo is private, you'd need a token — but keeping it public is simpler and the data isn't sensitive (it's summaries of group calls).

## Gotchas and Lessons Learned

_(This section is updated as phases are completed. Findings from earlier phases that affect later phases go here.)_

### From Phase 1
_(To be filled after Phase 1 review)_

### From Phase 2
_(To be filled after Phase 2 review)_

### From Phase 3
_(To be filled after Phase 3 review)_
