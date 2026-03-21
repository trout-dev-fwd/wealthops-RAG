import sqlite3
from datetime import datetime, timezone

from shared.schema import create_chat_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_chat_db(db_path: str) -> None:
    """Create chat DB tables if they don't exist yet."""
    create_chat_db(db_path)


def create_session(db_path: str) -> int:
    """Create a new session and return its session_id."""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO sessions (started_at) VALUES (?)",
            (_now(),),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def add_message(
    db_path: str,
    session_id: int,
    role: str,
    content: str,
    sources: str | None = None,
) -> None:
    """
    Insert a message, update session.last_message_at.
    If this is the first user message, set the session title (truncated to 60 chars).
    *sources* is an optional JSON string of source references for assistant messages.
    """
    now = _now()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO messages (session_id, role, content, sources, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, role, content, sources, now),
        )
        conn.execute(
            "UPDATE sessions SET last_message_at = ? WHERE id = ?",
            (now, session_id),
        )
        # Set title from first user message if not yet set
        if role == "user":
            row = conn.execute(
                "SELECT title FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row and row[0] is None:
                title = content[:60]
                conn.execute(
                    "UPDATE sessions SET title = ? WHERE id = ?",
                    (title, session_id),
                )
        conn.commit()
    finally:
        conn.close()


def get_session_messages(db_path: str, session_id: int) -> list[dict]:
    """Return all messages for a session in insertion order."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, session_id, role, content, sources, created_at "
            "FROM messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def list_sessions(db_path: str) -> list[dict]:
    """
    Return all sessions sorted by last_message_at descending, with message count.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT
                s.id,
                s.title,
                s.started_at,
                s.last_message_at,
                COUNT(m.id) AS message_count
            FROM sessions s
            LEFT JOIN messages m ON m.session_id = s.id
            GROUP BY s.id
            ORDER BY s.last_message_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
