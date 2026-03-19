import httpx
import os


TAVILY_API_URL = "https://api.tavily.com/search"


async def web_search(query: str, max_results: int = 3) -> str:
    """
    Performs a Tavily web search and returns formatted results
    as a string to inject into the model's context.
    """
    payload = {
        "api_key": os.getenv("TAVILY_API_KEY"),
        "query": query,
        "max_results": max_results,
        "search_depth": "basic",
        "include_answer": True,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(TAVILY_API_URL, json=payload)

        if response.status_code != 200:
            return ""

        data = response.json()

        context_parts = []

        # include tavily's own answer summary if available
        if data.get("answer"):
            context_parts.append(f"Summary: {data['answer']}")

        # include top search results
        for result in data.get("results", []):
            title = result.get("title", "")
            url = result.get("url", "")
            content = result.get("content", "")
            context_parts.append(f"Source: {title}\nURL: {url}\nContent: {content}")

        if not context_parts:
            return ""

        return "\n\n---\n\n".join(context_parts)

    except Exception:
        return ""