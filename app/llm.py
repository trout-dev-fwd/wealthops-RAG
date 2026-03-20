from __future__ import annotations

from typing import Generator

import anthropic

SYSTEM_PROMPT = """You are a helpful assistant for a member of the WealthOps micro family \
office program. You answer questions based on the call recording summaries provided below \
as context.

Rules:
- Only answer based on what's in the provided context
- If the context doesn't fully answer the question, say what you can and be honest about \
what isn't covered
- Always mention which call recording(s) your answer comes from, like "Christopher talked \
about this in the January 16th call"
- Be conversational and clear — explain things the way you would to a friend over dinner
- If multiple calls cover the same topic, bring them together into one clear answer
- Avoid jargon unless the source material uses it, and explain it when you do"""

ERROR_MESSAGES: dict = {
    401: "Your API key doesn't seem to be working. Go to Settings to update it, or ask Travis for help.",
    403: "Your API key doesn't seem to be working. Go to Settings to update it, or ask Travis for help.",
    429: "You're sending questions too quickly. Wait a minute and try again.",
    500: "Something went wrong on Claude's end. Try again in a moment.",
    502: "Something went wrong on Claude's end. Try again in a moment.",
    503: "Something went wrong on Claude's end. Try again in a moment.",
    "connection": "Can't reach the internet. Check your WiFi and try again.",
    "timeout": "That's taking too long. Try again with a shorter question.",
}


def build_request(
    context_chunks: list[dict],
    conversation_history: list[dict],
    user_query: str,
) -> dict:
    """
    Build the full API request body with cache_control on the system+context block.

    The second system content block (context) gets cache_control: ephemeral so that
    follow-up questions within 5 minutes reuse the cached prompt.
    """
    context_parts = []
    for chunk in context_chunks:
        context_parts.append(
            f"### {chunk['topic_heading']}\n"
            f"**Source:** {chunk['call_title']} ({chunk['call_date']})\n"
            f"**Speakers:** {chunk['speakers']}\n\n"
            f"{chunk['content']}\n"
        )
    context_block = "\n---\n".join(context_parts)

    system = [
        {
            "type": "text",
            "text": SYSTEM_PROMPT,
        },
        {
            "type": "text",
            "text": f"## Relevant call recording excerpts:\n\n{context_block}",
            "cache_control": {"type": "ephemeral"},
        },
    ]

    messages = []
    for msg in conversation_history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_query})

    return {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 2048,
        "system": system,
        "messages": messages,
    }


def should_replace_context(old_chunk_ids: set, new_chunk_ids: set) -> bool:
    """
    Return True if the context should be replaced entirely (topic changed).
    Replace when <50% of new chunk IDs are already in the old context.
    Keep (return False) when >=50% overlap.
    """
    if not new_chunk_ids:
        return False
    overlap = old_chunk_ids & new_chunk_ids
    return len(overlap) / len(new_chunk_ids) < 0.5


def stream_response(
    api_key: str, request_body: dict
) -> Generator[tuple[str, bool], None, None]:
    """
    Yield (text, is_error) tuples from the Claude streaming API.
    Normal tokens yield (text, False).
    If an error occurs (even mid-stream), yields (error_message, True) as the
    final item so the GUI can render it separately from any partial content.
    """
    client = anthropic.Anthropic(api_key=api_key)
    try:
        with client.messages.stream(**request_body) as stream:
            for text in stream.text_stream:
                yield text, False
    except anthropic.AuthenticationError:
        yield ERROR_MESSAGES[401], True
    except anthropic.PermissionDeniedError:
        yield ERROR_MESSAGES[403], True
    except anthropic.RateLimitError:
        yield ERROR_MESSAGES[429], True
    except anthropic.APIStatusError as exc:
        status = exc.status_code
        yield ERROR_MESSAGES.get(status, ERROR_MESSAGES[500]), True
    except anthropic.APITimeoutError:
        yield ERROR_MESSAGES["timeout"], True
    except anthropic.APIConnectionError:
        yield ERROR_MESSAGES["connection"], True
