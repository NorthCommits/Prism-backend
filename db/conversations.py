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


def update_conversation_title(conversation_id: str, title: str, user_id: str) -> dict:
    client = get_supabase()
    response = (
        client.table("conversations")
        .update({"title": title})
        .eq("id", conversation_id)
        .eq("user_id", user_id)
        .execute()
    )
    return response.data[0]


def delete_conversation(conversation_id: str, user_id: str) -> None:
    client = get_supabase()
    client.table("conversations").delete().eq(
        "id", conversation_id
    ).eq("user_id", user_id).execute()