import sqlite3

STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "in", "on", "at", "to", "for", "of", "with", "by", "from", "as",
    "into", "about", "between", "through", "during", "before", "after",
    "and", "but", "or", "not", "no", "nor", "so", "if", "then",
    "what", "which", "who", "whom", "this", "that", "these", "those",
    "how", "when", "where", "why",
    "can", "could", "should", "would", "will", "shall", "may", "might",
    "do", "does", "did", "have", "has", "had",
    "i", "me", "my", "you", "your", "we", "our", "they", "them", "their",
    "it", "its", "he", "she", "his", "her",
    "tell", "know", "think", "said", "say",
})


def sanitize_fts5_query(query: str) -> str:
    """Quote tokens, filter stop words, and join with OR for broad matching.

    FTS5 treats hyphens as NOT, ``*`` as prefix search, and parentheses /
    AND / OR / NEAR as query operators.  Quoting each token forces literal
    matching — e.g. ``S-Corp`` becomes ``"S-Corp"`` instead of ``S NOT Corp``.

    Stop words are removed so filler doesn't dilute results.  Tokens are
    joined with OR so any matching term returns results; FTS5 rank scoring
    puts chunks matching more terms higher.

    Returns ``""`` (empty quoted string) when all tokens are stop words or
    the query is empty, which produces zero FTS5 matches.
    """
    tokens = query.split()
    if not tokens:
        return '""'
    filtered = [t for t in tokens if t.lower() not in STOP_WORDS]
    if not filtered:
        return '""'
    return " OR ".join(f'"{t.replace(chr(34), chr(34) + chr(34))}"' for t in filtered)


def search_chunks(db_path: str, query: str, limit: int = 8) -> list[dict]:
    """
    Search the FTS5 index for chunks matching the query.
    Returns list of dicts with keys: id, topic_heading, content, speakers,
    call_title, call_date, call_url, timestamps.
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
                    c.timestamps,
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
