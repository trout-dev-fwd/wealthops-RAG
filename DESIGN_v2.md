# WealthOps RAG Assistant — Design Document v2

## Overview

Two separate tools that share a SQLite database via GitHub Releases:

1. **Pipeline script** (`pipeline.py`) — runs on the maintainer's machine. Prompts for a Circle.so cookie string, scrapes new call recordings, parses them into chunks, inserts into SQLite with FTS5, then pushes to GitHub where a GH Action creates a release with the DB + checksums.txt.

2. **Desktop app** (`wealthops_assistant/`) — runs on the end user's Windows machine. A simple chat GUI built with Python/tkinter. On startup, silently checks GitHub Releases for DB updates and auto-downloads if needed. User asks questions, app retrieves relevant chunks via FTS5, sends them + the question to Claude API with prompt caching, streams the response. Chat history is stored in a separate local SQLite file.

---

## Component 1: Pipeline Script (`pipeline.py`)

### User Experience

```
$ python pipeline.py
WealthOps Pipeline
==================
Paste your Circle.so cookie string (from DevTools > Network > cookie header):
> [user pastes full cookie string]

Validating cookie...
  ✓ Authenticated as Travis

Scraping Circle.so...
  Page 1: 15 posts
  Page 2: 15 posts
  Page 3: 1 posts
  31 total posts found

Checking for new posts...
  28 already in database, skipping
  3 new posts to process:
    Parsing: March 17, 2026... 8 chunks
    Parsing: March 10, 2026... 12 chunks
    Parsing: March 6, 2026... 6 chunks
  26 new chunks inserted
  FTS5 index rebuilt

Pushing to GitHub...
  DB size: 2.1 MB
  SHA256: a3f2b8c1...
  Committed and pushed to master

Done! GitHub Action will create the release automatically.
```

If no new posts are found:
```
Checking for new posts...
  31 already in database, skipping
  No new recordings found. Nothing to push.
```

### Scraping Logic

- Base URL: `https://community.wealthops.io`
- Listing endpoint: `GET /internal_api/spaces/2310701/posts?page={N}&per_page=15`
- Auth: raw `Cookie` header (full cookie string pasted by user)
- Paginate until `has_next_page` is false
- Each record in `records[]` contains the full `tiptap_body`

### Cookie Validation

Before scraping, validate the cookie by fetching page 1 and checking the response shape:

```python
resp = session.get(f"{BASE_URL}/internal_api/spaces/{SPACE_ID}/posts", params={"page": 1, "per_page": 1})
data = resp.json()

# The login form response looks like: {"email": "", "password": null}
# A valid response has "records" key
if "records" not in data:
    print("Cookie expired or invalid. Please paste a fresh cookie string.")
    # Loop back to cookie input prompt — do NOT proceed to scrape
```

If any subsequent page returns a non-200 status or the login JSON pattern, abort the entire scrape immediately. Print which page failed and that no data was committed.

```python
if resp.status_code != 200 or "records" not in data:
    print(f"Auth failed on page {page}. Cookie may have expired mid-scrape.")
    print("No changes were saved. Please re-run with a fresh cookie.")
    sys.exit(1)
```

### Incremental Processing

Before parsing, query the `calls` table for existing slugs:
```python
existing = {row[0] for row in db.execute("SELECT slug FROM calls")}
new_posts = [p for p in all_posts if p["slug"] not in existing]
```

If `len(new_posts) == 0`, print "No new recordings found. Nothing to push." and exit without any git operations.

### Additive-Only Rule

The pipeline only INSERTs, never DELETEs. If a post disappears from Circle (renamed, moved, deleted), its chunks remain in the database. This means:
- Chunk count is monotonically increasing
- No data loss from source changes
- If chunk count ever decreases, something is wrong (sanity check)

### Tiptap Parsing → Chunks

The tiptap JSON has a predictable structure per the existing call recordings.

**Two content formats exist across the 31 posts:**

**Format A (newer posts, ~March 2026):** Uses h2/h3 headings with paragraphs beneath them.

