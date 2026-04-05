from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import Response
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
from datetime import datetime
import asyncio
import httpx
import os
import json
import re

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


def format_datetime(dt_str: str) -> str:
    """Format ISO datetime to readable string."""
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return dt.strftime("%B %d, %Y at %I:%M %p UTC")
    except Exception:
        return dt_str


def strip_markdown_for_txt(text: str) -> str:
    """Strip markdown syntax for plain text export."""
    # remove code blocks (keep content)
    text = re.sub(r'```[\w]*\n', '', text)
    text = re.sub(r'```', '', text)
    # remove inline code
    text = re.sub(r'`([^`]+)`', r'\1', text)
    # remove headers (keep text)
    text = re.sub(r'#{1,6}\s+', '', text)
    # remove bold and italic (keep text)
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,3}([^_]+)_{1,3}', r'\1', text)
    # remove links (keep label)
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    # remove horizontal rules
    text = re.sub(r'\n---+\n', '\n', text)
    # clean up extra whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def build_safe_filename(title: str, ext: str) -> str:
    """Build a safe filename from conversation title."""
    safe = re.sub(r'[^\w\s-]', '', title)
    safe = re.sub(r'[\s]+', '_', safe.strip())
    safe = safe[:50]
    return f"prism_{safe}.{ext}"


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


# ═══════════════════════════════════════
# EXPORT ENDPOINT
# ═══════════════════════════════════════

