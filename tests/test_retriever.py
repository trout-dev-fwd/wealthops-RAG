import sqlite3
import pytest

from app.retriever import STOP_WORDS, sanitize_fts5_query, search_chunks
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


# ---------------------------------------------------------------------------
# FTS5 query sanitization
# ---------------------------------------------------------------------------

def test_sanitize_joins_with_or():
    assert sanitize_fts5_query("hello world") == '"hello" OR "world"'


def test_sanitize_preserves_hyphens():
    assert sanitize_fts5_query("S-Corp") == '"S-Corp"'


def test_sanitize_escapes_internal_quotes():
    result = sanitize_fts5_query('the "best" strategy')
    # "the" is a stop word and gets filtered out
    assert result == '"""best""" OR "strategy"'


def test_sanitize_handles_empty_query():
    assert sanitize_fts5_query("") == '""'


def test_sanitize_handles_asterisk():
    assert sanitize_fts5_query("tax*") == '"tax*"'


def test_sanitize_handles_parentheses():
    assert sanitize_fts5_query("(S-Corp)") == '"(S-Corp)"'


def test_sanitize_filters_stop_words():
    result = sanitize_fts5_query("What can you tell me about real estate")
    assert result == '"real" OR "estate"'


def test_sanitize_all_stop_words_returns_empty():
    result = sanitize_fts5_query("What is this")
    assert result == '""'


def test_sanitize_stop_words_case_insensitive():
    result = sanitize_fts5_query("THE quick FOX")
    assert result == '"quick" OR "FOX"'


def test_search_multi_word_or_returns_results(test_db):
    """Multi-word queries should match chunks containing ANY term (OR behavior)."""
    results = search_chunks(test_db, "real estate investing")
    assert len(results) >= 1
    headings = [r["topic_heading"] for r in results]
    assert "Real Estate Investing" in headings


def test_search_hyphenated_query_with_or(test_db):
    """S-Corp still matches with OR joining."""
    results = search_chunks(test_db, "S-Corp tax")
    assert len(results) >= 1
    headings = [r["topic_heading"] for r in results]
    assert "S-Corp Formation" in headings


def test_search_only_stop_words_returns_empty(test_db):
    results = search_chunks(test_db, "What is the")
    assert results == []


def test_search_query_with_quotes_does_not_break(test_db):
    # Should not raise — returns empty list or results, never an error
    results = search_chunks(test_db, 'the "best" strategy')
    assert isinstance(results, list)


def test_search_query_with_special_chars_does_not_break(test_db):
    # Parentheses, asterisks, etc. should not cause FTS5 syntax errors
    results = search_chunks(test_db, "tax* (strategies)")
    assert isinstance(results, list)