```
doc
  ├── file (video embed — skip)
  ├── heading (h2) — "Discussion Topics" — structural, skip
  ├── heading (h3) — "01:08 Travel Delays and World Baseball Classic"
  ├── paragraph — "(Christopher Nelson): **Christopher** shares..."
  ├── paragraph — "(Greg Nakagawa): **Greg** describes..."
  ├── paragraph — empty — skip
  ├── heading (h3) — "03:43 Philanthropy and Service Trips"
  ├── paragraph — content...
  ...
  ├── heading (h2) — "Key Search Terms" — structural, skip
  ├── paragraph — search terms — skip
```

Each h3 heading + its following paragraphs (until the next h3 or h2) = one chunk. Strip the timestamp prefix from the h3 for the topic heading.

**Format B (older posts, ~Oct 2025 - Jan 2026):** Uses bulletList with listItems.

```
doc
  ├── file (video embed — skip)
  ├── bulletList
  │   ├── listItem
  │   │   └── paragraph
  │   │       ├── text [bold] — "Topic Heading"
  │   │       ├── text — " Content about the topic..."
  │   │       ├── text [link] — "00:05:34" (timestamp)
  │   │       └── text — " more content..."
  │   ├── listItem (next topic)
  │   ...
```

Each listItem = one chunk. The bold text at the start = topic heading. Everything else = content.

**Chunk extraction rules:**
- Each topic = one chunk
- Extract `topic_heading`: bold text at start (Format B) or h3 text minus timestamp prefix (Format A)
- Extract `content`: full text of the chunk including speaker names and all detail
- Extract `speakers`: JSON array of unique speaker names mentioned in the chunk
- Extract `timestamps`: JSON array of timestamp strings found in the chunk
- Skip nodes of type `file` (video embeds)
- Skip structural headings: "Discussion Topics", "Key Search Terms"
- Skip empty paragraphs and search term lists

### SQLite Schema

```sql
-- Knowledge base — this file gets replaced on updates from GitHub
-- File: wealthops.db

CREATE TABLE calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    published_at TEXT,
    url TEXT
);

CREATE TABLE chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id INTEGER NOT NULL REFERENCES calls(id),
    topic_heading TEXT NOT NULL,
    content TEXT NOT NULL,
    speakers TEXT DEFAULT '[]',      -- JSON array of speaker names
    timestamps TEXT DEFAULT '[]',    -- JSON array of timestamp strings
    source_url TEXT                   -- direct link to the call recording page
);

-- FTS5 virtual table for full-text search
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    topic_heading,
    content,
    content='chunks',
    content_rowid='id',
    tokenize='porter unicode61'
);

-- Triggers to keep FTS5 in sync with chunks table
CREATE TRIGGER chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, topic_heading, content)
    VALUES (new.id, new.topic_heading, new.content);
END;

CREATE TRIGGER chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, topic_heading, content)
    VALUES ('delete', old.id, old.topic_heading, old.content);
END;

CREATE TRIGGER chunks_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, topic_heading, content)
    VALUES ('delete', old.id, old.topic_heading, old.content);
    INSERT INTO chunks_fts(rowid, topic_heading, content)
    VALUES (new.id, new.topic_heading, new.content);
END;
```

### Git Push

After updating the DB:
```python
import subprocess, hashlib

# Check if anything changed
new_count = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
print(f"  Total chunks in DB: {new_count}")

if not new_posts:
    print("No new recordings found. Nothing to push.")
    sys.exit(0)

# Compute SHA256
sha256 = hashlib.sha256(open("wealthops.db", "rb").read()).hexdigest()
with open("checksums.txt", "w") as f:
    f.write(f"sha256:{sha256}  wealthops.db\n")

# Git operations
subprocess.run(["git", "add", "wealthops.db", "checksums.txt"], check=True)
subprocess.run(["git", "commit", "-m", f"Update DB: {len(new_posts)} new recordings"], check=True)
subprocess.run(["git", "push"], check=True)
```

### Dry Run Mode

Support `--dry-run` flag that scrapes and parses but does not commit or push:

```
$ python pipeline.py --dry-run
...
DRY RUN — parsed 3 new posts (26 chunks) but did not save or push.
```

### GitHub Action (`.github/workflows/release.yml`)

Triggers on push to master when wealthops.db changes. Creates a release with the DB and checksums.txt as assets.

