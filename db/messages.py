from typing import Optional
from db.supabase import get_supabase


def save_message(
    conversation_id: str,
    role: str,
    content: str,
    model_id: Optional[str] = None,
    routed_to: Optional[str] = None,
    routing_reason: Optional[str] = None,
    search_used: bool = False,
    search_query: Optional[str] = None,
    file_used: bool = False,
    file_name: Optional[str] = None,
) -> dict:
    client = get_supabase()
    response = client.table("messages").insert({
        "conversation_id": conversation_id,
        "role": role,
        "content": content,
        "model_id": model_id,
        "routed_to": routed_to,
        "routing_reason": routing_reason,
        "search_used": search_used,
        "search_query": search_query,
        "file_used": file_used,
        "file_name": file_name,
    }).execute()
    return response.data[0]


def get_messages(conversation_id: str) -> list:
    client = get_supabase()
    response = (
        client.table("messages")
        .select("*")
        .eq("conversation_id", conversation_id)
        .order("created_at", desc=False)
        .execute()
    )
    return response.data