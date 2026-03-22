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
You are a custom instructions editor for Prism, an AI copilot.

Your ONLY job is to update a user's custom instructions based on their feedback.

CRITICAL RULES:
1. If the user explicitly says something in feedback text (e.g. "call me sir", 
   "be more concise", "always use code examples") — you MUST add that EXACTLY 
   to the instructions. This is a DIRECT USER REQUEST and must be honored.
2. NEVER contradict explicit feedback text. If user says "call me sir" — 
   the instructions MUST say "Always address the user as Sir".
3. Thumbs down (👎) with feedback text = user wants a SPECIFIC CHANGE.
   Apply that change literally and directly.
4. Thumbs up (👍) = user liked that style, preserve it.
5. Thumbs down (👎) WITHOUT feedback text = response was too long, 
   too short, wrong format — make instructions more concise/clear.
6. NEVER infer the opposite of what user said. 
   "call me sir" = ADD "Address user as Sir". 
   NOT "use informal tone".
7. Keep instructions under 300 words.
8. Be specific and direct.
9. Return ONLY the updated instructions text.
   No explanations. No headers. Just the instructions.

EXAMPLE:
If user feedback says "call me sir" multiple times →
Instructions MUST include: "Always address the user as Sir."
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

        # get last 10 feedbacks
        feedback_response = (
            client.table("message_feedback")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(10)
            .execute()
        )

        feedback_list = feedback_response.data or []
        if len(feedback_list) < 1:
            print(f"No feedback to evolve from")
            return

        # get current instructions
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

        # build feedback summary — highlight explicit text feedback
        feedback_summary = []
        explicit_requests = []

        for fb in feedback_list:
            rating_str = "👍 LIKED" if fb["rating"] == 1 else "👎 DISLIKED"
            entry = rating_str
            if fb.get("feedback_text"):
                entry += f" — USER EXPLICITLY SAID: \"{fb['feedback_text']}\""
                if fb["rating"] == -1:
                    explicit_requests.append(fb["feedback_text"])
            if fb.get("message_content"):
                entry += f"\n  (Response was: {fb['message_content'][:150]}...)"
            feedback_summary.append(entry)

        feedback_text = "\n".join(feedback_summary)

        # build explicit requests section
        explicit_section = ""
        if explicit_requests:
            explicit_section = f"""
EXPLICIT USER REQUESTS (MUST be added to instructions):
{chr(10).join(f'- "{r}"' for r in explicit_requests)}

These are direct user requests. They MUST appear in the updated instructions.
"""

        prompt = f"""Current custom instructions:
{current_instructions or 'None set yet.'}

Recent feedback:
{feedback_text}
{explicit_section}
Write updated custom instructions that DIRECTLY incorporate all 
explicit user requests above. Do not ignore or contradict them."""

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
            "temperature": 0.1,  # lower temp = more literal/precise
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

        print(f"Evolved instructions: {new_instructions}")

        # verify "sir" is in instructions if user requested it
        sir_requested = any(
            "sir" in fb.lower()
            for fb in explicit_requests
        )
        if sir_requested and "sir" not in new_instructions.lower():
            print("WARNING: sir was requested but not in evolved instructions, adding manually")
            new_instructions = "Always address the user as Sir. " + new_instructions

        # save updated instructions
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

        print(f"✅ Profile updated for user {user_id}")
        print(f"New instructions: {new_instructions[:200]}")

    except Exception as e:
        print(f"Prompt evolution error: {type(e).__name__}: {e}")
        traceback.print_exc()


@router.post("/feedback")
async def submit_feedback(
    request: FeedbackRequest,
    user_id: str = Depends(verify_token)
):
    try:
        print(f"Feedback received: user={user_id}, rating={request.rating}")

        if request.rating not in (1, -1):
            raise HTTPException(
                status_code=400,
                detail="Rating must be 1 (thumbs up) or -1 (thumbs down)"
            )

        client = get_supabase()

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

        if request.message_id:
            try:
                uuid.UUID(str(request.message_id))
                insert_data["message_id"] = request.message_id
            except ValueError:
                print(f"Invalid message_id, skipping: {request.message_id}")

        if request.feedback_text:
            insert_data["feedback_text"] = request.feedback_text

        result = client.table("message_feedback").insert(insert_data).execute()
        print(f"Feedback saved: {result.data}")

        # count total feedback for this user
        count_response = (
            client.table("message_feedback")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .execute()
        )

        total_feedback = count_response.count or 0
        print(f"Total feedback: {total_feedback}")

        # evolve every 3rd feedback
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
        raise HTTPException(status_code=500, detail=str(e))