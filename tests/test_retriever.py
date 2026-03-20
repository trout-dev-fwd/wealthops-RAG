import sqlite3
import pytest

from app.retriever import search_chunks
from shared.schema import create_knowledge_db


@pytest.fixture
def test_db(tmp_path):
    """Create a minimal knowledge DB with known data for testing."""
    db_path = str(tmp_path / "wealthops.db")
    create_knowledge_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO calls (title, slug, published_at, url) VALUES (?, ?, ?, ?)",
        ("January 16, 2026 Call", "jan-16-2026", "2026-01-16", "https://example.com/jan16"),
    )
    call_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    conn.execute(
        "INSERT INTO chunks (call_id, topic_heading, content, speakers) VALUES (?, ?, ?, ?)",
        (
            call_id,
            "S-Corp Formation",
            "Christopher explains how an S-Corp provides liability protection and tax benefits.",
            '["Christopher"]',
        ),
    )
    conn.execute(
        "INSERT INTO chunks (call_id, topic_heading, content, speakers) VALUES (?, ?, ?, ?)",
        (
            call_id,
            "Real Estate Investing",
            "Greg discusses buying rental properties and leveraging depreciation.",
            '["Greg"]',
        ),
    )
    conn.commit()
    conn.close()
    return db_path


def test_search_returns_matching_chunk(test_db):
    # Search for a word in the content (avoid hyphens — FTS5 treats '-' as NOT)
    results = search_chunks(test_db, "liability")
    assert len(results) >= 1
    headings = [r["topic_heading"] for r in results]
    assert "S-Corp Formation" in headings


def test_search_returns_correct_fields(test_db):
    results = search_chunks(test_db, "depreciation")
    assert len(results) >= 1
    r = results[0]
    assert "id" in r
    assert "topic_heading" in r
    assert "content" in r
    assert "speakers" in r
    assert "call_title" in r
    assert "call_date" in r
    assert "call_url" in r


def test_search_joins_call_metadata(test_db):
    results = search_chunks(test_db, "rental properties")
    assert len(results) >= 1
    r = results[0]
    assert r["call_title"] == "January 16, 2026 Call"
    assert r["call_date"] == "2026-01-16"
    assert r["call_url"] == "https://example.com/jan16"


def test_search_returns_empty_list_on_no_match(test_db):
    results = search_chunks(test_db, "zzznomatchxxx")
    assert results == []


def test_search_respects_limit(test_db):
    # Both chunks contain call-related content; insert more to test limit
    conn = sqlite3.connect(test_db)
    call_id = conn.execute("SELECT id FROM calls LIMIT 1").fetchone()[0]
    for i in range(10):
        conn.execute(
            "INSERT INTO chunks (call_id, topic_heading, content, speakers) VALUES (?, ?, ?, ?)",
            (call_id, f"Topic {i}", f"content about investing number {i}", "[]"),
        )
    conn.commit()
    conn.close()

    results = search_chunks(test_db, "investing", limit=3)
    assert len(results) <= 3


def test_search_returns_empty_on_missing_db(tmp_path):
    # Should not raise — just return empty list
    results = search_chunks(str(tmp_path / "nonexistent.db"), "anything")
    assert results == []