@router.get("/conversations/{conversation_id}/export")
async def export_conversation(
    conversation_id: str,
    format: str = Query("md", regex="^(md|txt|json)$"),
    user_id: str = Depends(verify_token)
):
    """
    Export a conversation as Markdown, plain text, or JSON.
    Returns a downloadable file.
    """
    try:
        # verify ownership
        conv = get_conversation(conversation_id, user_id)
        if not conv:
            raise HTTPException(
                status_code=404,
                detail="Conversation not found"
            )

        messages = get_messages(conversation_id)
        if not messages:
            raise HTTPException(
                status_code=404,
                detail="No messages found in this conversation"
            )

        title = conv.get("title", "Conversation")
        created_at = conv.get("created_at", "")
        exported_at = datetime.utcnow().isoformat()
        message_count = len(messages)

        print(f"Exporting conversation '{title}' "
              f"as {format} ({message_count} messages)")

        # ── JSON ──────────────────────────────────────
        if format == "json":
            export_data = {
                "id": conversation_id,
                "title": title,
                "created_at": created_at,
                "exported_at": exported_at,
                "exported_by": "Prism AI Copilot",
                "message_count": message_count,
                "messages": [
                    {
                        "role": m["role"],
                        "content": m["content"],
                        "created_at": m.get("created_at", ""),
                        "routed_to": m.get("routed_to"),
                        "routing_reason": m.get("routing_reason"),
                        "search_used": m.get("search_used", False),
                        "search_query": m.get("search_query"),
                        "file_used": m.get("file_used", False),
                        "file_name": m.get("file_name")
                    }
                    for m in messages
                ]
            }

            content = json.dumps(export_data, indent=2, ensure_ascii=False)
            filename = build_safe_filename(title, "json")

            return Response(
                content=content.encode("utf-8"),
                media_type="application/json",
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"',
                    "Content-Length": str(len(content.encode("utf-8")))
                }
            )

        # ── MARKDOWN ───────────────────────────────────
        if format == "md":
            lines = []

            # header
            lines.append(f"# {title}")
            lines.append("")
            lines.append(f"> Exported from Prism AI Copilot")
            if created_at:
                lines.append(f"> Created: {format_datetime(created_at)}")
            lines.append(f"> Exported: {format_datetime(exported_at)}")
            lines.append(f"> Messages: {message_count}")
            lines.append("")
            lines.append("---")
            lines.append("")

            # messages
            for msg in messages:
                role = msg["role"]
                content_text = msg["content"]
                msg_time = msg.get("created_at", "")

                if role == "user":
                    lines.append("### You")
                else:
                    routed = msg.get("routed_to", "")
                    search = msg.get("search_used", False)
                    label = "### Prism"
                    meta_parts = []
                    if routed:
                        meta_parts.append(f"routed to {routed}")
                    if search:
                        meta_parts.append("web search used")
                    if meta_parts:
                        label += f" _{' · '.join(meta_parts)}_"
                    lines.append(label)

                if msg_time:
                    lines.append(
                        f"*{format_datetime(msg_time)}*"
                    )
                lines.append("")
                lines.append(content_text)
                lines.append("")
                lines.append("---")
                lines.append("")

            # footer
            lines.append(
                "_Exported from [Prism AI Copilot]"
                "(https://prism-frontend-three.vercel.app)_"
            )

            content = "\n".join(lines)
            filename = build_safe_filename(title, "md")

            return Response(
                content=content.encode("utf-8"),
                media_type="text/markdown",
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"',
                    "Content-Length": str(len(content.encode("utf-8")))
                }
            )

        # ── PLAIN TEXT ─────────────────────────────────
        if format == "txt":
            lines = []

            # header
            lines.append(title.upper())
            lines.append("=" * min(len(title), 60))
            lines.append("")
            lines.append("Exported from Prism AI Copilot")
            if created_at:
                lines.append(f"Created:  {format_datetime(created_at)}")
            lines.append(f"Exported: {format_datetime(exported_at)}")
            lines.append(f"Messages: {message_count}")
            lines.append("")
            lines.append("-" * 60)
            lines.append("")

            # messages
            for i, msg in enumerate(messages, 1):
                role = msg["role"]
                content_text = strip_markdown_for_txt(msg["content"])
                msg_time = msg.get("created_at", "")

                if role == "user":
                    lines.append("YOU:")
                else:
                    routed = msg.get("routed_to", "")
                    search = msg.get("search_used", False)
                    label = "PRISM:"
                    meta = []
                    if routed:
                        meta.append(f"routed to {routed}")
                    if search:
                        meta.append("web search")
                    if meta:
                        label += f" [{', '.join(meta)}]"
                    lines.append(label)

                if msg_time:
                    lines.append(f"[{format_datetime(msg_time)}]")

                lines.append("")
                lines.append(content_text)
                lines.append("")
                lines.append("-" * 60)
                lines.append("")

            # footer
            lines.append(
                "Exported from Prism AI Copilot — "
                "https://prism-frontend-three.vercel.app"
            )

            content = "\n".join(lines)
            filename = build_safe_filename(title, "txt")

            return Response(
                content=content.encode("utf-8"),
                media_type="text/plain",
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"',
                    "Content-Length": str(len(content.encode("utf-8")))
                }
            )

    except HTTPException:
        raise
    except Exception as e:
        print(f"Export error: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════
# BRANCH ENDPOINT
# ═══════════════════════════════════════

class BranchConversationRequest(BaseModel):
    message_index: int  # branch from this message index (inclusive)


@router.post("/conversations/{conversation_id}/branch")
async def branch_conversation(
    conversation_id: str,
    request: BranchConversationRequest,
    user_id: str = Depends(verify_token)
):
    """
    Creates a new conversation branched from
    an existing one up to a specific message index.
    """
    try:
        client = get_supabase()

        # verify ownership
        conv = get_conversation(conversation_id, user_id)
        if not conv:
            raise HTTPException(
                status_code=404,
                detail="Conversation not found"
            )

        # get all messages
        messages = get_messages(conversation_id)
        if not messages:
            raise HTTPException(
                status_code=404,
                detail="No messages found"
            )

        # validate message index
        if request.message_index < 0 or \
           request.message_index >= len(messages):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid message index. "
                       f"Valid range: 0-{len(messages)-1}"
            )

        # slice messages up to branch point (inclusive)
        branch_messages = messages[:request.message_index + 1]
        branch_point_msg = messages[request.message_index]

        original_title = conv.get("title", "Conversation")
        branch_title = f"Branch: {original_title}"

        print(f"Branching '{original_title}' "
              f"at message {request.message_index} "
              f"({len(branch_messages)} messages)")

        # create new conversation
        new_conv = client.table("conversations").insert({
            "user_id": user_id,
            "title": branch_title,
            "model_id": conv.get("model_id", "auto"),
            "parent_conversation_id": conversation_id,
            "branch_point_message_id": branch_point_msg.get("id"),
            "is_branch": True
        }).execute()

        if not new_conv.data:
            raise HTTPException(
                status_code=500,
                detail="Failed to create branch conversation"
            )

        new_conv_id = new_conv.data[0]["id"]

        # copy messages to new conversation
        for msg in branch_messages:
            client.table("messages").insert({
                "conversation_id": new_conv_id,
                "role": msg["role"],
                "content": msg["content"],
                "model_id": msg.get("model_id"),
                "routed_to": msg.get("routed_to"),
                "routing_reason": msg.get("routing_reason"),
                "search_used": msg.get("search_used", False),
                "search_query": msg.get("search_query"),
                "file_used": msg.get("file_used", False),
                "file_name": msg.get("file_name")
            }).execute()

        print(f"Branch created: {new_conv_id} "
              f"with {len(branch_messages)} messages")

        return {
            "success": True,
            "branch_conversation_id": new_conv_id,
            "branch_title": branch_title,
            "message_count": len(branch_messages),
            "parent_conversation_id": conversation_id
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Branch error: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversations/{conversation_id}/branches")
async def get_conversation_branches(
    conversation_id: str,
    user_id: str = Depends(verify_token)
):
    """
    Returns all branches of a conversation.
    """
    try:
        client = get_supabase()

        # verify ownership
        conv = get_conversation(conversation_id, user_id)
        if not conv:
            raise HTTPException(
                status_code=404,
                detail="Conversation not found"
            )

        response = (
            client.table("conversations")
            .select("id, title, created_at, updated_at, "
                    "is_branch, branch_point_message_id")
            .eq("parent_conversation_id", conversation_id)
            .eq("user_id", user_id)
            .order("created_at", desc=False)
            .execute()
        )

        return response.data or []

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))








