from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from db.supabase import get_supabase
from db.auth import verify_token

router = APIRouter()


class UserProfile(BaseModel):
    display_name: Optional[str] = None
    about_you: Optional[str] = None
    custom_instructions: Optional[str] = None
    response_style: Optional[str] = "balanced"
    onboarding_completed: Optional[bool] = False


class UserProfileResponse(BaseModel):
    id: Optional[str] = None
    user_id: Optional[str] = None
    display_name: Optional[str] = None
    about_you: Optional[str] = None
    custom_instructions: Optional[str] = None
    response_style: Optional[str] = "balanced"
    onboarding_completed: Optional[bool] = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@router.get("/profile", response_model=UserProfileResponse)
async def get_profile(user_id: str = Depends(verify_token)):
    try:
        client = get_supabase()
        response = (
            client.table("user_profiles")
            .select("*")
            .eq("user_id", user_id)
            .execute()
        )
        if not response.data:
            return UserProfileResponse(user_id=user_id)
        return UserProfileResponse(**response.data[0])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/profile", response_model=UserProfileResponse)
async def upsert_profile(
    profile: UserProfile,
    user_id: str = Depends(verify_token)
):
    try:
        client = get_supabase()

        existing = (
            client.table("user_profiles")
            .select("id")
            .eq("user_id", user_id)
            .execute()
        )

        data = {
            "user_id": user_id,
            "display_name": profile.display_name,
            "about_you": profile.about_you,
            "custom_instructions": profile.custom_instructions,
            "response_style": profile.response_style or "balanced"
        }

        # only update onboarding_completed if explicitly provided
        if profile.onboarding_completed is not None:
            data["onboarding_completed"] = profile.onboarding_completed

        if existing.data:
            response = (
                client.table("user_profiles")
                .update(data)
                .eq("user_id", user_id)
                .execute()
            )
        else:
            response = (
                client.table("user_profiles")
                .insert(data)
                .execute()
            )

        return UserProfileResponse(**response.data[0])

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/profile/complete-onboarding")
async def complete_onboarding(user_id: str = Depends(verify_token)):
    """
    Marks onboarding as completed for the user.
    Called when user finishes the onboarding flow.
    """
    try:
        client = get_supabase()

        existing = (
            client.table("user_profiles")
            .select("id")
            .eq("user_id", user_id)
            .execute()
        )

        if existing.data:
            client.table("user_profiles").update({
                "onboarding_completed": True
            }).eq("user_id", user_id).execute()
        else:
            client.table("user_profiles").insert({
                "user_id": user_id,
                "onboarding_completed": True
            }).execute()

        return {"success": True}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def get_profile_by_user_id(user_id: Optional[str]) -> Optional[dict]:
    """
    Fetches user profile for injecting into system prompt.
    Returns None if no profile or user_id not provided.
    """
    if not user_id:
        return None
    try:
        client = get_supabase()
        response = (
            client.table("user_profiles")
            .select("*")
            .eq("user_id", user_id)
            .execute()
        )
        if not response.data:
            return None
        return response.data[0]
    except Exception:
        return None


def build_profile_context(profile: dict) -> str:
    """
    Builds a context string from user profile to inject into system prompt.
    """
    parts = []

    if profile.get("display_name"):
        parts.append(f"User's name: {profile['display_name']}")

    if profile.get("about_you"):
        parts.append(f"About the user: {profile['about_you']}")

    if profile.get("custom_instructions"):
        parts.append(f"Custom instructions: {profile['custom_instructions']}")

    if profile.get("response_style"):
        style_descriptions = {
            "balanced": "Respond in a balanced, clear way",
            "concise": "Keep responses short and to the point",
            "detailed": "Provide detailed, comprehensive responses",
            "friendly": "Use a warm, friendly and casual tone",
            "technical": "Use technical language and assume expertise"
        }
        style = profile["response_style"]
        if style in style_descriptions:
            parts.append(f"Response style: {style_descriptions[style]}")

    return "\n".join(parts)