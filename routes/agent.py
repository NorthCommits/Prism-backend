import os
import json
import httpx
from typing import List, AsyncGenerator

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
PLANNER_MODEL = "openai/gpt-4o-mini"
EXECUTOR_MODEL = "openai/gpt-4o-mini"

PLANNER_SYSTEM_PROMPT = """
You are a task planning expert for Prism, an AI copilot.

Your job is to break down complex user requests into clear, sequential steps.

Rules:
- Maximum 6 steps, minimum 2 steps
- Each step should be focused and self-contained
- Steps should build on each other logically
- Each step title should be short (5 words max)
- Only use agent mode for genuinely complex multi-part tasks
- Simple questions should NOT be broken into steps

Respond ONLY with a valid JSON array:
[
  {
    "step": 1,
    "title": "Design the data model",
    "instruction": "Define the schema and data structure for the todo list including fields, types and relationships"
  },
  {
    "step": 2,
    "title": "Write Pydantic schemas",
    "instruction": "Create Pydantic models for request/response validation based on the data model"
  }
]

Return [] if the task does not need multiple steps.
""".strip()

EXECUTOR_SYSTEM_PROMPT = """
You are an expert {specialist} working on step {step_num} of {total_steps} for a complex task.

Overall task: {overall_task}

Previous steps completed:
{previous_context}

Your job for this step: {step_instruction}

Be thorough and complete for this specific step.
Build naturally on what was done in previous steps.
Do not repeat content from previous steps.

EMOTIONAL INTELLIGENCE:
You are warm, encouraging and human.
The user is working on something complex and
multi-step — acknowledge their effort.
On step 1: start with a brief warm line like
"Alright, let us build this together step by step."
On final step: end with encouragement like
"And that wraps it up! You now have a complete
implementation. Well done for seeing this through."
Between steps: keep momentum with phrases like
"Building on that..." or "Now for the next piece..."
Keep empathy brief — 1 sentence per step max.
""".strip()


async def plan_task(message: str) -> List[dict]:
    """
    Uses GPT-4o-mini to break a complex task into steps.
    Returns list of steps or empty list if not needed.
    """
    headers = {
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/prism-ai",
        "X-Title": "Prism"
    }

    payload = {
        "model": PLANNER_MODEL,
        "messages": [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": f"Break this task into steps:\n\n{message}"}
        ],
        "temperature": 0,
        "max_tokens": 800
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                OPENROUTER_API_URL,
                json=payload,
                headers=headers
            )

        if response.status_code != 200:
            return []

        data = response.json()
        content = data["choices"][0]["message"]["content"].strip()
        content = content.replace("```json", "").replace("```", "").strip()

        steps = json.loads(content)
        if not isinstance(steps, list) or len(steps) < 2:
            return []

        return steps

    except Exception as e:
        print(f"Planning error: {e}")
        return []


async def execute_step_stream(
    overall_task: str,
    step: dict,
    total_steps: int,
    previous_context: str,
    system_prompt: str,
    specialist: str = "AI assistant"
) -> AsyncGenerator[str, None]:
    """
    Executes a single step and streams the response.
    """
    headers = {
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/prism-ai",
        "X-Title": "Prism"
    }

    step_system_prompt = EXECUTOR_SYSTEM_PROMPT.format(
        specialist=specialist,
        step_num=step["step"],
        total_steps=total_steps,
        overall_task=overall_task,
        previous_context=previous_context or "None — this is the first step.",
        step_instruction=step["instruction"]
    )

    payload = {
        "model": EXECUTOR_MODEL,
        "messages": [
            {"role": "system", "content": step_system_prompt},
            {"role": "user", "content": step["instruction"]}
        ],
        "stream": True
    }

    try:
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
                            return
                        try:
                            chunk = json.loads(data)
                            delta = chunk["choices"][0]["delta"]
                            if "content" in delta and delta["content"]:
                                yield delta["content"]
                        except Exception:
                            continue

    except Exception as e:
        print(f"Step execution error: {e}")


async def run_agent(
    message: str,
    system_prompt: str,
    specialist: str,
    metadata: dict
) -> AsyncGenerator[str, None]:
    """
    Main agent runner — plans and executes steps sequentially.
    Yields SSE events for the frontend.
    """

    # send metadata first
    yield f"data: {json.dumps({'type': 'metadata', **metadata})}\n\n"

    # plan the task
    steps = await plan_task(message)

    if not steps:
        # warm fallback message
        yield f"data: {json.dumps({'type': 'token', 'content': 'Hmm, I could not break that into steps. Let me try answering it directly instead.'})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
        return

    total_steps = len(steps)

    # warm intro before plan
    intro = f"Alright! This is a multi-step task. I will walk you through all {total_steps} steps together.\n\n"
    yield f"data: {json.dumps({'type': 'token', 'content': intro})}\n\n"

    # send plan to frontend
    yield f"data: {json.dumps({'type': 'agent_plan', 'steps': [s['title'] for s in steps], 'total': total_steps})}\n\n"

    previous_context = ""
    full_response_parts = []

    for step in steps:
        step_num = step["step"]

        # signal step start
        yield f"data: {json.dumps({'type': 'agent_step_start', 'step': step_num, 'total': total_steps, 'title': step['title']})}\n\n"

        # stream step content
        step_content = ""
        async for token in execute_step_stream(
            overall_task=message,
            step=step,
            total_steps=total_steps,
            previous_context=previous_context,
            system_prompt=system_prompt,
            specialist=specialist
        ):
            step_content += token
            yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"

        # signal step done
        yield f"data: {json.dumps({'type': 'agent_step_done', 'step': step_num, 'total': total_steps})}\n\n"

        # add separator between steps
        separator = f"\n\n---\n\n"
        yield f"data: {json.dumps({'type': 'token', 'content': separator})}\n\n"
        step_content += separator

        # build context for next step
        previous_context += f"\nStep {step_num} ({step['title']}):\n{step_content[:500]}...\n"
        full_response_parts.append(step_content)

    # warm completion message
    completion = "\n\n✦ All done! You now have a complete implementation. Let me know if you want to adjust anything or go deeper on any step."
    yield f"data: {json.dumps({'type': 'token', 'content': completion})}\n\n"

    # signal completion
    yield f"data: {json.dumps({'type': 'done'})}\n\n"