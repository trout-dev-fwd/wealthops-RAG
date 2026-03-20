import sqlite3


def create_knowledge_db(db_path):
    """Create the knowledge base schema (calls, chunks, chunks_fts, triggers).

    Idempotent — safe to call multiple times.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS calls (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT NOT NULL,
                slug        TEXT NOT NULL UNIQUE,
                published_at TEXT,
                url         TEXT
            );

            CREATE TABLE IF NOT EXISTS chunks (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                call_id       INTEGER NOT NULL REFERENCES calls(id),
                topic_heading TEXT NOT NULL,
                content       TEXT NOT NULL,
                speakers      TEXT DEFAULT '[]',
                timestamps    TEXT DEFAULT '[]',
                source_url    TEXT
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                topic_heading,
                content,
                content='chunks',
                content_rowid='id',
                tokenize='porter unicode61'
            );

            CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
                INSERT INTO chunks_fts(rowid, topic_heading, content)
                VALUES (new.id, new.topic_heading, new.content);
            END;

            CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
                INSERT INTO chunks_fts(chunks_fts, rowid, topic_heading, content)
                VALUES ('delete', old.id, old.topic_heading, old.content);
            END;

            CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
                INSERT INTO chunks_fts(chunks_fts, rowid, topic_heading, content)
                VALUES ('delete', old.id, old.topic_heading, old.content);
                INSERT INTO chunks_fts(rowid, topic_heading, content)
                VALUES (new.id, new.topic_heading, new.content);
            END;
        """)
        conn.commit()
    finally:
        conn.close()


def create_chat_db(db_path):
    """Create the chat history schema (sessions, messages).

    Idempotent — safe to call multiple times.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                title           TEXT,
                started_at      TEXT NOT NULL,
                last_message_at TEXT
            );

            CREATE TABLE IF NOT EXISTS messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL REFERENCES sessions(id),
                role       TEXT NOT NULL,
                content    TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
        """)
        conn.commit()
    finally:
        conn.close()
