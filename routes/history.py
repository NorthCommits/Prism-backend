from fastapi import APIRouter, HTTPException, Depends
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
import asyncio

router = APIRouter()


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

        # trigger memory extraction after every 4th assistant message
        # runs in background so it doesn't slow down the response
        if request.role == "assistant":
            all_messages = get_messages(request.conversation_id)
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