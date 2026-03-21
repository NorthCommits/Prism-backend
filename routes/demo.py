import os
import json
import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List

router = APIRouter()

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# simple in-memory rate limiter per IP
# resets on server restart — good enough for demo
demo_usage: dict = {}
MAX_DEMO_MESSAGES = 3

DEMO_SYSTEM_PROMPT = """
You are Prism, an intelligent AI copilot.

You are Prism — a personal AI assistant with these capabilities:
- Smart model routing: auto-selects the best AI model for every task
- Live web search: real-time information from the internet
- Code execution: run Python, JavaScript, Bash in a secure sandbox
- Image vision: analyze and understand uploaded images
- Image generation: create images with DALL-E 3
- Cross-conversation memory: learns and remembers who you are
- Multi-step agent mode: breaks complex tasks into steps automatically
- Prompt templates: slash commands for common tasks
- Preference evolution: adapts to your feedback over time

You are currently running in demo mode on the Prism landing page.
The user has not signed up yet — they are exploring Prism for the first time.

Rules:
- Keep every response to 3-4 sentences maximum
- Be impressive, smart and friendly
- Showcase what makes Prism unique when relevant
- If asked what you are, explain you are Prism the AI copilot
- If asked about capabilities, highlight the most impressive ones
- End responses with a subtle hint to sign up if appropriate
- NEVER confuse yourself with any other product called Prism
- NEVER mention real estate, videos, or marketing tools
""".strip()


class DemoMessage(BaseModel):
    message: str
    history: Optional[List[dict]] = []


async def stream_demo_response(messages: list, metadata: dict):
    """Stream response tokens from OpenRouter."""
    headers = {
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/prism-ai",
        "X-Title": "Prism"
    }

    payload = {
        "model": "openai/gpt-4o-mini",
        "messages": messages,
        "stream": True,
        "max_tokens": 200
    }

    yield f"data: {json.dumps({'type': 'metadata', **metadata})}\n\n"

    async with httpx.AsyncClient(timeout=30) as client:
        async with client.stream(
            "POST",
            OPENROUTER_API_URL,
            json=payload,
            headers=headers
        ) as response:
            if response.status_code != 200:
                error = await response.aread()
                print(f"Demo API error: {response.status_code} {error.decode()}")
                yield f"data: {json.dumps({'type': 'error', 'message': 'Something went wrong. Please try again.'})}\n\n"
                return

            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        yield f"data: {json.dumps({'type': 'done'})}\n\n"
                        return
                    try:
                        chunk = json.loads(data)
                        delta = chunk["choices"][0]["delta"]
                        if "content" in delta and delta["content"]:
                            yield f"data: {json.dumps({'type': 'token', 'content': delta['content']})}\n\n"
                    except Exception:
                        continue

    yield f"data: {json.dumps({'type': 'done'})}\n\n"


@router.post("/demo/chat")
async def demo_chat(request: Request, body: DemoMessage):
    """
    Public demo endpoint — no auth required.
    Rate limited to MAX_DEMO_MESSAGES per IP.
    Text only — no web search, code execution, or image generation.
    """
    # get client IP
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    client_ip = forwarded_for.split(",")[0].strip() if forwarded_for else ""
    if not client_ip:
        client_ip = request.client.host if request.client else "unknown"

    print(f"Demo request from IP: {client_ip}")

    # check rate limit
    current_count = demo_usage.get(client_ip, 0)
    if current_count >= MAX_DEMO_MESSAGES:
        raise HTTPException(
            status_code=429,
            detail={
                "message": "Demo limit reached",
                "limit_reached": True,
                "max_messages": MAX_DEMO_MESSAGES
            }
        )

    # validate message
    if not body.message or not body.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    message = body.message.strip()[:500]

    # increment usage BEFORE responding
    demo_usage[client_ip] = current_count + 1
    messages_remaining = MAX_DEMO_MESSAGES - demo_usage[client_ip]

    print(f"Demo usage: {demo_usage[client_ip]}/{MAX_DEMO_MESSAGES} for {client_ip}")

    # build messages array
    messages = [{"role": "system", "content": DEMO_SYSTEM_PROMPT}]

    # add conversation history (max last 4 messages for context)
    for msg in (body.history or [])[-4:]:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({
                "role": role,
                "content": content[:300]
            })

    # add current user message
    messages.append({"role": "user", "content": message})

    metadata = {
        "model_name": "Prism Demo",
        "routed_to": "writing",
        "search_used": False,
        "messages_remaining": messages_remaining,
        "limit_reached": messages_remaining <= 0
    }

    return StreamingResponse(
        stream_demo_response(messages, metadata),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.get("/demo/status")
async def demo_status(request: Request):
    """Check how many demo messages this IP has used."""
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    client_ip = forwarded_for.split(",")[0].strip() if forwarded_for else ""
    if not client_ip:
        client_ip = request.client.host if request.client else "unknown"

    used = demo_usage.get(client_ip, 0)
    remaining = max(0, MAX_DEMO_MESSAGES - used)

    return {
        "used": used,
        "remaining": remaining,
        "limit_reached": used >= MAX_DEMO_MESSAGES,
        "max_messages": MAX_DEMO_MESSAGES
    }