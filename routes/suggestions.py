import os
import json
import httpx
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from db.supabase import get_supabase
from db.auth import verify_token

router = APIRouter()

OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"
EMBEDDING_MODEL = "text-embedding-3-small"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
SUMMARY_MODEL = "openai/gpt-4o-mini"


class SuggestionsRequest(BaseModel):
    text: str
    limit: Optional[int] = 3


async def generate_embedding(text: str) -> Optional[List[float]]:
    try:
        headers = {
            "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": EMBEDDING_MODEL,
            "input": text[:2000],
            "encoding_format": "float"
        }
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                OPENAI_EMBEDDINGS_URL,
                json=payload,
                headers=headers
            )
        if response.status_code != 200:
            print(f"Embedding API error: {response.status_code} {response.text}")
            return None
        data = response.json()
        return data["data"][0]["embedding"]
    except Exception as e:
        print(f"Embedding generation error: {e}")
        return None


async def generate_conversation_summary(messages: List[dict]) -> str:
    try:
        if not messages:
            return ""
        sample = messages[:6]
        conv_text = "\n".join([
            f"{m['role'].upper()}: {m['content'][:200]}"
            for m in sample
        ])
        headers = {
            "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/prism-ai",
            "X-Title": "Prism"
        }
        payload = {
            "model": SUMMARY_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": "Summarize this conversation in 1-2 sentences. Focus on the main topic and what was accomplished. Be specific and technical. Return ONLY the summary, nothing else."
                },
                {"role": "user", "content": conv_text}
            ],
            "temperature": 0,
            "max_tokens": 100
        }
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                OPENROUTER_API_URL,
                json=payload,
                headers=headers
            )
        if response.status_code != 200:
            first_user = next(
                (m["content"][:200] for m in messages if m["role"] == "user"), ""
            )
            return first_user
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"Summary generation error: {e}")
        first_user = next(
            (m["content"][:200] for m in messages if m["role"] == "user"), ""
        )
        return first_user


async def store_conversation_embedding(
    conversation_id: str,
    user_id: str,
    messages: List[dict]
) -> None:
    try:
        if not messages or len(messages) < 2:
            return
        summary = await generate_conversation_summary(messages)
        if not summary:
            return
        embedding = await generate_embedding(summary)
        if not embedding:
            return
        client = get_supabase()
        existing = (
            client.table("conversation_embeddings")
            .select("id")
            .eq("conversation_id", conversation_id)
            .execute()
        )
        if existing.data:
            client.table("conversation_embeddings").update({
                "embedding": embedding,
                "content_summary": summary,
                "updated_at": "now()"
            }).eq("conversation_id", conversation_id).execute()
        else:
            client.table("conversation_embeddings").insert({
                "conversation_id": conversation_id,
                "user_id": user_id,
                "embedding": embedding,
                "content_summary": summary
            }).execute()
        print(f"Stored embedding for conversation {conversation_id}")
    except Exception as e:
        print(f"Store embedding error: {type(e).__name__}: {e}")


# ═══════════════════════════════════════
# API ENDPOINTS
# ═══════════════════════════════════════

@router.post("/suggestions")
async def get_suggestions(
    request: SuggestionsRequest,
    user_id: str = Depends(verify_token)
):
    try:
        text = request.text.strip()
        if len(text.split()) < 3:
            return []

        query_embedding = await generate_embedding(text)
        if not query_embedding:
            return []

        client = get_supabase()

        try:
            results = client.rpc(
                "match_conversation_embeddings",
                {
                    "query_embedding": query_embedding,
                    "match_user_id": user_id,
                    "match_threshold": 0.4,
                    "match_count": request.limit or 3
                }
            ).execute()

            if not results.data:
                print(f"No vector matches found, falling back to text search")
                return await _fallback_text_search(text, user_id, request.limit or 3)

            suggestions = []
            for match in results.data:
                conv = (
                    client.table("conversations")
                    .select("id, title, updated_at")
                    .eq("id", match["conversation_id"])
                    .eq("user_id", user_id)
                    .execute()
                )
                if conv.data:
                    suggestions.append({
                        "conversation_id": match["conversation_id"],
                        "title": conv.data[0]["title"],
                        "similarity": round(match["similarity"], 3),
                        "content_summary": match["content_summary"],
                        "updated_at": conv.data[0]["updated_at"]
                    })

            print(f"Vector search returned {len(suggestions)} suggestions")
            return suggestions

        except Exception as rpc_error:
            print(f"RPC error: {rpc_error}")
            return await _fallback_text_search(text, user_id, request.limit or 3)

    except Exception as e:
        print(f"Suggestions error: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _fallback_text_search(
    text: str,
    user_id: str,
    limit: int
) -> List[dict]:
    try:
        client = get_supabase()
        words = [w for w in text.split() if len(w) > 3][:3]
        if not words:
            return []

        results = []
        seen_ids = set()

        for word in words:
            conv_results = (
                client.table("conversations")
                .select("id, title, updated_at")
                .eq("user_id", user_id)
                .ilike("title", f"%{word}%")
                .order("updated_at", desc=True)
                .limit(limit)
                .execute()
            )
            for conv in (conv_results.data or []):
                if conv["id"] not in seen_ids:
                    seen_ids.add(conv["id"])
                    results.append({
                        "conversation_id": conv["id"],
                        "title": conv["title"],
                        "similarity": 0.7,
                        "content_summary": conv["title"],
                        "updated_at": conv["updated_at"]
                    })

        print(f"Fallback text search returned {len(results)} results")
        return results[:limit]

    except Exception as e:
        print(f"Fallback search error: {e}")
        return []


@router.post("/suggestions/embed-all")
async def embed_all_conversations(
    user_id: str = Depends(verify_token)
):
    """
    Bulk embed all existing conversations for a user.
    Run once to backfill embeddings for existing conversations.
    """
    try:
        from db.messages import get_messages
        client = get_supabase()

        conversations = (
            client.table("conversations")
            .select("id, title")
            .eq("user_id", user_id)
            .order("updated_at", desc=True)
            .limit(50)
            .execute()
        )

        if not conversations.data:
            return {"success": True, "embedded": 0, "total": 0}

        embedded = 0
        failed = 0

        for conv in conversations.data:
            try:
                messages = get_messages(conv["id"])
                if len(messages) < 2:
                    continue

                await store_conversation_embedding(
                    conversation_id=conv["id"],
                    user_id=user_id,
                    messages=[
                        {"role": m["role"], "content": m["content"]}
                        for m in messages
                    ]
                )
                embedded += 1
                print(f"Embedded [{embedded}]: {conv['title']}")

            except Exception as e:
                failed += 1
                print(f"Failed to embed {conv['id']}: {e}")
                continue

        print(f"Bulk embed complete: {embedded} embedded, {failed} failed")
        return {
            "success": True,
            "embedded": embedded,
            "failed": failed,
            "total": len(conversations.data)
        }

    except Exception as e:
        print(f"Bulk embed error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/suggestions/embed-conversation")
async def embed_conversation(
    conversation_id: str,
    user_id: str = Depends(verify_token)
):
    try:
        from db.messages import get_messages
        messages = get_messages(conversation_id)

        if not messages:
            raise HTTPException(status_code=404, detail="No messages found")

        await store_conversation_embedding(
            conversation_id=conversation_id,
            user_id=user_id,
            messages=[
                {"role": m["role"], "content": m["content"]}
                for m in messages
            ]
        )

        return {"success": True, "message": "Embedding generated"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))