```yaml
name: Release DB
on:
  push:
    branches: [master]
    paths: [wealthops.db]

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Get date tag
        id: tag
        run: echo "tag=db-$(date +%Y%m%d-%H%M%S)" >> $GITHUB_OUTPUT

      - name: Create Release
        uses: softprops/action-gh-release@v2
        with:
          tag_name: ${{ steps.tag.outputs.tag }}
          name: "Database Update ${{ steps.tag.outputs.tag }}"
          files: |
            wealthops.db
            checksums.txt
```

---

## Component 2: Desktop App (`wealthops_assistant/`)

### File Structure

```
wealthops_assistant/
├── main.py              # Entry point
├── config.py            # API key management, paths, constants
├── updater.py           # GitHub release checker + downloader
├── retriever.py         # FTS5 search logic
├── llm.py               # Claude API client with prompt caching + streaming
├── chat_store.py        # Local chat history (separate SQLite file)
├── irc_client.py        # Embedded IRC client for Help chat
├── gui.py               # tkinter GUI
└── assets/
    ├── icon.ico         # App icon
    └── dollar.gif       # Loading animation
```

### Configuration (`config.py`)

Config stored at `~/.wealthops/config.json`:
```json
{
    "api_key": "sk-ant-...",
    "github_repo": "username/wealthops-rag",
    "irc_server": "irc.greed.software",
    "irc_port": 6697,
    "irc_channel": "#wealthops",
    "irc_nick": "Barbara",
    "help_email": "trout.dev.fwd@gmail.com"
}
```

File paths (not configurable, hardcoded):
- Knowledge DB: `~/.wealthops/wealthops.db` (replaced on updates)
- Chat history DB: `~/.wealthops/chats.db` (permanent, local only)
- Config: `~/.wealthops/config.json`

### Startup Flow

```
1. Load config from ~/.wealthops/config.json
2. If no API key → show API key entry screen
   - Validate key with minimal API call (1 token) before proceeding
   - If invalid, show: "That key doesn't seem to work. Double-check 
     it and try again, or ask Travis for help."
   - If valid, save to config and continue
3. Check for DB updates (silent, non-blocking):
   - Fetch checksums.txt from latest GitHub Release
   - Compare SHA256 with local wealthops.db
   - If no local DB exists → show "Downloading database..." with progress
   - If local DB exists but outdated → download new DB silently in background
   - If download fails → use existing local DB, no error shown
   - If no local DB AND download fails → show error: 
     "Couldn't download the database. Check your internet and restart,
     or ask Travis for help."
4. Show main chat interface with welcome screen
```

### First Launch / API Key Screen

A simple centered screen. This blocks all other functionality until a valid key is saved.

```
┌─────────────────────────────────────────┐
│                                         │
│   Welcome to WealthOps Assistant        │
│                                         │
│   To get started, please enter your     │
│   Claude API key below.                 │
│                                         │
│   ┌───────────────────────────────┐     │
│   │ sk-ant-...                    │     │
│   └───────────────────────────────┘     │
│                                         │
│              [ Save & Continue ]         │
│                                         │
└─────────────────────────────────────────┘
```

**API key validation:** On save, make a minimal Claude API call (e.g., a 1 max_token request with "Hi"). If it returns 200, the key is valid. If 401/403, show a friendly error. This prevents her from getting into the chat and then hitting a confusing error on her first question.

### Update Checker (`updater.py`)

Runs on startup, **forces updates silently** — no prompt, no decision for the user.

1. Fetch latest release from GitHub API:
   `GET https://api.github.com/repos/{owner}/{repo}/releases/latest`
   (unauthenticated — 60 requests/hour, more than enough)
2. Find the `checksums.txt` asset in the release → download → parse SHA256
3. Compute SHA256 of local `~/.wealthops/wealthops.db`
4. If no local DB exists:
   - Show "Downloading call recording database..." with dollar.gif animation
   - Download `wealthops.db` asset from the release
   - Verify SHA256 matches checksums.txt
   - Save to `~/.wealthops/wealthops.db`
5. If checksums differ:
   - Download new DB silently in background
   - Verify checksum
   - Replace local copy
   - No user notification needed
6. If checksums match: do nothing
7. If download fails: use existing local DB if available; show error only if no local DB exists

### Retrieval (`retriever.py`)

