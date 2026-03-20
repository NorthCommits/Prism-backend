import os
import json
import httpx
from typing import List, Optional

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
COMPRESSION_MODEL = "openai/gpt-4o-mini"

# thresholds
FULL_HISTORY_LIMIT = 8       # send full history under this
RECENT_WINDOW_MEDIUM = 6     # keep last N messages for medium conversations
RECENT_WINDOW_LONG = 4       # keep last N messages for long conversations
MEDIUM_THRESHOLD = 15        # above this → long compression strategy


SUMMARY_SYSTEM_PROMPT = """
You are a conversation summarizer for Prism, an AI copilot.

Summarize the provided conversation history into a concise, 
dense summary that preserves:
- Key facts, decisions, and conclusions
- Code snippets or technical details that were discussed
- User preferences or context about who the user is
- Any important data, numbers, or specific details mentioned
- Which AI model (coding/writing) handled which topics

Keep the summary under 300 words.
Be factual and precise. Do not add opinions.
Format: plain paragraph, no bullet points.
""".strip()


async def summarize_messages(messages: List[dict]) -> str:
    """
    Uses GPT-4o-mini to compress a list of messages into a summary string.
    Falls back to simple truncation if API fails.
    """
    if not messages:
        return ""

    # format messages for summarization
    conversation_text = "\n".join([
        f"{msg['role'].upper()} ({msg.get('model_id', 'unknown')}): {msg['content'][:500]}"
        for msg in messages
    ])

    headers = {
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/prism-ai",
        "X-Title": "Prism"
    }

    payload = {
        "model": COMPRESSION_MODEL,
        "messages": [
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": f"Summarize this conversation:\n\n{conversation_text}"}
        ],
        "temperature": 0,
        "max_tokens": 400
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                OPENROUTER_API_URL,
                json=payload,
                headers=headers
            )

        if response.status_code != 200:
            return _simple_truncate(messages)

        data = response.json()
        return data["choices"][0]["message"]["content"].strip()

    except Exception:
        return _simple_truncate(messages)


def _simple_truncate(messages: List[dict]) -> str:
    """
    Fallback: creates a basic summary from message content.
    """
    parts = []
    for msg in messages[:10]:
        role = msg["role"].upper()
        content = msg["content"][:200]
        parts.append(f"{role}: {content}")
    return "Earlier conversation summary:\n" + "\n".join(parts)


def _add_model_context_note(
    messages: List[dict],
    current_model_id: str
) -> List[dict]:
    """
    Adds a context note when model switches mid-conversation.
    Helps the new model understand what was discussed before.
    """
    if not messages:
        return messages

    # find last model used
    last_model = None
    for msg in reversed(messages):
        if msg.get("model_id") and msg["role"] == "assistant":
            last_model = msg["model_id"]
            break

    if last_model and last_model != current_model_id:
        note = {
            "role": "system",
            "content": (
                f"Context note: The previous messages were handled by the "
                f"{last_model} specialist. You are now the {current_model_id} "
                f"specialist. Maintain continuity with the conversation above."
            )
        }
        return messages + [note]

    return messages


async def build_smart_context(
    conversation_history: List[dict],
    current_model_id: str,
    system_prompt: str
) -> List[dict]:
    """
    Builds an optimized message array for the LLM call.
    
    Strategy:
    - 0-8 messages: full history
    - 9-15 messages: summarize older + keep last 6
    - 16+ messages: summarize all older + keep last 4
    
    Returns complete messages array ready for API call.
    """
    total = len(conversation_history)
    messages = [{"role": "system", "content": system_prompt}]

    # short conversation — send everything
    if total <= FULL_HISTORY_LIMIT:
        history = _add_model_context_note(
            conversation_history, current_model_id
        )
        for msg in history:
            messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })
        return messages

    # medium conversation — summarize older, keep last 6
    if total <= MEDIUM_THRESHOLD:
        recent_window = RECENT_WINDOW_MEDIUM
    else:
        # long conversation — summarize older, keep last 4
        recent_window = RECENT_WINDOW_LONG

    older_messages = conversation_history[:-recent_window]
    recent_messages = conversation_history[-recent_window:]

    # summarize older messages
    summary = await summarize_messages(older_messages)

    if summary:
        messages.append({
            "role": "system",
            "content": (
                f"The following is a summary of the earlier conversation "
                f"before the most recent messages:\n\n{summary}"
            )
        })

    # add recent messages with model context note
    recent_with_context = _add_model_context_note(
        recent_messages, current_model_id
    )
    for msg in recent_with_context:
        messages.append({
            "role": msg["role"],
            "content": msg["content"]
        })

    return messages


def estimate_token_count(messages: List[dict]) -> int:
    """
    Rough token estimate: ~4 chars per token.
    Used to decide if compression is needed.
    """
    total_chars = sum(len(msg.get("content", "")) for msg in messages)
    return total_chars // 4