# ═══════════════════════════════════════
# EXISTING ENDPOINTS (unchanged)
# ═══════════════════════════════════════

@router.get("/search")
async def search_conversations(
    q: str = Query(..., min_length=1),
    user_id: str = Depends(verify_token)
):
    try:
        if not q or not q.strip():
            return []

        query = q.strip().lower()
        client = get_supabase()

        title_results = (
            client.table("conversations")
            .select("id, title, created_at, updated_at")
            .eq("user_id", user_id)
            .ilike("title", f"%{query}%")
            .order("updated_at", desc=True)
            .limit(5)
            .execute()
        )

        message_results = (
            client.table("messages")
            .select("id, conversation_id, role, content, created_at")
            .ilike("content", f"%{query}%")
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )

        conv_snippets: dict = {}
        for msg in (message_results.data or []):
            conv_id = msg["conversation_id"]
            if conv_id not in conv_snippets:
                content = msg["content"]
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

        seen_ids = set()
        final_results = []

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
            raise HTTPException(
                status_code=404,
                detail="Conversation not found"
            )
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

            if len(all_messages) % 4 == 0:
                from routes.scores import score_conversation
                asyncio.create_task(
                    score_conversation(
                        conversation_id=request.conversation_id,
                        user_id=user_id,
                        messages=[
                            {"role": m["role"], "content": m["content"]}
                            for m in all_messages
                        ]
                    )
                )

            if len(all_messages) % 4 == 0:
                from routes.suggestions import store_conversation_embedding
                asyncio.create_task(
                    store_conversation_embedding(
                        conversation_id=request.conversation_id,
                        user_id=user_id,
                        messages=[
                            {"role": m["role"], "content": m["content"]}
                            for m in all_messages
                        ]
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