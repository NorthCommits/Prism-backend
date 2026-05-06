import httpx
import os
import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List
from models.config import MODEL_REGISTRY
from routes.router import route_message
from routes.search import web_search
from routes.image import generate_plot_json, generate_dalle_image
from routes.sandbox import execute_code
from routes.context import build_smart_context
from routes.profile import get_profile_by_user_id, build_profile_context
from routes.memory import get_user_memories, build_memory_context
# from routes.agent import run_agent
from routes.templates import get_template_system_prompt
from routes.projects import get_project_context

VISION_MODEL = "openai/gpt-4o"

CUSTOM_INSTRUCTIONS_ADDENDUM = """
--- STRICT USER INSTRUCTIONS — HIGHEST PRIORITY ---
{profile_context}
--- THESE INSTRUCTIONS MUST BE FOLLOWED IN EVERY RESPONSE ---
"""

PROJECT_CONTEXT_ADDENDUM = """
--- PROJECT CONTEXT ---
{project_context}
--- END OF PROJECT CONTEXT ---
"""

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
    model_id: Optional[str] = None


class ChatRequest(BaseModel):
    message: str
    model_id: str
    conversation_history: Optional[List[HistoryMessage]] = []
    file_name: Optional[str] = None
    file_type: Optional[str] = None
    file_content: Optional[str] = None
    user_id: Optional[str] = None
    image_base64: Optional[str] = None
    image_media_type: Optional[str] = None
    active_template: Optional[str] = None
    project_id: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    model_name: str
    model_id: str
    response_type: str = "text"
    plot_json: Optional[dict] = None
    image_url: Optional[str] = None
    routed_to: Optional[str] = None
    routing_reason: Optional[str] = None
    search_used: Optional[bool] = None
    search_query: Optional[str] = None
    file_used: Optional[bool] = None
    image_used: Optional[bool] = None
    active_template: Optional[str] = None
    project_id: Optional[str] = None


# ═══════════════════════════════════════
# OPENROUTER STREAM (internal helper)
# ═══════════════════════════════════════

async def _stream_openrouter(
    messages: list,
    model: str,
    metadata: dict
):
    """
    Internal OpenRouter streaming helper.
    Does NOT emit metadata — caller handles that.
    """
    headers = {
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/prism-ai",
        "X-Title": "Prism"
    }

    payload = {
        "model": model,
        "messages": messages,
        "stream": True
    }

    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream(
            "POST",
            OPENROUTER_API_URL,
            json=payload,
            headers=headers
        ) as response:
            if response.status_code != 200:
                error = await response.aread()
                yield f"data: {json.dumps({'type': 'error', 'message': error.decode()})}\n\n"
                return

            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        yield f"data: {json.dumps({'type': 'done'})}\n\n"
                        return
                    try:
                        chunk = json.loads(data)
                        delta = chunk["choices"][0]["delta"]
                        if "content" in delta and delta["content"]:
                            yield f"data: {json.dumps({'type': 'token', 'content': delta['content']})}\n\n"
                    except Exception:
                        continue


# ═══════════════════════════════════════
# HUGGINGFACE STREAM
# ═══════════════════════════════════════

async def stream_hf_response(
    messages: list,
    hf_url: str,
    system_prompt: str,
    metadata: dict,
    openrouter_model: str
):
    """
    Calls HuggingFace Space.
    HF Space returns handled_by: 'local' or 'openai'
    
    local  → stream word by word from HF response
    openai → fall back to OpenRouter (complex task)
    error  → fall back to OpenRouter
    timeout → fall back to OpenRouter
    """
    yield f"data: {json.dumps({'type': 'metadata', **metadata})}\n\n"

    try:
        # extract last user message
        user_message = ""
        for msg in messages:
            if isinstance(msg.get("content"), str):
                if msg["role"] == "user":
                    user_message = msg["content"]

        print(f"Calling HF Space: {hf_url}/generate")

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{hf_url}/generate",
                json={
                    "prompt": user_message,
                    "system_prompt": system_prompt,
                    "max_tokens": 512,
                    "temperature": 0.7
                },
                headers={"Content-Type": "application/json"}
            )

        if response.status_code != 200:
            print(f"HF Space error: {response.status_code} "
                  f"— falling back to OpenRouter")
            async for chunk in _stream_openrouter(
                messages, openrouter_model, metadata
            ):
                yield chunk
            return

        data = response.json()
        handled_by = data.get("handled_by", "local")
        complexity = data.get("complexity", "simple")
        full_response = data.get("response", "").strip()
        tokens_generated = data.get("tokens_generated", 0)

        print(f"HF response: complexity={complexity}, "
              f"handled_by={handled_by}, "
              f"tokens={tokens_generated}")

        # complex task or error — fall back to OpenRouter
        if handled_by in ("openai", "error") or not full_response:
            print(f"Task is {complexity} — "
                  f"escalating to OpenRouter")

            # update metadata to reflect actual model used
            escalated_metadata = {
                **metadata,
                "model_name": "Coding Assistant (OpenAI)",
                "routing_reason": (
                    f"Complex task detected — escalated from "
                    f"local model to OpenAI"
                )
            }
            # emit updated metadata
            yield f"data: {json.dumps({'type': 'metadata', **escalated_metadata})}\n\n"

            async for chunk in _stream_openrouter(
                messages, openrouter_model, metadata
            ):
                # skip metadata from openrouter — already sent
                if chunk.startswith("data: "):
                    try:
                        parsed = json.loads(chunk[6:])
                        if parsed.get("type") != "metadata":
                            yield chunk
                    except Exception:
                        yield chunk
            return

        # simple task — stream local model response word by word
        print(f"Streaming local Qwen response: "
              f"{len(full_response)} chars")

        words = full_response.split(" ")
        for i, word in enumerate(words):
            token = word if i == len(words) - 1 else word + " "
            yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    except httpx.TimeoutException:
        print("HF Space timed out — falling back to OpenRouter")
        async for chunk in _stream_openrouter(
            messages, openrouter_model, metadata
        ):
            yield chunk

    except Exception as e:
        print(f"HF Space error: {type(e).__name__}: {e} "
              f"— falling back to OpenRouter")
        async for chunk in _stream_openrouter(
            messages, openrouter_model, metadata
        ):
            yield chunk


