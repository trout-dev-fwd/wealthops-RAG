"""Tests for shared/schema.py — knowledge DB and chat DB creation."""

import os
import sqlite3
import tempfile

import pytest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.schema import create_knowledge_db, create_chat_db


@pytest.fixture
def tmp_db(tmp_path):
    return str(tmp_path / "test.db")


# ---------------------------------------------------------------------------
# Knowledge DB
# ---------------------------------------------------------------------------

class TestCreateKnowledgeDb:
    def test_creates_calls_table(self, tmp_db):
        create_knowledge_db(tmp_db)
        conn = sqlite3.connect(tmp_db)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        conn.close()
        assert "calls" in tables

    def test_creates_chunks_table(self, tmp_db):
        create_knowledge_db(tmp_db)
        conn = sqlite3.connect(tmp_db)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        conn.close()
        assert "chunks" in tables

    def test_creates_chunks_fts_table(self, tmp_db):
        create_knowledge_db(tmp_db)
        conn = sqlite3.connect(tmp_db)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        conn.close()
        assert "chunks_fts" in tables

    def test_creates_triggers(self, tmp_db):
        create_knowledge_db(tmp_db)
        conn = sqlite3.connect(tmp_db)
        triggers = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        )}
        conn.close()
        assert "chunks_ai" in triggers
        assert "chunks_ad" in triggers
        assert "chunks_au" in triggers

    def test_idempotent(self, tmp_db):
        """Calling create_knowledge_db twice must not raise."""
        create_knowledge_db(tmp_db)
        create_knowledge_db(tmp_db)  # should not raise

    def test_calls_columns(self, tmp_db):
        create_knowledge_db(tmp_db)
        conn = sqlite3.connect(tmp_db)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(calls)")}
        conn.close()
        assert {"id", "title", "slug", "published_at", "url"} <= cols

    def test_chunks_columns(self, tmp_db):
        create_knowledge_db(tmp_db)
        conn = sqlite3.connect(tmp_db)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(chunks)")}
        conn.close()
        assert {"id", "call_id", "topic_heading", "content",
                "speakers", "timestamps", "source_url"} <= cols

    def test_fts5_search(self, tmp_db):
        """FTS5 virtual table must accept queries and return results."""
        create_knowledge_db(tmp_db)
        conn = sqlite3.connect(tmp_db)

        conn.execute(
            "INSERT INTO calls (title, slug) VALUES (?, ?)",
            ("Test Call", "test-call"),
        )
        call_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO chunks (call_id, topic_heading, content) VALUES (?, ?, ?)",
            (call_id, "Tax Strategies", "Discussion about S-Corp deductions"),
        )
        conn.commit()

        results = conn.execute(
            "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ?",
            ("deduction",),
        ).fetchall()
        conn.close()

        assert len(results) == 1

    def test_insert_trigger_populates_fts(self, tmp_db):
        """INSERT trigger must add the chunk to chunks_fts."""
        create_knowledge_db(tmp_db)
        conn = sqlite3.connect(tmp_db)

        conn.execute(
            "INSERT INTO calls (title, slug) VALUES (?, ?)",
            ("Call A", "call-a"),
        )
        call_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO chunks (call_id, topic_heading, content) VALUES (?, ?, ?)",
            (call_id, "Philanthropy", "Donor Advised Fund strategies"),
        )
        conn.commit()

        rows = conn.execute(
            "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH 'philanthropy'",
        ).fetchall()
        conn.close()
        assert len(rows) == 1

    def test_delete_trigger_removes_from_fts(self, tmp_db):
        """DELETE trigger must remove the chunk from chunks_fts."""
        create_knowledge_db(tmp_db)
        conn = sqlite3.connect(tmp_db)

        conn.execute(
            "INSERT INTO calls (title, slug) VALUES (?, ?)",
            ("Call B", "call-b"),
        )
        call_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO chunks (call_id, topic_heading, content) VALUES (?, ?, ?)",
            (call_id, "Bookkeeping", "Unique phrase xylophonequartz"),
        )
        conn.commit()
        chunk_id = conn.execute("SELECT id FROM chunks WHERE topic_heading='Bookkeeping'").fetchone()[0]

        # Confirm it's in FTS
        assert conn.execute(
            "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH 'xylophonequartz'"
        ).fetchone() is not None

        conn.execute("DELETE FROM chunks WHERE id = ?", (chunk_id,))
        conn.commit()

        result = conn.execute(
            "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH 'xylophonequartz'"
        ).fetchone()
        conn.close()
        assert result is None

    def test_update_trigger_reindexes_fts(self, tmp_db):
        """UPDATE trigger must remove old text and index new text in chunks_fts."""
        create_knowledge_db(tmp_db)
        conn = sqlite3.connect(tmp_db)

        conn.execute(
            "INSERT INTO calls (title, slug) VALUES (?, ?)",
            ("Call U", "call-u"),
        )
        call_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO chunks (call_id, topic_heading, content) VALUES (?, ?, ?)",
            (call_id, "Old Heading", "Unique old content zebratangerine"),
        )
        conn.commit()
        chunk_id = conn.execute("SELECT id FROM chunks WHERE topic_heading='Old Heading'").fetchone()[0]

        # Confirm old text is in FTS
        assert conn.execute(
            "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH 'zebratangerine'"
        ).fetchone() is not None

        # Update the chunk
        conn.execute(
            "UPDATE chunks SET topic_heading = ?, content = ? WHERE id = ?",
            ("New Heading", "Unique new content mangoplatypus", chunk_id),
        )
        conn.commit()

        # Old text should no longer match
        assert conn.execute(
            "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH 'zebratangerine'"
        ).fetchone() is None

        # New text should match
        assert conn.execute(
            "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH 'mangoplatypus'"
        ).fetchone() is not None

        conn.close()

    def test_porter_stemming(self, tmp_db):
        """FTS5 porter tokenizer must match stemmed variants."""
        create_knowledge_db(tmp_db)
        conn = sqlite3.connect(tmp_db)

        conn.execute("INSERT INTO calls (title, slug) VALUES ('C', 'c')")
        call_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO chunks (call_id, topic_heading, content) VALUES (?, ?, ?)",
            (call_id, "Investing", "Discussion about investment opportunities"),
        )
        conn.commit()

        # "invest" should match "investment" and "investing" via porter stemming
        results = conn.execute(
            "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH 'invest'",
        ).fetchall()
        conn.close()
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Chat DB
# ---------------------------------------------------------------------------