```python
import sqlite3

def search_chunks(db_path: str, query: str, limit: int = 8) -> list[dict]:
    """
    Search the FTS5 index for chunks matching the query.
    Returns list of dicts with: topic_heading, content, speakers,
    call_title, call_date, call_url
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    results = conn.execute("""
        SELECT
            c.topic_heading,
            c.content,
            c.speakers,
            calls.title AS call_title,
            calls.published_at AS call_date,
            calls.url AS call_url
        FROM chunks_fts
        JOIN chunks c ON chunks_fts.rowid = c.id
        JOIN calls ON c.call_id = calls.id
        WHERE chunks_fts MATCH ?
        ORDER BY rank
        LIMIT ?
    """, (query, limit)).fetchall()
    conn.close()
    return [dict(row) for row in results]
```

**When FTS5 returns no results:**

Do NOT call the Claude API. Instead, show this message directly in the chat (no API cost):

> "I couldn't find anything about that in the call recordings. Try rephrasing your question or using different words."

This prevents wasting tokens on empty context and avoids hallucinated answers.

### Claude API Client (`llm.py`)

**Model:** `claude-sonnet-4-20250514`

**System prompt:**
```
You are a helpful assistant for a member of the WealthOps micro family
office program. You answer questions based on the call recording 
summaries provided below as context.

Rules:
- Only answer based on what's in the provided context
- If the context doesn't fully answer the question, say what you can 
  and be honest about what isn't covered
- Always mention which call recording(s) your answer comes from, 
  like "Christopher talked about this in the January 16th call"
- Be conversational and clear — explain things the way you would 
  to a friend over dinner
- If multiple calls cover the same topic, bring them together into 
  one clear answer
- Avoid jargon unless the source material uses it, and explain it 
  when you do
```

**RAG prompt construction with prompt caching:**

```python
def build_request(system_prompt: str, context_chunks: list[dict],
                  conversation_history: list[dict], user_query: str) -> dict:
    """
    Build the API request body with prompt caching.
    
    The system prompt + context block gets cache_control marker.
    On first question: cache WRITE (~25% surcharge on input)
    On follow-ups within 5 min: cache READ (~90% cheaper)
    """

    # Build context block from retrieved chunks
    context_parts = []
    for chunk in context_chunks:
        context_parts.append(
            f"### {chunk['topic_heading']}\n"
            f"**Source:** {chunk['call_title']} ({chunk['call_date']})\n"
            f"**Speakers:** {chunk['speakers']}\n\n"
            f"{chunk['content']}\n"
        )
    context_block = "\n---\n".join(context_parts)

    # System message with cache_control on the context block
    system = [
        {
            "type": "text",
            "text": system_prompt
        },
        {
            "type": "text",
            "text": f"## Relevant call recording excerpts:\n\n{context_block}",
            "cache_control": {"type": "ephemeral"}
        }
    ]

    # Conversation history + new message
    messages = []
    for msg in conversation_history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_query})

    return {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 2048,
        "system": system,
        "messages": messages,
        "stream": True
    }
```

**Prompt caching strategy for follow-up questions:**

When a follow-up question comes in within the same session:
1. Run FTS5 search with the new question
2. Compare new chunk IDs with the chunks already in the context
3. If >50% overlap: keep the original context (preserves cache), append only genuinely new chunks
4. If <50% overlap: replace context entirely (cache miss, but the topic changed significantly)

This maximizes cache hits for natural follow-up conversations while still providing fresh context when the topic shifts.

**Streaming:** Use Claude API streaming so tokens appear in the GUI as they're generated:

```python
import anthropic

client = anthropic.Anthropic(api_key=api_key)

with client.messages.stream(**request_body) as stream:
    for text in stream.text_stream:
        yield text  # GUI appends each token to the response area
```

**Error handling — human-friendly messages:**

| API error | User sees |
|-----------|-----------|
| 401 / 403 (auth) | "Your API key doesn't seem to be working. Go to Settings to update it, or ask Travis for help." |
| 429 (rate limit) | "You're sending questions too quickly. Wait a minute and try again." |
| 500+ (server error) | "Something went wrong on Claude's end. Try again in a moment." |
| Connection error | "Can't reach the internet. Check your WiFi and try again." |
| Timeout | "That's taking too long. Try again with a shorter question." |

