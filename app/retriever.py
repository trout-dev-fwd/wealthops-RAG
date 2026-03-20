import sqlite3


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
                (query, limit),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()
    except Exception:
        return []
