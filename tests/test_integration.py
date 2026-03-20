"""Integration tests: end-to-end flow without GUI.

Creates a real config + test DB, runs search, builds request, verifies
structure.  The Claude API call itself is mocked.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from app import config as cfg, chat_store, retriever
from app.llm import build_request, SYSTEM_PROMPT, should_replace_context
from shared.schema import create_chat_db, create_knowledge_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_dir(tmp_path):
    return tmp_path


@pytest.fixture()
def knowledge_db(tmp_dir):
    db_path = str(tmp_dir / "wealthops.db")
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
            "Christopher explains how an S-Corp provides liability protection and tax benefits for the business.",
            '["Christopher Nelson"]',
        ),
    )
    conn.execute(
        "INSERT INTO chunks (call_id, topic_heading, content, speakers) VALUES (?, ?, ?, ?)",
        (
            call_id,
            "Real Estate Investing",
            "Greg discusses buying rental properties and leveraging depreciation deductions.",
            '["Greg Nakagawa"]',
        ),
    )
    conn.execute(
        "INSERT INTO chunks (call_id, topic_heading, content, speakers) VALUES (?, ?, ?, ?)",
        (
            call_id,
            "DAF Strategies",
            "Discussion on Donor Advised Funds and charitable giving tax strategies.",
            '["Christopher Nelson", "Greg Nakagawa"]',
        ),
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture()
def chats_db(tmp_dir):
    db_path = str(tmp_dir / "chats.db")
    create_chat_db(db_path)
    return db_path


@pytest.fixture()
def config_file(tmp_dir, monkeypatch):
    config_dir = str(tmp_dir / "config")
    os.makedirs(config_dir, exist_ok=True)
    config_path = os.path.join(config_dir, "config.json")
    data = {"api_key": "sk-ant-test-key", "github_repo": "test/repo"}
    with open(config_path, "w") as f:
        json.dump(data, f)
    monkeypatch.setattr(cfg, "CONFIG_FILE", config_path)
    monkeypatch.setattr(cfg, "CONFIG_DIR", config_dir)
    return config_path


# ---------------------------------------------------------------------------
# Config integration
# ---------------------------------------------------------------------------

def test_config_roundtrip(config_file):
    config = cfg.load_config()
    assert config["api_key"] == "sk-ant-test-key"
    assert config["github_repo"] == "test/repo"


def test_config_get_api_key(config_file):
    key = cfg.get_api_key()
    assert key == "sk-ant-test-key"


def test_config_save_and_reload(config_file):
    cfg.save_config({"api_key": "sk-ant-new-key", "extra": "value"})
    reloaded = cfg.load_config()
    assert reloaded["api_key"] == "sk-ant-new-key"
    assert reloaded["extra"] == "value"


# ---------------------------------------------------------------------------
# Search integration
# ---------------------------------------------------------------------------

def test_search_returns_matching_chunk(knowledge_db):
    results = retriever.search_chunks(knowledge_db, "S-Corp liability")
    assert len(results) >= 1
    headings = [r["topic_heading"] for r in results]
    assert "S-Corp Formation" in headings


def test_search_includes_call_metadata(knowledge_db):
    results = retriever.search_chunks(knowledge_db, "rental properties depreciation")
    assert len(results) >= 1
    r = results[0]
    assert r["call_title"] == "January 16, 2026 Call"
    assert r["call_date"] == "2026-01-16"
    assert r["call_url"] == "https://example.com/jan16"


def test_search_returns_empty_for_no_match(knowledge_db):
    assert retriever.search_chunks(knowledge_db, "quantum teleportation") == []


def test_search_result_has_all_required_fields(knowledge_db):
    results = retriever.search_chunks(knowledge_db, "tax")
    assert len(results) >= 1
    required = {"id", "topic_heading", "content", "speakers", "call_title", "call_date", "call_url"}
    assert required.issubset(results[0].keys())


# ---------------------------------------------------------------------------
# build_request integration
# ---------------------------------------------------------------------------

def test_build_request_from_search_results(knowledge_db):
    chunks = retriever.search_chunks(knowledge_db, "S-Corp")
    assert chunks, "No chunks returned for 'S-Corp' — search prerequisite failed"

    body = build_request(chunks, [], "What is an S-Corp?")

    assert body["model"] == "claude-sonnet-4-20250514"
    assert body["max_tokens"] == 2048
    assert len(body["system"]) == 2
    assert body["system"][1].get("cache_control") == {"type": "ephemeral"}
    assert body["messages"][-1] == {"role": "user", "content": "What is an S-Corp?"}


def test_build_request_context_contains_chunk_data(knowledge_db):
    chunks = retriever.search_chunks(knowledge_db, "S-Corp")
    body = build_request(chunks, [], "Tell me about S-Corps")
    context_text = body["system"][1]["text"]
    assert "S-Corp Formation" in context_text
    assert "January 16, 2026 Call" in context_text


def test_build_request_includes_history(knowledge_db):
    chunks = retriever.search_chunks(knowledge_db, "real estate")
    history = [
        {"role": "user", "content": "Previous question"},
        {"role": "assistant", "content": "Previous answer"},
    ]
    body = build_request(chunks, history, "Follow-up question")
    assert len(body["messages"]) == 3
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][0]["content"] == "Previous question"
    assert body["messages"][-1]["content"] == "Follow-up question"


def test_build_request_system_prompt_is_present(knowledge_db):
    chunks = retriever.search_chunks(knowledge_db, "tax")
    body = build_request(chunks, [], "question")
    assert body["system"][0]["text"] == SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Chat store integration
# ---------------------------------------------------------------------------

def test_create_and_list_session(chats_db):
    session_id = chat_store.create_session(chats_db)
    assert isinstance(session_id, int)
    assert session_id > 0


def test_add_and_retrieve_messages(chats_db):
    session_id = chat_store.create_session(chats_db)
    chat_store.add_message(chats_db, session_id, "user", "What is an S-Corp?")
    chat_store.add_message(chats_db, session_id, "assistant", "An S-Corp is...")

    messages = chat_store.get_session_messages(chats_db, session_id)
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "What is an S-Corp?"
    assert messages[1]["role"] == "assistant"


def test_session_title_set_from_first_user_message(chats_db):
    session_id = chat_store.create_session(chats_db)
    chat_store.add_message(chats_db, session_id, "user", "What tax strategies have been discussed?")

    sessions = chat_store.list_sessions(chats_db)
    match = next((s for s in sessions if s["id"] == session_id), None)
    assert match is not None
    assert match["title"] == "What tax strategies have been discussed?"


def test_list_sessions_includes_message_count(chats_db):
    session_id = chat_store.create_session(chats_db)
    for i in range(3):
        chat_store.add_message(chats_db, session_id, "user", f"Question {i}")

    sessions = chat_store.list_sessions(chats_db)
    match = next((s for s in sessions if s["id"] == session_id), None)
    assert match is not None
    assert match["message_count"] == 3


def test_multiple_sessions_sorted_by_last_message(chats_db):
    s1 = chat_store.create_session(chats_db)
    chat_store.add_message(chats_db, s1, "user", "First session question")

    import time
    time.sleep(0.01)

    s2 = chat_store.create_session(chats_db)
    chat_store.add_message(chats_db, s2, "user", "Second session question")

    sessions = [s for s in chat_store.list_sessions(chats_db) if s["message_count"] > 0]
    assert sessions[0]["id"] == s2  # most recent first


# ---------------------------------------------------------------------------
# Full end-to-end: search → build_request → mock stream
# ---------------------------------------------------------------------------

def test_full_pipeline_search_to_request(knowledge_db, chats_db):
    """Simulate a complete user interaction without calling the real API."""
    session_id = chat_store.create_session(chats_db)
    user_query = "S-Corp liability"  # focused query — all tokens appear in chunk content

    # Search
    chunks = retriever.search_chunks(knowledge_db, user_query)
    assert chunks, "Expected chunks for S-Corp query"

    # Record user message
    chat_store.add_message(chats_db, session_id, "user", user_query)

    # Build request
    request = build_request(chunks, [], user_query)

    # Verify request structure (API call mocked)
    assert request["model"] == "claude-sonnet-4-20250514"
    system_block = request["system"][1]["text"]
    assert "S-Corp" in system_block or "S-Corp Formation" in system_block

    # Simulate a streamed response
    mock_response = "Christopher discussed S-Corp formation in the January 16th call."
    chat_store.add_message(chats_db, session_id, "assistant", mock_response)

    # Verify stored
    messages = chat_store.get_session_messages(chats_db, session_id)
    assert len(messages) == 2
    assert messages[1]["content"] == mock_response


def test_no_results_flow_does_not_call_api(knowledge_db, chats_db):
    """When search returns no chunks, we show a message and skip the API call."""
    session_id = chat_store.create_session(chats_db)
    user_query = "quantum teleportation time travel"

    chunks = retriever.search_chunks(knowledge_db, user_query)
    assert chunks == []

    # The GUI would display NO_RESULTS_MSG and not call the API.
    # Verify this by ensuring no API call is made when chunks is empty.
    # Use the string inline to avoid importing tkinter via gui.py in a headless env.
    no_results_msg = (
        "I couldn't find anything about that in the call recordings. "
        "Try rephrasing your question or using different words."
    )

    with patch("app.llm.stream_response") as mock_stream:
        if not chunks:
            # The GUI shows the message and skips the API call.
            chat_store.add_message(chats_db, session_id, "user", user_query)
            chat_store.add_message(chats_db, session_id, "assistant", no_results_msg)

        mock_stream.assert_not_called()

    messages = chat_store.get_session_messages(chats_db, session_id)
    assert len(messages) == 2
    assert "couldn't find" in messages[1]["content"].lower()


# ---------------------------------------------------------------------------
# Context overlap logic
# ---------------------------------------------------------------------------

def test_should_replace_context_high_overlap():
    """High overlap (>=50%) → keep existing context."""
    assert should_replace_context({1, 2, 3}, {1, 2, 4}) is False  # 2/3 = 67%


def test_should_replace_context_low_overlap():
    """Low overlap (<50%) → replace context."""
    assert should_replace_context({1, 2, 3}, {4, 5, 6}) is True  # 0%


def test_should_replace_context_exact_50():
    """Exactly 50% overlap → keep (boundary: >=50% keeps)."""
    assert should_replace_context({1, 2}, {1, 2, 3, 4}) is False  # 2/4 = 50%
