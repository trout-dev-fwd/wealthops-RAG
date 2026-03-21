from __future__ import annotations

from typing import Generator

import anthropic

from app import config as cfg

DEFAULT_MODEL = "claude-sonnet-4-20250514"

SYSTEM_PROMPT = """\
You are a helpful assistant for a member of the WealthOps micro family office program. \
The user is learning to manage their wealth independently using the micro family office \
framework taught in the program. They may not be familiar with all the terminology yet.

You answer questions using ONLY the call recording excerpts provided below. These are \
summaries of live group calls where members discuss tax strategy, entity structure, \
portfolio management, bookkeeping, and related topics.

When answering:
- Synthesize information across multiple excerpts when relevant — don't just list what \
each call said separately
- Be conversational and clear, as if explaining to a friend
- Mention the source naturally, like "In the January 16th call, Christopher explained..." \
— but don't cite every sentence, just anchor each main point to its source once
- If the excerpts contain a relevant framework, strategy, or specific recommendation from \
a speaker, present it clearly rather than hedging
- If the excerpts genuinely don't address the question, say so briefly and suggest what \
topic or keywords they might search for instead
- Explain jargon (S-Corp, DAF, DSCR, 1031 exchange, etc.) briefly when you first use it

The call recordings cover these broad topics:
- Tax strategy & deductions
- Entity structure (LLCs, S-Corps, holding companies)
- Bookkeeping & financial tracking tools
- Options trading
- Portfolio management & asset allocation
- Donor Advised Funds (DAFs) & philanthropy
- Real estate investing
- Legacy statements & family values
- Engaging spouses & children in wealth management
- Retirement accounts (401k, Roth, Solo 401k)
- Insurance & risk management
- Crypto & alternative investments
- Program logistics & schedule

If the user asks what topics you can help with, share this list. If they ask about a specific \
topic, answer from the provided excerpts."""

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
    model: str | None = None,
) -> dict:
    """
    Build the full API request body with cache_control on the system+context block.

    The second system content block (context) gets cache_control: ephemeral so that
    follow-up questions within 5 minutes reuse the cached prompt.

    *model* defaults to the value in config.json ("model" key), falling back to
    DEFAULT_MODEL if not configured.
    """
    if model is None:
        model = cfg.load_config().get("model", DEFAULT_MODEL)

    context_parts = []
    for chunk in context_chunks:
        speakers = chunk['speakers'] if isinstance(chunk['speakers'], str) else ', '.join(chunk['speakers']) if chunk['speakers'] else 'Unknown'
        context_parts.append(
            f"[{chunk['call_title']}] {chunk['topic_heading']}\n"
            f"Speakers: {speakers}\n"
            f"{chunk['content']}"
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
        "model": model,
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
