import os
import json
import httpx
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from db.supabase import get_supabase
from db.auth import verify_token

router = APIRouter()

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
MEMORY_MODEL = "openai/gpt-4o-mini"

MEMORY_EXTRACTION_PROMPT = """
You are a memory extraction system for Prism, an AI copilot.

Analyze the conversation and extract important facts about the user that would be useful to remember in future conversations.

Extract memories in these categories:
- personal: name, location, job, company, role
- technical: programming languages, tools, frameworks, expertise level
- preferences: how they like responses, communication style, pet peeves
- projects: what they are working on, their goals
- context: important background information

Rules:
- Only extract clear, factual information explicitly stated by the user
- Do NOT extract things the assistant said
- Do NOT extract temporary or one-time things
- Each memory should be a single, concise sentence
- Importance: 1=minor, 2=useful, 3=important, 4=very important, 5=critical
- Maximum 5 memories per conversation
- If nothing worth remembering, return empty array

Respond ONLY with a valid JSON array:
[
  {
    "memory": "User is an AI engineer at Indegene",
    "category": "personal",
    "importance": 4
  }
]

Return [] if nothing worth remembering.
""".strip()

MEMORY_INJECTION_PROMPT = """
--- MEMORY: WHAT PRISM KNOWS ABOUT YOU ---
{memories}
--- END OF MEMORY ---
"""


async def extract_memories_from_conversation(
    messages: List[dict],
    conversation_id: str,
    user_id: str
) -> List[dict]:
    """
    Uses GPT-4o-mini to extract memorable facts from a conversation.
    Saves them to the user_memories table.
    """
    if not messages or len(messages) < 2:
        return []

    # format conversation for extraction
    conversation_text = "\n".join([
        f"{msg['role'].upper()}: {msg['content'][:300]}"
        for msg in messages
        if msg['role'] in ['user', 'assistant']
    ])

    headers = {
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/prism-ai",
        "X-Title": "Prism"
    }

    payload = {
        "model": MEMORY_MODEL,
        "messages": [
            {"role": "system", "content": MEMORY_EXTRACTION_PROMPT},
            {"role": "user", "content": f"Extract memories from:\n\n{conversation_text}"}
        ],
        "temperature": 0,
        "max_tokens": 500
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                OPENROUTER_API_URL,
                json=payload,
                headers=headers
            )

        if response.status_code != 200:
            return []

        data = response.json()
        content = data["choices"][0]["message"]["content"].strip()
        content = content.replace("```json", "").replace("```", "").strip()

        memories = json.loads(content)
        if not isinstance(memories, list):
            return []

        # save to database
        if memories:
            client_db = get_supabase()
            for mem in memories:
                if not mem.get("memory"):
                    continue
                client_db.table("user_memories").insert({
                    "user_id": user_id,
                    "memory": mem["memory"],
                    "category": mem.get("category", "general"),
                    "importance": mem.get("importance", 1),
                    "source_conversation_id": conversation_id
                }).execute()

        return memories

    except Exception as e:
        print(f"Memory extraction error: {e}")
        return []


async def get_user_memories(user_id: str, limit: int = 20) -> List[dict]:
    """
    Fetches the most important memories for a user.
    """
    try:
        client = get_supabase()
        response = (
            client.table("user_memories")
            .select("*")
            .eq("user_id", user_id)
            .order("importance", desc=True)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return response.data or []
    except Exception:
        return []


def build_memory_context(memories: List[dict]) -> str:
    """
    Formats memories into a context string for injection.
    """
    if not memories:
        return ""

    memory_lines = []
    for mem in memories:
        category = mem.get("category", "general").upper()
        memory = mem.get("memory", "")
        if memory:
            memory_lines.append(f"[{category}] {memory}")

    if not memory_lines:
        return ""

    return MEMORY_INJECTION_PROMPT.format(
        memories="\n".join(memory_lines)
    )


# API endpoints

class MemoryItem(BaseModel):
    memory: str
    category: Optional[str] = "general"
    importance: Optional[int] = 1


class ExtractMemoriesRequest(BaseModel):
    conversation_id: str
    messages: List[dict]


@router.get("/memories")
async def list_memories(user_id: str = Depends(verify_token)):
    try:
        memories = await get_user_memories(user_id)
        return memories
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/memories/{memory_id}")
async def delete_memory(
    memory_id: str,
    user_id: str = Depends(verify_token)
):
    try:
        client = get_supabase()
        client.table("user_memories").delete().eq(
            "id", memory_id
        ).eq("user_id", user_id).execute()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/memories/extract")
async def extract_memories(
    request: ExtractMemoriesRequest,
    user_id: str = Depends(verify_token)
):
    try:
        memories = await extract_memories_from_conversation(
            request.messages,
            request.conversation_id,
            user_id
        )
        return {"extracted": len(memories), "memories": memories}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))