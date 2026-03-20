import pytest

from app.llm import (
    ERROR_MESSAGES,
    SYSTEM_PROMPT,
    build_request,
    should_replace_context,
)


# ---------------------------------------------------------------------------
# build_request
# ---------------------------------------------------------------------------

SAMPLE_CHUNKS = [
    {
        "topic_heading": "S-Corp Formation",
        "content": "Christopher explains S-Corp benefits.",
        "speakers": '["Christopher"]',
        "call_title": "January 16, 2026 Call",
        "call_date": "2026-01-16",
        "call_url": "https://example.com/jan16",
    },
    {
        "topic_heading": "Real Estate",
        "content": "Greg discusses rental properties.",
        "speakers": '["Greg"]',
        "call_title": "February 3, 2026 Call",
        "call_date": "2026-02-03",
        "call_url": "https://example.com/feb3",
    },
]

SAMPLE_HISTORY = [
    {"role": "user", "content": "What is an S-Corp?"},
    {"role": "assistant", "content": "An S-Corp is a tax election..."},
]


def test_build_request_top_level_keys():
    body = build_request(SAMPLE_CHUNKS, [], "Tell me about taxes")
    assert "model" in body
    assert "max_tokens" in body
    assert "system" in body
    assert "messages" in body


def test_build_request_system_has_two_blocks():
    body = build_request(SAMPLE_CHUNKS, [], "Tell me about taxes")
    system = body["system"]
    assert len(system) == 2


def test_build_request_cache_control_on_second_block():
    body = build_request(SAMPLE_CHUNKS, [], "Tell me about taxes")
    system = body["system"]
    # First block: no cache_control
    assert "cache_control" not in system[0]
    # Second block: cache_control present and correct
    assert system[1].get("cache_control") == {"type": "ephemeral"}


def test_build_request_first_system_block_is_system_prompt():
    body = build_request(SAMPLE_CHUNKS, [], "question")
    assert body["system"][0]["text"] == SYSTEM_PROMPT


def test_build_request_context_block_contains_chunk_data():
    body = build_request(SAMPLE_CHUNKS, [], "question")
    context_text = body["system"][1]["text"]
    assert "S-Corp Formation" in context_text
    assert "Real Estate" in context_text
    assert "January 16, 2026 Call" in context_text


def test_build_request_appends_user_query():
    body = build_request(SAMPLE_CHUNKS, [], "My question here")
    messages = body["messages"]
    assert messages[-1] == {"role": "user", "content": "My question here"}


def test_build_request_includes_conversation_history():
    body = build_request(SAMPLE_CHUNKS, SAMPLE_HISTORY, "Follow-up question")
    messages = body["messages"]
    assert len(messages) == 3
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"
    assert messages[2]["content"] == "Follow-up question"


def test_build_request_empty_chunks():
    body = build_request([], [], "question")
    system = body["system"]
    assert system[1]["cache_control"] == {"type": "ephemeral"}


# ---------------------------------------------------------------------------
# should_replace_context
# ---------------------------------------------------------------------------

def test_replace_when_no_overlap():
    assert should_replace_context({1, 2, 3}, {4, 5, 6}) is True


def test_keep_when_full_overlap():
    assert should_replace_context({1, 2, 3}, {1, 2, 3}) is False


def test_keep_when_exactly_50_percent_overlap():
    # 2 out of 4 new chunks overlap = 50% — should KEEP (not replace)
    assert should_replace_context({1, 2}, {1, 2, 3, 4}) is False


def test_replace_when_below_50_percent():
    # 1 out of 4 new chunks overlap = 25% — should replace
    assert should_replace_context({1}, {1, 2, 3, 4}) is True


def test_keep_when_above_50_percent():
    # 3 out of 4 new chunks overlap = 75% — should keep
    assert should_replace_context({1, 2, 3, 10}, {1, 2, 3, 4}) is False


def test_no_replace_when_new_chunks_empty():
    assert should_replace_context({1, 2, 3}, set()) is False


# ---------------------------------------------------------------------------
# ERROR_MESSAGES
# ---------------------------------------------------------------------------

def test_error_messages_keys():
    assert 401 in ERROR_MESSAGES
    assert 403 in ERROR_MESSAGES
    assert 429 in ERROR_MESSAGES
    assert 500 in ERROR_MESSAGES
    assert 502 in ERROR_MESSAGES
    assert 503 in ERROR_MESSAGES
    assert "connection" in ERROR_MESSAGES
    assert "timeout" in ERROR_MESSAGES


def test_error_messages_mention_travis():
    for key in (401, 403):
        assert "Travis" in ERROR_MESSAGES[key]


def test_system_prompt_non_empty():
    assert len(SYSTEM_PROMPT) > 50
