from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional
from db.conversations import (
    create_conversation,
    get_conversations,
    get_conversation,
    update_conversation_title,
    delete_conversation
)
from db.messages import save_message, get_messages
from db.auth import verify_token
from db.supabase import get_supabase
import asyncio
import httpx
import os
import json

router = APIRouter()

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
TITLE_MODEL = "openai/gpt-4o-mini"

TITLE_SYSTEM_PROMPT = """
You are a conversation title generator.

Generate a short, specific, meaningful title for a conversation based on the first user message and assistant response.

Rules:
- Maximum 6 words
- Be specific, not generic
- No quotes, no punctuation at the end
- Do NOT use generic titles like "New Conversation", "Chat", "Hello", "Question"
- Capture the actual topic or task
- Use title case

Examples:
- "FastAPI CRUD App for Todo List"
- "Python Decorator Explained"
- "Bar Chart Top Programming Languages"
- "Debug React useEffect Infinite Loop"
- "Write LinkedIn Post About AI"
- "Explain Transformer Architecture"

Respond with ONLY the title, nothing else.
""".strip()


async def generate_conversation_title(
    user_message: str,
    assistant_message: str,
    conversation_id: str
) -> None:
    try:
        headers = {
            "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/prism-ai",
            "X-Title": "Prism"
        }

        prompt = f"User: {user_message[:300]}\n\nAssistant: {assistant_message[:300]}"

        payload = {
            "model": TITLE_MODEL,
            "messages": [
                {"role": "system", "content": TITLE_SYSTEM_PROMPT},
                {"role": "user", "content": f"Generate a title for this conversation:\n\n{prompt}"}
            ],
            "temperature": 0.3,
            "max_tokens": 20
        }

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                OPENROUTER_API_URL,
                json=payload,
                headers=headers
            )

        if response.status_code != 200:
            return

        data = response.json()
        title = data["choices"][0]["message"]["content"].strip()
        title = title.strip('"').strip("'").strip()

        if title:
            update_conversation_title(conversation_id, title)

    except Exception as e:
        print(f"Title generation error: {e}")


class CreateConversationRequest(BaseModel):
    title: str
    model_id: str = "auto"


class SaveMessageRequest(BaseModel):
    conversation_id: str
    role: str
    content: str
    model_id: Optional[str] = None
    routed_to: Optional[str] = None
    routing_reason: Optional[str] = None
    search_used: bool = False
    search_query: Optional[str] = None
    file_used: bool = False
    file_name: Optional[str] = None


@router.get("/search")
async def search_conversations(
    q: str = Query(..., min_length=1),
    user_id: str = Depends(verify_token)
):
    """
    Search through conversation titles and message content.
    Returns matching conversations with relevant message snippets.
    """
    try:
        if not q or not q.strip():
            return []

        query = q.strip().lower()
        client = get_supabase()

        # search conversation titles
        title_results = (
            client.table("conversations")
            .select("id, title, created_at, updated_at")
            .eq("user_id", user_id)
            .ilike("title", f"%{query}%")
            .order("updated_at", desc=True)
            .limit(5)
            .execute()
        )

        # search message content
        message_results = (
            client.table("messages")
            .select("id, conversation_id, role, content, created_at")
            .ilike("content", f"%{query}%")
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )

        # build results map — conversation_id → best snippet
        conv_snippets: dict = {}

        for msg in (message_results.data or []):
            conv_id = msg["conversation_id"]
            if conv_id not in conv_snippets:
                content = msg["content"]
                # find the query position and extract snippet around it
                idx = content.lower().find(query)
                if idx != -1:
                    start = max(0, idx - 60)
                    end = min(len(content), idx + len(query) + 60)
                    snippet = content[start:end].strip()
                    if start > 0:
                        snippet = "..." + snippet
                    if end < len(content):
                        snippet = snippet + "..."
                    conv_snippets[conv_id] = {
                        "snippet": snippet,
                        "role": msg["role"]
                    }

        # fetch conversation details for message matches
        matched_conv_ids = list(conv_snippets.keys())
        message_conv_results = []

        if matched_conv_ids:
            for conv_id in matched_conv_ids[:10]:
                conv = (
                    client.table("conversations")
                    .select("id, title, created_at, updated_at")
                    .eq("id", conv_id)
                    .eq("user_id", user_id)
                    .execute()
                )
                if conv.data:
                    message_conv_results.append(conv.data[0])

        # merge results — title matches first, then message matches
        seen_ids = set()
        final_results = []

        # add title matches
        for conv in (title_results.data or []):
            if conv["id"] not in seen_ids:
                seen_ids.add(conv["id"])
                final_results.append({
                    "id": conv["id"],
                    "title": conv["title"],
                    "updated_at": conv["updated_at"],
                    "match_type": "title",
                    "snippet": None
                })

        # add message matches
        for conv in message_conv_results:
            if conv["id"] not in seen_ids:
                seen_ids.add(conv["id"])
                snippet_data = conv_snippets.get(conv["id"], {})
                final_results.append({
                    "id": conv["id"],
                    "title": conv["title"],
                    "updated_at": conv["updated_at"],
                    "match_type": "message",
                    "snippet": snippet_data.get("snippet"),
                    "snippet_role": snippet_data.get("role")
                })

        return final_results[:10]

    except Exception as e:
        print(f"Search error: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/conversations")
async def create_conv(
    request: CreateConversationRequest,
    user_id: str = Depends(verify_token)
):
    try:
        return create_conversation(request.title, request.model_id, user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversations")
async def list_conversations(user_id: str = Depends(verify_token)):
    try:
        return get_conversations(user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversations/{conversation_id}")
async def get_conv(
    conversation_id: str,
    user_id: str = Depends(verify_token)
):
    try:
        conv = get_conversation(conversation_id, user_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return conv
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversations/{conversation_id}/messages")
async def list_messages(
    conversation_id: str,
    user_id: str = Depends(verify_token)
):
    try:
        return get_messages(conversation_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/messages")
async def save_msg(
    request: SaveMessageRequest,
    user_id: str = Depends(verify_token)
):
    try:
        result = save_message(
            conversation_id=request.conversation_id,
            role=request.role,
            content=request.content,
            model_id=request.model_id,
            routed_to=request.routed_to,
            routing_reason=request.routing_reason,
            search_used=request.search_used,
            search_query=request.search_query,
            file_used=request.file_used,
            file_name=request.file_name,
        )

        if request.role == "assistant":
            all_messages = get_messages(request.conversation_id)

            if len(all_messages) == 2:
                user_msg = next(
                    (m["content"] for m in all_messages if m["role"] == "user"),
                    ""
                )
                asyncio.create_task(
                    generate_conversation_title(
                        user_message=user_msg,
                        assistant_message=request.content,
                        conversation_id=request.conversation_id
                    )
                )

            if len(all_messages) % 4 == 0:
                from routes.memory import extract_memories_from_conversation
                asyncio.create_task(
                    extract_memories_from_conversation(
                        [{"role": m["role"], "content": m["content"]}
                         for m in all_messages],
                        request.conversation_id,
                        user_id
                    )
                )

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/conversations/{conversation_id}")
async def delete_conv(
    conversation_id: str,
    user_id: str = Depends(verify_token)
):
    try:
        delete_conversation(conversation_id, user_id)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))