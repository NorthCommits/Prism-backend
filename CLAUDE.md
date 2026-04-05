# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Project

```bash
# Development (hot reload)
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Docker (production-like)
docker-compose up --build
```

No build step required — Python runs directly.

## Environment Variables

Required in `.env`:
- `OPENROUTER_API_KEY` — routes LLM calls to specialist models
- `OPENAI_API_KEY` — used for embeddings (text-embedding-3-small) and vision
- `SUPABASE_URL` / `SUPABASE_KEY` — database and auth
- `TAVILY_API_KEY` — web search
- `SANDBOX_URL` — HuggingFace Judge0 endpoint for code execution

## Architecture

**Prism** is a FastAPI backend that routes every chat message to the best specialist LLM via an intent classification pipeline.

### Request Flow (routes/chat.py)
1. `route_message()` (routes/router.py) — GPT-4o-mini classifies the message, returns an 11-tuple: `(model_id, needs_web_search, needs_plot, needs_image, needs_execution, needs_agent, search_query, image_prompt, execution_code, execution_language, reason)`
2. System prompt is assembled in layers (priority order):
   - Template instructions (highest priority, if active)
   - Project context (instructions + injected file contents)
   - Uploaded file content
   - User profile (name, style, custom instructions)
   - Cross-conversation memories
   - Web search results (if routed to search)
3. Streaming response via Server-Sent Events (SSE): `metadata → token... → done`

### Background Tasks (fired in chat.py after streaming)
Every message: store embeddings for suggestions.
Every 2nd message: auto-generate conversation title.
Every 4th message: extract memories, score conversation.

### Smart Context Compression (routes/context.py)
- ≤8 messages: full history
- 9–15 messages: summarize older + keep last 6
- ≥16 messages: summarize older + keep last 4

### Model Registry (models/config.py)
`MODEL_REGISTRY` dict maps `model_id` strings to `ModelConfig` (name, description, system_prompt, capabilities). To add a new model, add an entry here — no other changes needed.

### Database (db/)
Supabase PostgreSQL with no ORM. Direct SDK calls: `.select()`, `.insert()`, `.update()`, `.delete()`. Authentication via Supabase JWT — `verify_token()` in `db/auth.py` is used as a FastAPI dependency on protected routes.

pgvector is used in the `conversation_embeddings` table for semantic similarity search powering the suggestions feature (routes/suggestions.py).

### Key Routes
| File | Responsibility |
|------|---------------|
| `routes/chat.py` | Main chat endpoint, full pipeline |
| `routes/router.py` | Intent classification → 11-tuple |
| `routes/agent.py` | Multi-step planner/executor |
| `routes/projects.py` | Workspaces, file injection |
| `routes/memory.py` | Cross-conversation memory extraction |
| `routes/suggestions.py` | Embedding-based context suggestions |
| `routes/feedback.py` | Message ratings, prompt evolution |
| `routes/scores.py` | Conversation quality scoring |
| `routes/context.py` | History compression |
| `routes/demo.py` | Public/unauthenticated demo endpoint |

All routers are registered in `main.py` under `/api/v1`.