# ═══════════════════════════════════════
# OPENROUTER STREAM (public)
# ═══════════════════════════════════════

async def stream_response(
    messages: list,
    model: str,
    metadata: dict
):
    headers = {
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/prism-ai",
        "X-Title": "Prism"
    }

    payload = {
        "model": model,
        "messages": messages,
        "stream": True
    }

    yield f"data: {json.dumps({'type': 'metadata', **metadata})}\n\n"

    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream(
            "POST",
            OPENROUTER_API_URL,
            json=payload,
            headers=headers
        ) as response:
            if response.status_code != 200:
                error = await response.aread()
                yield f"data: {json.dumps({'type': 'error', 'message': error.decode()})}\n\n"
                return

            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        yield f"data: {json.dumps({'type': 'done'})}\n\n"
                        return
                    try:
                        chunk = json.loads(data)
                        delta = chunk["choices"][0]["delta"]
                        if "content" in delta and delta["content"]:
                            yield f"data: {json.dumps({'type': 'token', 'content': delta['content']})}\n\n"
                    except Exception:
                        continue


@router.post("/chat")
async def chat(request: ChatRequest):
    routed_to = None
    routing_reason = None
    search_used = False
    search_query = None
    needs_web_search = False
    needs_plot = False
    needs_image = False
    needs_execution = False
    # needs_agent = False
    image_prompt = ""
    execution_code = ""
    execution_language = "python"
    file_used = False
    image_used = False

    routing_message = request.message
    if request.file_content:
        routing_message = f"{request.message} [User has uploaded a file: {request.file_name}]"
    if request.image_base64:
        routing_message = f"{request.message} [User has uploaded an image]"

    if request.model_id == "auto":
        (routed_to, needs_web_search, needs_plot, needs_image,
        needs_execution, _, search_query, image_prompt,
        execution_code, execution_language, routing_reason) = await route_message(routing_message)
        resolved_model_id = routed_to
    else:
        resolved_model_id = request.model_id

    model_config = MODEL_REGISTRY.get(resolved_model_id)

    if not model_config:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown model_id '{resolved_model_id}'. Available: {list(MODEL_REGISTRY.keys())}"
        )

    if needs_plot and not request.image_base64 and not request.active_template:
        plot_context = request.message
        if needs_web_search and search_query:
            search_results = await web_search(search_query)
            if search_results:
                plot_context = (
                    f"{request.message}\n\n"
                    f"Use this real data from web search to populate the chart:\n"
                    f"{search_results}"
                )
                search_used = True

        history = [{"role": m.role, "content": m.content} for m in (request.conversation_history or [])]
        plot_json = await generate_plot_json(plot_context, history)
        if plot_json:
            return ChatResponse(
                reply="Here is your chart.",
                model_name=model_config.name,
                model_id=resolved_model_id,
                response_type="plot",
                plot_json=plot_json,
                routed_to=routed_to,
                routing_reason=routing_reason,
                search_used=search_used,
                search_query=search_query if search_used else None,
                file_used=False
            )

    if needs_image and not request.image_base64 and not request.active_template:
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

    if needs_execution and execution_code and not request.image_base64 and not request.active_template:
        result = await execute_code(execution_code, execution_language)

        output_lines = []
        if result["stdout"]:
            output_lines.append(f"**Output:**\n```\n{result['stdout'].strip()}\n```")
        if result["stderr"]:
            output_lines.append(f"**Errors:**\n```\n{result['stderr'].strip()}\n```")
        if result["timed_out"]:
            output_lines.append("**Execution timed out after 10 seconds.**")
        if not output_lines:
            output_lines.append("**No output produced.**")

        execution_output = "\n\n".join(output_lines)

        return ChatResponse(
            reply=execution_output,
            model_name=model_config.name,
            model_id=resolved_model_id,
            response_type="text",
            routed_to=routed_to,
            routing_reason=routing_reason,
            search_used=False,
            file_used=False
        )

    system_prompt = model_config.system_prompt

    if request.active_template:
        template_prompt = get_template_system_prompt(request.active_template)
        if template_prompt:
            system_prompt = template_prompt + "\n\n" + system_prompt

    if request.project_id and request.user_id:
        project_context = await get_project_context(
            request.project_id,
            request.user_id
        )
        if project_context:
            system_prompt += "\n\n" + PROJECT_CONTEXT_ADDENDUM.format(
                project_context=project_context
            )
            print(f"Injected project context for project {request.project_id}")

    if request.file_content and request.file_name:
        system_prompt += "\n\n" + FILE_CONTEXT_ADDENDUM.format(
            file_name=request.file_name,
            file_type=request.file_type or "unknown",
            file_content=request.file_content
        )
        file_used = True

    if request.user_id:
        profile = await get_profile_by_user_id(request.user_id)
        if profile:
            profile_context = build_profile_context(profile)
            if profile_context:
                system_prompt += "\n\n" + CUSTOM_INSTRUCTIONS_ADDENDUM.format(
                    profile_context=profile_context
                )

    if request.user_id:
        memories = await get_user_memories(request.user_id)
        if memories:
            memory_context = build_memory_context(memories)
            if memory_context:
                system_prompt += "\n\n" + memory_context

    if needs_web_search and search_query and not request.image_base64:
        search_results = await web_search(search_query)
        if search_results:
            system_prompt += "\n\n" + WEB_SEARCH_SYSTEM_ADDENDUM.format(
                search_results=search_results
            )
            search_used = True

    # if needs_agent and not request.image_base64 and not request.active_template:
    #     agent_metadata = {
    #         "model_name": model_config.name,
    #         "model_id": resolved_model_id,
    #         "response_type": "text",
    #         "routed_to": routed_to,
    #         "routing_reason": routing_reason,
    #         "search_used": False,
    #         "search_query": None,
    #         "file_used": file_used,
    #         "image_used": False,
    #         "is_agent": True,
    #         "active_template": request.active_template,
    #         "project_id": request.project_id
    #     }

    #     return StreamingResponse(
    #         run_agent(
    #             message=request.message,
    #             system_prompt=system_prompt,
    #             specialist=model_config.name,
    #             metadata=agent_metadata
    #         ),
    #         media_type="text/event-stream",
    #         headers={
    #             "Cache-Control": "no-cache",
    #             "Connection": "keep-alive",
    #             "X-Accel-Buffering": "no"
    #         }
    #     )

    history_dicts = [
        {
            "role": msg.role,
            "content": msg.content,
            "model_id": msg.model_id
        }
        for msg in (request.conversation_history or [])
    ]

    messages = await build_smart_context(
        conversation_history=history_dicts,
        current_model_id=resolved_model_id,
        system_prompt=system_prompt
    )

    if request.image_base64:
        media_type = request.image_media_type or "image/jpeg"
        user_message = {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{media_type};base64,{request.image_base64}"
                    }
                },
                {
                    "type": "text",
                    "text": request.message or "What is in this image?"
                }
            ]
        }
        messages.append(user_message)
        image_used = True
        selected_model = VISION_MODEL
        routing_reason = "Image uploaded — using GPT-4o vision model"
        routed_to = "coding"
    else:
        messages.append({"role": "user", "content": request.message})
        selected_model = model_config.openrouter_model

    metadata = {
        "model_name": "Vision Assistant" if image_used else model_config.name,
        "model_id": resolved_model_id,
        "response_type": "text",
        "routed_to": routed_to,
        "routing_reason": routing_reason,
        "search_used": search_used,
        "search_query": search_query if search_used else None,
        "file_used": file_used,
        "image_used": image_used,
        # "is_agent": False,
        "active_template": request.active_template,
        "project_id": request.project_id
    }

    # ═══════════════════════════════════════
    # ROUTE TO HF SPACE OR OPENROUTER
    # ═══════════════════════════════════════

    if (
        not image_used
        and resolved_model_id == "coding"
        and model_config.use_hf
        and model_config.hf_url
    ):
        print(f"Routing to HuggingFace Space: {model_config.hf_url}")
        metadata["model_name"] = "Coding Assistant (Qwen2.5)"
        metadata["routing_reason"] = (
            routing_reason or "Routed to local coding model"
        )
        return StreamingResponse(
            stream_hf_response(
                messages=messages,
                hf_url=model_config.hf_url,
                system_prompt=system_prompt,
                metadata=metadata,
                openrouter_model=model_config.openrouter_model
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )

    # default: OpenRouter
    return StreamingResponse(
        stream_response(messages, selected_model, metadata),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )