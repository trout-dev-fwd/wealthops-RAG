"""Incremental DB population for WealthOps knowledge base."""

import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.schema import create_knowledge_db
from shared.tiptap_parser import parse_tiptap_to_chunks


def get_existing_slugs(db_path: str) -> set:
    """Return all slugs currently in the calls table.

    Returns an empty set if the file doesn't exist or the table isn't created yet.
    """
    if not os.path.exists(db_path):
        return set()

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT slug FROM calls").fetchall()
        return {row[0] for row in rows}
    except sqlite3.OperationalError:
        return set()
    finally:
        conn.close()


def insert_new_posts(db_path: str, new_posts: list) -> int:
    """Parse and insert new posts into the knowledge DB.

    Each post's tiptap_body is parsed into chunks and both calls + chunks rows
    are inserted.  Existing data is never deleted — this is additive-only.

    Returns the total number of new chunks inserted.
    """
    create_knowledge_db(db_path)

    total_chunks = 0
    conn = sqlite3.connect(db_path)
    try:
        for post in new_posts:
            title = post.get("name") or post.get("title") or "Untitled"
            slug = post["slug"]
            published_at = post.get("published_at")
            post_url = post.get("url", "")
            tiptap_body = post.get("tiptap_body") or {}

            cur = conn.execute(
                "INSERT INTO calls (title, slug, published_at, url) VALUES (?, ?, ?, ?)",
                (title, slug, published_at, post_url),
            )
            call_id = cur.lastrowid

            chunks = parse_tiptap_to_chunks(tiptap_body, title, post_url)
            for chunk in chunks:
                conn.execute(
                    """INSERT INTO chunks
                           (call_id, topic_heading, content, speakers, timestamps, source_url)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        call_id,
                        chunk["topic_heading"],
                        chunk["content"],
                        json.dumps(chunk["speakers"]),
                        json.dumps(chunk["timestamps"]),
                        post_url,
                    ),
                )
                total_chunks += 1

        conn.commit()
    finally:
        conn.close()

    return total_chunks
