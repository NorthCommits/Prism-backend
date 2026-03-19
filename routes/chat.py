import httpx
import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from models.config import MODEL_REGISTRY
from routes.router import route_message
from routes.search import web_search
from routes.image import generate_plot_json, generate_dalle_image

router = APIRouter()

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

WEB_SEARCH_SYSTEM_ADDENDUM = """
You have been provided with recent web search results below to help answer the user's question accurately.
Use this information to give an up-to-date, well-informed response.
Always cite sources where relevant by mentioning the source title or URL.

--- WEB SEARCH RESULTS ---
{search_results}
--- END OF WEB SEARCH RESULTS ---
"""

FILE_CONTEXT_ADDENDUM = """
The user has uploaded a file for context. Use the file content below to answer their question accurately.

File name: {file_name}
File type: {file_type}

--- FILE CONTENT ---
{file_content}
--- END OF FILE CONTENT ---
"""


class HistoryMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    model_id: str
    conversation_history: Optional[List[HistoryMessage]] = []
    file_name: Optional[str] = None
    file_type: Optional[str] = None
    file_content: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    model_name: str
    model_id: str
    response_type: str = "text"  # "text", "plot", "image"
    plot_json: Optional[dict] = None
    image_url: Optional[str] = None
    routed_to: Optional[str] = None
    routing_reason: Optional[str] = None
    search_used: Optional[bool] = None
    search_query: Optional[str] = None
    file_used: Optional[bool] = None


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    routed_to = None
    routing_reason = None
    search_used = False
    search_query = None
    needs_web_search = False
    needs_plot = False
    needs_image = False
    image_prompt = ""
    file_used = False

    # combine message with file context for routing
    routing_message = request.message
    if request.file_content:
        routing_message = f"{request.message} [User has uploaded a file: {request.file_name}]"

    # auto routing
    if request.model_id == "auto":
        routed_to, needs_web_search, needs_plot, needs_image, search_query, image_prompt, routing_reason = await route_message(routing_message)
        resolved_model_id = routed_to
    else:
        resolved_model_id = request.model_id

    model_config = MODEL_REGISTRY.get(resolved_model_id)

    if not model_config:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown model_id '{resolved_model_id}'. Available: {list(MODEL_REGISTRY.keys())}"
        )

    # handle plot request
    if needs_plot:
        history = [{"role": m.role, "content": m.content} for m in (request.conversation_history or [])]
        plot_json = await generate_plot_json(request.message, history)
        if plot_json:
            return ChatResponse(
                reply="Here is your chart.",
                model_name=model_config.name,
                model_id=resolved_model_id,
                response_type="plot",
                plot_json=plot_json,
                routed_to=routed_to,
                routing_reason=routing_reason,
                search_used=False,
                file_used=False
            )

    # handle image request
    if needs_image:
        prompt = image_prompt or request.message
        image_url = await generate_dalle_image(prompt)
        if image_url:
            return ChatResponse(
                reply="Here is your generated image.",
                model_name=model_config.name,
                model_id=resolved_model_id,
                response_type="image",
                image_url=image_url,
                routed_to=routed_to,
                routing_reason=routing_reason,
                search_used=False,
                file_used=False
            )

    # build system prompt
    system_prompt = model_config.system_prompt

    # inject file content if provided
    if request.file_content and request.file_name:
        system_prompt += "\n\n" + FILE_CONTEXT_ADDENDUM.format(
            file_name=request.file_name,
            file_type=request.file_type or "unknown",
            file_content=request.file_content
        )
        file_used = True

    # inject web search results if needed
    if needs_web_search and search_query:
        search_results = await web_search(search_query)
        if search_results:
            system_prompt += "\n\n" + WEB_SEARCH_SYSTEM_ADDENDUM.format(
                search_results=search_results
            )
            search_used = True

    headers = {
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/prism-ai",
        "X-Title": "Prism"
    }

    # build messages array with full conversation history
    messages = [{"role": "system", "content": system_prompt}]

    for msg in (request.conversation_history or []):
        messages.append({"role": msg.role, "content": msg.content})

    messages.append({"role": "user", "content": request.message})

    payload = {
        "model": model_config.openrouter_model,
        "messages": messages
    }

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(OPENROUTER_API_URL, json=payload, headers=headers)

    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"OpenRouter error: {response.text}"
        )

    data = response.json()
    reply = data["choices"][0]["message"]["content"]

    return ChatResponse(
        reply=reply,
        model_name=model_config.name,
        model_id=resolved_model_id,
        response_type="text",
        routed_to=routed_to,
        routing_reason=routing_reason,
        search_used=search_used,
        search_query=search_query if search_used else None,
        file_used=file_used
    )