class TestCreateChatDb:
    def test_creates_sessions_table(self, tmp_db):
        create_chat_db(tmp_db)
        conn = sqlite3.connect(tmp_db)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        conn.close()
        assert "sessions" in tables

    def test_creates_messages_table(self, tmp_db):
        create_chat_db(tmp_db)
        conn = sqlite3.connect(tmp_db)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        conn.close()
        assert "messages" in tables

    def test_creates_messages_index(self, tmp_db):
        create_chat_db(tmp_db)
        conn = sqlite3.connect(tmp_db)
        indexes = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )}
        conn.close()
        assert "idx_messages_session" in indexes

    def test_idempotent(self, tmp_db):
        create_chat_db(tmp_db)
        create_chat_db(tmp_db)  # should not raise

    def test_sessions_columns(self, tmp_db):
        create_chat_db(tmp_db)
        conn = sqlite3.connect(tmp_db)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(sessions)")}
        conn.close()
        assert {"id", "title", "started_at", "last_message_at"} <= cols

    def test_messages_columns(self, tmp_db):
        create_chat_db(tmp_db)
        conn = sqlite3.connect(tmp_db)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(messages)")}
        conn.close()
        assert {"id", "session_id", "role", "content", "created_at"} <= cols

    def test_insert_and_query(self, tmp_db):
        create_chat_db(tmp_db)
        conn = sqlite3.connect(tmp_db)
        conn.execute(
            "INSERT INTO sessions (title, started_at) VALUES (?, ?)",
            ("Test session", "2026-03-17T10:00:00"),
        )
        session_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, "user", "Hello", "2026-03-17T10:00:01"),
        )
        conn.commit()

        msgs = conn.execute(
            "SELECT content FROM messages WHERE session_id = ?", (session_id,)
        ).fetchall()
        conn.close()
        assert len(msgs) == 1
        assert msgs[0][0] == "Hello"
