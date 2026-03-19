import httpx
import os
import json
from models.router_config import ROUTER_SYSTEM_PROMPT, ROUTER_USER_PROMPT
from models.config import MODEL_REGISTRY

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
ROUTER_MODEL = "openai/gpt-4o-mini"


async def route_message(message: str) -> tuple[str, bool, bool, bool, str, str, str]:
    """
    Returns (model_id, needs_web_search, needs_plot, needs_image, search_query, image_prompt, reason)
    Falls back to ("writing", False, False, False, "", "", "fallback") if routing fails.
    """
    headers = {
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/prism-ai",
        "X-Title": "Prism"
    }

    payload = {
        "model": ROUTER_MODEL,
        "messages": [
            {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
            {"role": "user", "content": ROUTER_USER_PROMPT.format(message=message)}
        ],
        "temperature": 0,
        "max_tokens": 200
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                OPENROUTER_API_URL,
                json=payload,
                headers=headers
            )

        if response.status_code != 200:
            return "writing", False, False, False, "", "", "Fallback due to router error"

        data = response.json()
        content = data["choices"][0]["message"]["content"].strip()

        # clean markdown fences if model wraps in ```json
        content = content.replace("```json", "").replace("```", "").strip()

        result = json.loads(content)
        model_id = result.get("model_id", "writing")
        needs_web_search = result.get("needs_web_search", False)
        needs_plot = result.get("needs_plot", False)
        needs_image = result.get("needs_image", False)
        search_query = result.get("search_query", "")
        image_prompt = result.get("image_prompt", "")
        reason = result.get("reason", "No reason provided")

        # validate model_id is actually registered
        if model_id not in MODEL_REGISTRY:
            return "writing", False, False, False, "", "", "Fallback: unknown model returned by router"

        # enforce mutual exclusivity
        if needs_plot and needs_image:
            needs_image = False

        return model_id, needs_web_search, needs_plot, needs_image, search_query, image_prompt, reason

    except Exception:
        return "writing", False, False, False, "", "", "Fallback due to unexpected router error"