Use the maintainer's actual name ("Travis") in error messages so she knows who to contact.

### Chat History Storage (`chat_store.py`)

**CRITICAL: This is a SEPARATE SQLite file from the knowledge DB.**

The knowledge DB (`wealthops.db`) gets replaced on updates from GitHub.
Chat history (`chats.db`) is permanent and local-only, never overwritten.

File: `~/.wealthops/chats.db`

```sql
CREATE TABLE sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,                -- auto-generated from first user message (first ~60 chars)
    started_at TEXT NOT NULL,  -- ISO 8601
    last_message_at TEXT       -- updated on each new message
);

CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,        -- 'user' or 'assistant'
    content TEXT NOT NULL,
    created_at TEXT NOT NULL   -- ISO 8601
);

CREATE INDEX idx_messages_session ON messages(session_id);
```

**Session behavior:**
- App opens → new session created automatically
- "Clear Chat" button → saves current session, creates a new session, clears the chat area
- Session title = first user message, truncated to ~60 characters
- `last_message_at` updated on every new message (for sorting in History view)

### Embedded IRC Client (`irc_client.py`)

Uses the `irc` Python package (pure Python, PyInstaller-compatible).

```python
import irc.client
import threading

class HelpChat:
    def __init__(self, server, port, channel, nickname, on_message_callback):
        """
        server: IRC server hostname
        port: IRC server port (6697 for TLS)
        channel: channel to join (e.g., "#wealthops-help")
        nickname: user's nick (e.g., "Barbara")
        on_message_callback: function called with (sender, message) 
                             when a message is received
        """
        self.reactor = irc.client.Reactor()
        self.connection = None
        self.channel = channel
        self.nickname = nickname
        self.on_message = on_message_callback
        self.server = server
        self.port = port

    def connect(self):
        """Connect to IRC server in a background thread."""
        server = self.reactor.server()
        server.connect(self.server, self.port, self.nickname)
        server.add_global_handler("welcome", self._on_connect)
        server.add_global_handler("pubmsg", self._on_pubmsg)
        server.add_global_handler("privmsg", self._on_privmsg)
        self.connection = server
        
        # Run the reactor loop in a background thread
        self.thread = threading.Thread(target=self.reactor.process_forever, daemon=True)
        self.thread.start()

    def _on_connect(self, connection, event):
        connection.join(self.channel)

    def _on_pubmsg(self, connection, event):
        sender = event.source.nick
        message = event.arguments[0]
        self.on_message(sender, message)

    def _on_privmsg(self, connection, event):
        sender = event.source.nick
        message = event.arguments[0]
        self.on_message(sender, message)

    def send(self, message):
        """Send a message to the help channel."""
        if self.connection:
            self.connection.privmsg(self.channel, message)

    def disconnect(self):
        """Clean shutdown."""
        if self.connection:
            self.connection.disconnect("Goodbye")
```

**IRC connection behavior:**
- Connect only when user clicks "Help" (not on app startup — saves resources)
- Auto-reconnect on disconnect with exponential backoff
- If connection fails, show: "Can't connect to help chat right now. Email Travis at trout.dev.fwd@gmail.com instead." with a clickable mailto: link as fallback
- Messages persist in the Help panel for the current app session (not saved to chat history DB)

### GUI Design (`gui.py`)

Using tkinter. Base font: Segoe UI 13px (native Windows font, clean rendering). Line height 1.6+ on all text. Input box at least 3 lines tall.

**Top bar:**
```
┌─────────────────────────────────────────────────────────┐
│  WealthOps Assistant      [Clear Chat] [History] [Help] │
```

Three buttons, always visible. Settings (API key) accessible via a small gear icon or from a right-click menu on the top bar — not a primary button since she'll rarely need it.

**Main chat area — Welcome screen (shown on fresh/cleared sessions):**

When there are no messages in the current session, the chat area shows:

