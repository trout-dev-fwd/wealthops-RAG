import sqlite3


def sanitize_fts5_query(query: str) -> str:
    """Wrap each whitespace-separated token in double quotes to prevent
    FTS5 operator interpretation.

    FTS5 treats hyphens as NOT, ``*`` as prefix search, and parentheses /
    AND / OR / NEAR as query operators.  Quoting each token forces literal
    matching — e.g. ``S-Corp`` becomes ``"S-Corp"`` instead of ``S NOT Corp``.

    Internal double quotes are escaped by doubling them per FTS5 rules.
    """
    tokens = query.split()
    if not tokens:
        return '""'
    return " ".join(f'"{t.replace(chr(34), chr(34) + chr(34))}"' for t in tokens)


def is_discovery_query(query: str) -> bool:
    """Return True if the query is a meta-question about available topics."""
    q = query.lower()
    if "topic" in q:
        return True
    if "what can you" in q or "what do you" in q:
        return True
    return False


def get_all_topics(db_path: str) -> list[dict]:
    """Return all unique topic headings grouped by call, sorted by date descending.

    Each dict has keys: topic_heading, call_title, published_at.
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT DISTINCT c.topic_heading, calls.title AS call_title,
                       calls.published_at
                FROM chunks c
                JOIN calls ON c.call_id = calls.id
                ORDER BY calls.published_at DESC, c.topic_heading
                """
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()
    except Exception:
        return []


def format_topic_list(topics: list[dict]) -> str:
    """Format get_all_topics output as a readable grouped list."""
    if not topics:
        return "No topics found in the database."

    from datetime import datetime

    grouped: dict[str, list[str]] = {}
    order: list[str] = []
    for t in topics:
        raw = t["published_at"] or ""
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            label = dt.strftime("%B %-d, %Y")
        except (ValueError, AttributeError):
            label = t["call_title"]
        if label not in grouped:
            grouped[label] = []
            order.append(label)
        grouped[label].append(t["topic_heading"])

    lines = ["Here are the topics covered in the call recordings:\n"]
    for label in order:
        lines.append(f"{label}:")
        for heading in grouped[label]:
            lines.append(f"  - {heading}")
        lines.append("")

    return "\n".join(lines).rstrip()


def search_chunks(db_path: str, query: str, limit: int = 8) -> list[dict]:
    """
    Search the FTS5 index for chunks matching the query.
    Returns list of dicts with keys: id, topic_heading, content, speakers,
    call_title, call_date, call_url.
    Returns empty list on no matches (never raises on search failure).
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            sanitized = sanitize_fts5_query(query)
            rows = conn.execute(
                """
                SELECT
                    c.id,
                    c.topic_heading,
                    c.content,
                    c.speakers,
                    calls.title  AS call_title,
                    calls.published_at AS call_date,
                    calls.url    AS call_url
                FROM chunks_fts
                JOIN chunks c ON chunks_fts.rowid = c.id
                JOIN calls  ON c.call_id = calls.id
                WHERE chunks_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (sanitized, limit),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()
    except Exception:
        return []
