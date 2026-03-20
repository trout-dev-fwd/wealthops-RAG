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


TOPIC_CATEGORIES = [
    "Tax strategy & deductions",
    "Entity structure (LLCs, S-Corps, holding companies)",
    "Bookkeeping & financial tracking tools",
    "Options trading",
    "Portfolio management & asset allocation",
    "Donor Advised Funds (DAFs) & philanthropy",
    "Real estate investing",
    "Legacy statements & family values",
    "Engaging spouses & children in wealth management",
    "Retirement accounts (401k, Roth, Solo 401k)",
    "Insurance & risk management",
    "Crypto & alternative investments",
    "Program logistics & schedule",
]


def is_discovery_query(query: str) -> bool:
    """Return True if the query is a meta-question about available topics."""
    q = query.lower()
    if "topic" in q:
        return True
    if "what can you" in q or "what do you" in q:
        return True
    return False


def format_topic_list() -> str:
    """Return a formatted list of broad topic categories covered in the recordings."""
    lines = ["Here are the topics covered in the call recordings:\n"]
    for category in TOPIC_CATEGORIES:
        lines.append(f"  - {category}")
    lines.append("")
    lines.append(
        "Ask me about any of these — I'll find the relevant discussions "
        "from your call recordings."
    )
    return "\n".join(lines)


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