```
┌──────────────────────────────────────────────────────────┐
│                                                          │
│                                                          │
│   Welcome! Ask me anything about your WealthOps          │
│   call recordings. Here are some ideas:                  │
│                                                          │
│   ┌────────────────────────────────────────────────┐     │
│   │ What tax strategies have been discussed?       │     │
│   └────────────────────────────────────────────────┘     │
│   ┌────────────────────────────────────────────────┐     │
│   │ How should I set up bookkeeping?               │     │
│   └────────────────────────────────────────────────┘     │
│   ┌────────────────────────────────────────────────┐     │
│   │ What did Christopher say about options trading? │     │
│   └────────────────────────────────────────────────┘     │
│                                                          │
│   Tips:                                                  │
│   • Ask follow-up questions — I'll remember our chat     │
│   • Click 'Clear Chat' to start on a new topic           │
│   • Click 'History' to see your past conversations       │
│   • Click 'Help' to message Travis directly              │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

Example questions are **clickable** — clicking one fills the input box and sends it immediately, giving an instant success experience on first use. The welcome screen disappears once the first message is sent.

**Main chat area — Active conversation:**

```
┌──────────────────────────────────────────────────────────┐
│                                                          │
│  ┌─ You ───────────────────────────────────────────────┐ │
│  │ What tax strategies have been discussed?             │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌─ Assistant ─────────────────────────────────────────┐ │
│  │ Several tax strategies have come up across the      │ │
│  │ calls. In the January 16th call, Christopher        │ │
│  │ walked through the deduction stack for the          │ │
│  │ management company — things like phone, computer,   │ │
│  │ and tax service expenses...                         │ │
│  │                                                     │ │
│  │ Source: January 16, 2026 Call Recording              │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
├──────────────────────────────────────────────────────────┤
│ ┌────────────────────────────────────────────┐  [Send]  │
│ │ Ask about the call recordings...           │          │
│ │                                            │          │
│ │                                            │          │
│ └────────────────────────────────────────────┘          │
└──────────────────────────────────────────────────────────┘
```

**Loading state:**

When user hits Send:
1. Input box and Send button become disabled
2. A "Stop" button appears (replaces Send) to cancel streaming
3. The dollar.gif animation appears in the chat area with text underneath:
   - "Searching call recordings..." (during FTS5 search)
   - "Thinking..." (during Claude API wait, before first token)
4. Once first token arrives, dollar.gif disappears and response streams in token-by-token
5. When response is complete, input box and Send button re-enable

**dollar.gif bundling:** The gif needs to be included via PyInstaller's `--add-data` flag. At runtime, access it relative to the bundle path using `sys._MEIPASS` if frozen, or `__file__` if running from source.

**History view:**

Clicking "History" replaces the chat area with a scrollable list of past sessions:

```
┌──────────────────────────────────────────────────────────┐
│  WealthOps Assistant                      [← Back]       │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  Today                                                   │
│  ┌────────────────────────────────────────────────────┐  │
│  │ What tax strategies have been discussed?           │  │
│  │ Mar 19, 2026 · 4 messages                         │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  Yesterday                                               │
│  ┌────────────────────────────────────────────────────┐  │
│  │ How should I set up bookkeeping for the holding... │  │
│  │ Mar 18, 2026 · 6 messages                         │  │
│  └────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────┐  │
│  │ What did Christopher say about DAF strategies?     │  │
│  │ Mar 18, 2026 · 2 messages                         │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  Last week                                               │
│  ┌────────────────────────────────────────────────────┐  │
│  │ What tools were recommended for tracking invest... │  │
│  │ Mar 14, 2026 · 8 messages                         │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

Clicking a session opens it **read-only** — messages are displayed but the input box shows "This is a past conversation" (disabled). The "← Back" button returns to the current active session. Sessions are grouped by date and sorted by `last_message_at` descending.

**Help view:**

Clicking "Help" replaces the chat area with the IRC-backed help chat:

```
┌──────────────────────────────────────────────────────────┐
│  Help — Chat with Travis                  [← Back]       │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  Travis may not see your message right away.             │
│  He'll respond when he's available.                      │
│                                                          │
│  ┌─ You ───────────────────────────────────────────────┐ │
│  │ Hey Travis, I'm confused about the S-Corp stuff    │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌─ Travis ────────────────────────────────────────────┐ │
│  │ Hey! Yeah that's in the January 16 call. The key   │ │
│  │ thing is you only need the S-Corp for levels 5-6   │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
├──────────────────────────────────────────────────────────┤
│ ┌────────────────────────────────────────────┐  [Send]  │
│ │ Type a message to Travis...                │          │
│ └────────────────────────────────────────────┘          │
└──────────────────────────────────────────────────────────┘
```

