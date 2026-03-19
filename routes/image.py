import httpx
import os
import json

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENAI_IMAGE_API_URL = "https://api.openai.com/v1/images/generations"

PLOT_SYSTEM_PROMPT = """
You are a data visualization expert. Your job is to generate valid Plotly JSON for charts and plots.

When given a request for a chart or plot, respond ONLY with a valid Plotly JSON object in this exact format:
{
  "data": [...],
  "layout": {
    "title": "...",
    "template": "plotly_dark"
  }
}

Rules:
- Always use "plotly_dark" as the template
- Always include a descriptive title in the layout
- Use realistic sample data if no data is provided
- Supported chart types: scatter, bar, line, pie, histogram, heatmap, box, violin
- Make the chart visually appealing with proper axis labels
- Do not include any text outside the JSON object
- Do not wrap in markdown code blocks
""".strip()


async def generate_plot_json(message: str, conversation_history: list = []) -> dict | None:
    """
    Uses GPT-4o-mini to generate Plotly JSON for a chart request.
    Returns the Plotly JSON dict or None if failed.
    """
    headers = {
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/prism-ai",
        "X-Title": "Prism"
    }

    messages = [{"role": "system", "content": PLOT_SYSTEM_PROMPT}]

    for msg in conversation_history:
        messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": message})

    payload = {
        "model": "openai/gpt-4o-mini",
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 2000
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                OPENROUTER_API_URL,
                json=payload,
                headers=headers
            )

        if response.status_code != 200:
            print(f"Plot generation error: {response.status_code} {response.text}")
            return None

        data = response.json()
        content = data["choices"][0]["message"]["content"].strip()
        content = content.replace("```json", "").replace("```", "").strip()

        plot_json = json.loads(content)
        return plot_json

    except Exception as e:
        print(f"Plot generation exception: {e}")
        return None


async def generate_dalle_image(image_prompt: str) -> str:
    """
    Calls DALL-E 3 directly via OpenAI API.
    Returns the image URL or empty string if failed.
    """
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        print("DALLE error: OPENAI_API_KEY not set")
        return ""

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "dall-e-3",
        "prompt": image_prompt,
        "n": 1,
        "size": "1024x1024",
        "quality": "standard",
        "response_format": "url"
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                OPENAI_IMAGE_API_URL,
                json=payload,
                headers=headers
            )

        print(f"DALLE status: {response.status_code}")

        if response.status_code != 200:
            print(f"DALLE error response: {response.text}")
            return ""

        data = response.json()
        url = data["data"][0]["url"]
        print(f"DALLE success: {url[:50]}...")
        return url

    except Exception as e:
        print(f"DALLE exception: {e}")
        return ""