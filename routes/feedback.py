import os
import asyncio
import traceback
import httpx
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from db.supabase import get_supabase
from db.auth import verify_token

router = APIRouter()

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
FEEDBACK_MODEL = "openai/gpt-4o-mini"

PROMPT_EVOLUTION_SYSTEM = """
You are a prompt optimization expert for Prism, an AI copilot.

Your job is to analyze user feedback on AI responses and update their 
custom instructions to make future responses better match their preferences.

You will receive:
1. The user's current custom instructions
2. A list of recent feedback (thumbs up/down + optional text)

Your task:
- Identify patterns in what the user likes and dislikes
- Update the custom instructions to reflect these preferences
- Keep instructions concise (max 300 words)
- Be specific about formatting, tone, depth, style preferences
- Preserve any existing preferences that aren't contradicted by feedback
- Don't make the instructions too rigid — allow natural variation

Return ONLY the updated custom instructions text.
No explanations, no headers, just the instructions themselves.
""".strip()


class FeedbackRequest(BaseModel):
    conversation_id: str
    message_id: Optional[str] = None
    message_content: str
    rating: int
    feedback_text: Optional[str] = None


async def evolve_user_prompt(user_id: str) -> None:
    """
    Analyzes recent feedback and evolves the user's custom instructions.
    Runs in background after every 3rd feedback submission.
    """
    try:
        print(f"Starting prompt evolution for user {user_id}")
        client = get_supabase()

        feedback_response = (
            client.table("message_feedback")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(10)
            .execute()
        )

        feedback_list = feedback_response.data or []
        if len(feedback_list) < 2:
            print(f"Not enough feedback to evolve: {len(feedback_list)}")
            return

        profile_response = (
            client.table("user_profiles")
            .select("custom_instructions")
            .eq("user_id", user_id)
            .execute()
        )

        current_instructions = ""
        if profile_response.data:
            current_instructions = profile_response.data[0].get(
                "custom_instructions", ""
            ) or ""

        feedback_summary = []
        for fb in feedback_list:
            rating_str = "👍 LIKED" if fb["rating"] == 1 else "👎 DISLIKED"
            entry = rating_str
            if fb.get("feedback_text"):
                entry += f": {fb['feedback_text']}"
            if fb.get("message_content"):
                entry += f"\nResponse preview: {fb['message_content'][:200]}..."
            feedback_summary.append(entry)

        feedback_text = "\n\n".join(feedback_summary)

        prompt = f"""Current custom instructions:
{current_instructions or 'None set yet.'}

Recent user feedback on AI responses:
{feedback_text}

Based on this feedback, write updated custom instructions that will 
make future responses better match this user's preferences."""

        headers = {
            "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/prism-ai",
            "X-Title": "Prism"
        }

        payload = {
            "model": FEEDBACK_MODEL,
            "messages": [
                {"role": "system", "content": PROMPT_EVOLUTION_SYSTEM},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 400
        }

        async with httpx.AsyncClient(timeout=15) as http_client:
            response = await http_client.post(
                OPENROUTER_API_URL,
                json=payload,
                headers=headers
            )

        if response.status_code != 200:
            print(f"Prompt evolution API error: {response.status_code}")
            return

        data = response.json()
        new_instructions = data["choices"][0]["message"]["content"].strip()

        if not new_instructions:
            print("Empty instructions returned")
            return

        print(f"Evolved instructions: {new_instructions[:100]}...")

        existing = (
            client.table("user_profiles")
            .select("id")
            .eq("user_id", user_id)
            .execute()
        )

        if existing.data:
            client.table("user_profiles").update({
                "custom_instructions": new_instructions
            }).eq("user_id", user_id).execute()
        else:
            client.table("user_profiles").insert({
                "user_id": user_id,
                "custom_instructions": new_instructions
            }).execute()

        print(f"Profile updated for user {user_id}")

    except Exception as e:
        print(f"Prompt evolution error: {type(e).__name__}: {e}")
        traceback.print_exc()


@router.post("/feedback")
async def submit_feedback(
    request: FeedbackRequest,
    user_id: str = Depends(verify_token)
):
    try:
        print(f"Feedback received: user={user_id}, rating={request.rating}, conv={request.conversation_id}")

        if request.rating not in (1, -1):
            raise HTTPException(
                status_code=400,
                detail="Rating must be 1 (thumbs up) or -1 (thumbs down)"
            )

        client = get_supabase()

        # validate conversation_id is a valid UUID format
        import uuid
        try:
            uuid.UUID(str(request.conversation_id))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid conversation_id format: {request.conversation_id}"
            )

        insert_data = {
            "user_id": user_id,
            "conversation_id": request.conversation_id,
            "message_content": request.message_content[:500] if request.message_content else "",
            "rating": request.rating,
        }

        # only add optional fields if they have values
        if request.message_id:
            try:
                uuid.UUID(str(request.message_id))
                insert_data["message_id"] = request.message_id
            except ValueError:
                print(f"Invalid message_id, skipping: {request.message_id}")

        if request.feedback_text:
            insert_data["feedback_text"] = request.feedback_text

        print(f"Inserting feedback: {insert_data}")

        result = client.table("message_feedback").insert(insert_data).execute()
        print(f"Feedback insert result: {result.data}")

        # count total feedback
        count_response = (
            client.table("message_feedback")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .execute()
        )

        total_feedback = count_response.count or 0
        print(f"Total feedback for user: {total_feedback}")

        # evolve prompt every 3rd feedback
        if total_feedback % 3 == 0:
            asyncio.create_task(evolve_user_prompt(user_id))
            return {
                "success": True,
                "message": "Feedback saved. Updating your preferences...",
                "evolving": True
            }

        return {
            "success": True,
            "message": "Feedback saved",
            "evolving": False
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Feedback error: {type(e).__name__}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/feedback/stats")
async def get_feedback_stats(user_id: str = Depends(verify_token)):
    try:
        client = get_supabase()

        response = (
            client.table("message_feedback")
            .select("rating, feedback_text, created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )

        feedback = response.data or []
        thumbs_up = sum(1 for f in feedback if f["rating"] == 1)
        thumbs_down = sum(1 for f in feedback if f["rating"] == -1)

        return {
            "total": len(feedback),
            "thumbs_up": thumbs_up,
            "thumbs_down": thumbs_down,
            "recent": feedback[:5]
        }

    except Exception as e:
        print(f"Feedback stats error: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=str(e))