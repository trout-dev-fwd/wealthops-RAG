from unittest.mock import MagicMock, patch

import pytest

from app.llm import (
    DEFAULT_MODEL,
    ERROR_MESSAGES,
    SYSTEM_PROMPT,
    build_request,
    should_replace_context,
    stream_response,
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
    body = build_request(SAMPLE_CHUNKS, [], "Tell me about taxes", model=DEFAULT_MODEL)
    assert "model" in body
    assert "max_tokens" in body
    assert "system" in body
    assert "messages" in body


def test_build_request_system_has_two_blocks():
    body = build_request(SAMPLE_CHUNKS, [], "Tell me about taxes", model=DEFAULT_MODEL)
    system = body["system"]
    assert len(system) == 2


def test_build_request_cache_control_on_second_block():
    body = build_request(SAMPLE_CHUNKS, [], "Tell me about taxes", model=DEFAULT_MODEL)
    system = body["system"]
    # First block: no cache_control
    assert "cache_control" not in system[0]
    # Second block: cache_control present and correct
    assert system[1].get("cache_control") == {"type": "ephemeral"}


def test_build_request_first_system_block_is_system_prompt():
    body = build_request(SAMPLE_CHUNKS, [], "question", model=DEFAULT_MODEL)
    assert body["system"][0]["text"] == SYSTEM_PROMPT


def test_build_request_context_block_contains_chunk_data():
    body = build_request(SAMPLE_CHUNKS, [], "question", model=DEFAULT_MODEL)
    context_text = body["system"][1]["text"]
    assert "[January 16, 2026 Call] S-Corp Formation" in context_text
    assert "[February 3, 2026 Call] Real Estate" in context_text
    assert "Speakers:" in context_text


def test_build_request_context_format_is_lean():
    """Context uses bracket format, not markdown headers."""
    body = build_request(SAMPLE_CHUNKS, [], "question", model=DEFAULT_MODEL)
    context_text = body["system"][1]["text"]
    assert "###" not in context_text
    assert "**Source:**" not in context_text
    assert "**Speakers:**" not in context_text


def test_build_request_appends_user_query():
    body = build_request(SAMPLE_CHUNKS, [], "My question here", model=DEFAULT_MODEL)
    messages = body["messages"]
    assert messages[-1] == {"role": "user", "content": "My question here"}


def test_build_request_includes_conversation_history():
    body = build_request(SAMPLE_CHUNKS, SAMPLE_HISTORY, "Follow-up question", model=DEFAULT_MODEL)
    messages = body["messages"]
    assert len(messages) == 3
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"
    assert messages[2]["content"] == "Follow-up question"


def test_build_request_empty_chunks():
    body = build_request([], [], "question", model=DEFAULT_MODEL)
    system = body["system"]
    assert system[1]["cache_control"] == {"type": "ephemeral"}


def test_build_request_uses_explicit_model():
    body = build_request(SAMPLE_CHUNKS, [], "q", model="claude-haiku-4-5-20251001")
    assert body["model"] == "claude-haiku-4-5-20251001"


def test_build_request_defaults_model_from_config():
    with patch("app.llm.cfg.load_config", return_value={"model": "claude-haiku-4-5-20251001"}):
        body = build_request(SAMPLE_CHUNKS, [], "q")
    assert body["model"] == "claude-haiku-4-5-20251001"


def test_build_request_speakers_string_passthrough():
    """When speakers is already a JSON string, it passes through as-is."""
    body = build_request(SAMPLE_CHUNKS, [], "q", model=DEFAULT_MODEL)
    context_text = body["system"][1]["text"]
    assert '["Christopher"]' in context_text


def test_build_request_speakers_list_joined():
    """When speakers is a list, it gets comma-joined."""
    chunks = [{
        **SAMPLE_CHUNKS[0],
        "speakers": ["Christopher", "Greg"],
    }]
    body = build_request(chunks, [], "q", model=DEFAULT_MODEL)
    context_text = body["system"][1]["text"]
    assert "Christopher, Greg" in context_text


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


# ---------------------------------------------------------------------------
# stream_response
# ---------------------------------------------------------------------------

DUMMY_REQUEST = {"model": "claude-sonnet-4-20250514", "max_tokens": 10, "messages": []}


def _mock_stream(tokens: list[str]):
    """Return a context-manager mock whose text_stream yields *tokens*."""
    stream = MagicMock()
    stream.__enter__ = MagicMock(return_value=stream)
    stream.__exit__ = MagicMock(return_value=False)
    stream.text_stream = iter(tokens)
    return stream


def test_stream_response_yields_text_false_tuples():
    tokens = ["Hello", " world", "!"]
    with patch("app.llm.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.stream.return_value = _mock_stream(tokens)
        result = list(stream_response("sk-test", DUMMY_REQUEST))
    assert result == [("Hello", False), (" world", False), ("!", False)]


def test_stream_response_auth_error():
    import anthropic

    with patch("app.llm.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.stream.side_effect = (
            anthropic.AuthenticationError(
                message="invalid key",
                response=MagicMock(status_code=401),
                body={},
            )
        )
        result = list(stream_response("sk-bad", DUMMY_REQUEST))
    assert len(result) == 1
    text, is_error = result[0]
    assert is_error is True
    assert text == ERROR_MESSAGES[401]


def test_stream_response_rate_limit_error():
    import anthropic

    with patch("app.llm.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.stream.side_effect = (
            anthropic.RateLimitError(
                message="rate limited",
                response=MagicMock(status_code=429),
                body={},
            )
        )
        result = list(stream_response("sk-test", DUMMY_REQUEST))
    assert len(result) == 1
    assert result[0] == (ERROR_MESSAGES[429], True)


def test_stream_response_connection_error():
    import anthropic

    with patch("app.llm.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.stream.side_effect = (
            anthropic.APIConnectionError(request=MagicMock())
        )
        result = list(stream_response("sk-test", DUMMY_REQUEST))
    assert len(result) == 1
    assert result[0] == (ERROR_MESSAGES["connection"], True)


def test_stream_response_mid_stream_error():
    """Some tokens arrive before the stream raises an exception."""
    import anthropic

    def _broken_stream():
        yield "Partial "
        yield "answer"
        raise anthropic.APIConnectionError(request=MagicMock())

    stream = MagicMock()
    stream.__enter__ = MagicMock(return_value=stream)
    stream.__exit__ = MagicMock(return_value=False)
    stream.text_stream = _broken_stream()

    with patch("app.llm.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.stream.return_value = stream
        result = list(stream_response("sk-test", DUMMY_REQUEST))

    assert result[0] == ("Partial ", False)
    assert result[1] == ("answer", False)
    assert result[2] == (ERROR_MESSAGES["connection"], True)