- IRC connection is established when Help is clicked (not on app startup)
- If IRC connection fails, show: "Can't connect to help chat right now." 
  with a clickable "Email Travis instead" link (mailto:)
- Messages from the current Help session persist in the panel while the app is open
- Help messages are NOT saved to the chat history DB
- "← Back" returns to the active chat session

### Threading Model

- **Main thread:** tkinter GUI (required by tkinter)
- **Background thread 1:** Claude API streaming (one at a time)
- **Background thread 2:** IRC reactor loop (only when Help is active)
- **Background thread 3:** DB update check/download (on startup only)
- Use `root.after()` to safely push updates from background threads to GUI
- Send button disabled while waiting for API response
- Stop button appears during streaming to cancel (sets a flag that the streaming thread checks)

### Packaging with PyInstaller

```bash
pip install pyinstaller
pyinstaller --onefile --windowed \
    --name "WealthOps Assistant" \
    --icon assets/icon.ico \
    --add-data "assets/dollar.gif:assets" \
    main.py
```

Produces a single `WealthOps Assistant.exe`. No Python needed on her machine.

First launch creates `~/.wealthops/` directory and downloads the DB from GitHub.

---

## Two-Database Architecture

**This separation is critical and must not be violated.**

| | Knowledge DB | Chat History DB |
|---|---|---|
| **File** | `~/.wealthops/wealthops.db` | `~/.wealthops/chats.db` |
| **Source** | Downloaded from GitHub Releases | Created locally on first launch |
| **Updated by** | Replaced wholesale on update | Appended to on every message |
| **Contains** | calls, chunks, chunks_fts | sessions, messages |
| **Deletable?** | Yes — re-downloads on next launch | No — permanent user data |

---

## Data Flow Summary

### Maintainer workflow (you, ~2 minutes)

```
1. Open Circle.so in browser, copy cookie string
2. Run: python pipeline.py
3. Paste cookie string when prompted
4. Script validates cookie, scrapes only new posts, updates DB, pushes to GitHub
5. If no new posts: script exits, nothing pushed
6. GH Action creates release with DB + checksums.txt
7. Next time she opens the app, DB updates silently
```

### End user workflow (mother-in-law)

```
First time:
1. Double-click WealthOps Assistant.exe
2. Enter API key (Travis pre-configures this for her)
3. App downloads database automatically
4. Welcome screen with example questions appears
5. Click a question or type her own

Every time after:
1. Double-click WealthOps Assistant.exe
2. DB updates silently in background if needed
3. Welcome screen appears (new session)
4. Ask questions, ask follow-ups
5. Click Clear Chat to change topics
6. Click History to review past conversations
7. Click Help if stuck — chats with Travis via IRC
```

---

## Cost Estimates

- ~300-400 chunks across 31 recordings
- Each query retrieves ~8 chunks ≈ 2-3k tokens of context
- System prompt ≈ 200 tokens
- Average response ≈ 500 tokens
- With prompt caching in a session:
  - First question: ~$0.01
  - Follow-up questions: ~$0.002 each
- Typical session (1 topic + 3 follow-ups): ~$0.016
- Estimated monthly cost for active daily use: $2-5
- Claude API has usage limits configurable at console.anthropic.com

---

## Dependencies

### Pipeline script
- `requests` — HTTP client for Circle.so API
- `sqlite3` — standard library
- `hashlib` — standard library
- `subprocess` — standard library (for git)
- `argparse` — standard library (for --dry-run)

### Desktop app
- `anthropic` — Claude API client with streaming support
- `irc` — IRC protocol client (pure Python)
- `tkinter` — standard library GUI
- `sqlite3` — standard library
- `hashlib` — standard library
- `urllib.request` — standard library (for GitHub API)
- `threading` — standard library
- `pyinstaller` — build tool only, not a runtime dependency

---

## Future Enhancements (not for v1)

- Vector embeddings via sqlite-vec for semantic search
- Topic classification and browseable topic index
- Auto-summarization across calls per topic
- Notifications when new recordings are available
- Search history / suggested questions based on past queries
