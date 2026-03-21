from db.supabase import get_supabase
from typing import Optional


def create_conversation(title: str, model_id: str, user_id: str) -> dict:
    client = get_supabase()
    response = client.table("conversations").insert({
        "title": title,
        "model_id": model_id,
        "user_id": user_id
    }).execute()
    return response.data[0]


def get_conversations(user_id: str) -> list:
    client = get_supabase()
    response = (
        client.table("conversations")
        .select("*")
        .eq("user_id", user_id)
        .order("updated_at", desc=True)
        .execute()
    )
    return response.data


def get_conversation(conversation_id: str, user_id: str) -> Optional[dict]:
    client = get_supabase()
    response = (
        client.table("conversations")
        .select("*")
        .eq("id", conversation_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    return response.data


def update_conversation_title(
    conversation_id: str,
    title: str,
    user_id: Optional[str] = None
) -> dict:
    """
    Updates conversation title.
    user_id is optional — when called from background tasks
    (e.g. auto title generation) we only have conversation_id.
    """
    client = get_supabase()
    query = (
        client.table("conversations")
        .update({"title": title})
        .eq("id", conversation_id)
    )
    # only filter by user_id if provided
    if user_id:
        query = query.eq("user_id", user_id)

    response = query.execute()
    return response.data[0] if response.data else {}


def delete_conversation(conversation_id: str, user_id: str) -> None:
    client = get_supabase()
    client.table("conversations").delete().eq(
        "id", conversation_id
    ).eq("user_id", user_id).execute()