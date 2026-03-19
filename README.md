# Prism Backend

> The intelligent routing engine powering Prism — a copilot for small language models.

![Python](https://img.shields.io/badge/Python-3.11-blue?style=flat-square&logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi)
![Supabase](https://img.shields.io/badge/Supabase-PostgreSQL-3ECF8E?style=flat-square&logo=supabase)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?style=flat-square&logo=docker)
![License](https://img.shields.io/badge/License-MIT-purple?style=flat-square)

---

## What is Prism?

Prism is an open-source AI copilot that routes every user message to the most capable specialist model. Instead of using one general-purpose LLM for everything, Prism intelligently decides — in real time — whether your query needs a coding expert, a writing assistant, a web search, or even an AI-generated image or chart.

**The right model. Every time.**

---

## Architecture

```
User Message
     │
     ▼
┌─────────────────────────────┐
│         Router              │  ← GPT-4o-mini classifies intent
│  model_id + needs_search    │
│  needs_plot + needs_image   │
└─────────┬───────────────────┘
          │
    ┌─────┴──────┐
    │            │
    ▼            ▼
┌────────┐  ┌─────────┐
│ Tavily │  │  DALL-E │  ← Web search or image generation if needed
└────┬───┘  └────┬────┘
     │            │
     ▼            ▼
┌─────────────────────────────┐
│     Specialist Model        │  ← Coding or Writing LLM via OpenRouter
│  (with full context)        │
└─────────────────────────────┘
          │
          ▼
┌─────────────────────────────┐
│        Supabase             │  ← Persist conversation + messages
└─────────────────────────────┘
```

---

## Features

- **Auto Model Routing** — Classifies every message and routes it to the best specialist model automatically
- **Web Search Integration** — Detects when a query needs real-time information and fetches it via Tavily
- **File Upload & Parsing** — Supports CSV, XLSX, Python, JavaScript, TypeScript, Markdown, and plain text files
- **Data Visualization** — Generates interactive Plotly JSON charts from natural language descriptions
- **AI Image Generation** — Creates images via DALL-E 3 directly from user prompts
- **Conversation Memory** — Full conversation history sent with every request for coherent multi-turn chats
- **Persistent Storage** — All conversations and messages stored in Supabase PostgreSQL
- **User Authentication** — Supabase Auth integration with per-user conversation isolation
- **Docker Ready** — Single command to run the entire backend locally

---

## API Endpoints

### Chat
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/chat` | Send a message, get a response with routing metadata |
| `GET` | `/api/v1/models` | List all available specialist models |

### Files
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/file/parse` | Upload and parse a file (CSV, XLSX, code, text) |

### Conversations (Auth Required)
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/conversations` | Create a new conversation |
| `GET` | `/api/v1/conversations` | List all conversations for the authenticated user |
| `GET` | `/api/v1/conversations/:id` | Get a single conversation |
| `GET` | `/api/v1/conversations/:id/messages` | Get all messages in a conversation |
| `DELETE` | `/api/v1/conversations/:id` | Delete a conversation |
| `POST` | `/api/v1/messages` | Save a message to a conversation |

---

## Chat Request & Response

### Request
```json
{
  "message": "write a binary search in Python",
  "model_id": "auto",
  "conversation_history": [
    { "role": "user", "content": "..." },
    { "role": "assistant", "content": "..." }
  ],
  "file_name": "data.csv",
  "file_type": "csv",
  "file_content": "..."
}
```

`model_id` can be `"auto"`, `"coding"`, or `"writing"`.

### Response
```json
{
  "reply": "...",
  "model_name": "Coding Assistant",
  "model_id": "coding",
  "response_type": "text",
  "plot_json": null,
  "image_url": null,
  "routed_to": "coding",
  "routing_reason": "The request involves code generation.",
  "search_used": false,
  "search_query": null,
  "file_used": false
}
```

`response_type` can be `"text"`, `"plot"`, or `"image"`.

---

## Getting Started

### Prerequisites
- Docker and Docker Compose
- OpenRouter API key (free at [openrouter.ai](https://openrouter.ai))
- OpenAI API key (for DALL-E 3)
- Tavily API key (free at [tavily.com](https://tavily.com))
- Supabase project (free at [supabase.com](https://supabase.com))

### 1. Clone the repository
```bash
git clone https://github.com/your-username/prism-backend.git
cd prism-backend
```

### 2. Set up environment variables
```bash
cp .env.example .env
```

Edit `.env` with your actual keys:
```dotenv
OPENROUTER_API_KEY=your_openrouter_api_key
OPENAI_API_KEY=your_openai_api_key
TAVILY_API_KEY=your_tavily_api_key
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_service_role_key
```

### 3. Set up Supabase database
Run this SQL in your Supabase SQL editor:

```sql
CREATE TABLE conversations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title TEXT NOT NULL,
  model_id TEXT NOT NULL DEFAULT 'auto',
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content TEXT NOT NULL,
  model_id TEXT,
  routed_to TEXT,
  routing_reason TEXT,
  search_used BOOLEAN DEFAULT FALSE,
  search_query TEXT,
  file_used BOOLEAN DEFAULT FALSE,
  file_name TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_messages_conversation_id ON messages(conversation_id);
CREATE INDEX idx_conversations_user_id ON conversations(user_id);
```

### 4. Run with Docker
```bash
docker-compose up --build
```

The API will be available at `http://localhost:8000`.

### 5. Explore the API docs
Visit `http://localhost:8000/docs` for the interactive Swagger UI.

---

## Project Structure

```
prism-backend/
├── main.py                  # FastAPI app entry point
├── requirements.txt         # Python dependencies
├── Dockerfile
├── docker-compose.yml
├── models/
│   ├── config.py            # Model registry (add new models here)
│   └── router_config.py     # Router system prompt
├── routes/
│   ├── chat.py              # Main chat endpoint
│   ├── router.py            # Intent classification logic
│   ├── search.py            # Tavily web search
│   ├── image.py             # DALL-E 3 + Plotly JSON generation
│   ├── file.py              # File parsing (CSV, XLSX, code)
│   └── history.py           # Conversation CRUD endpoints
└── db/
    ├── supabase.py          # Supabase client singleton
    ├── auth.py              # JWT token verification
    ├── conversations.py     # Conversation DB operations
    └── messages.py          # Message DB operations
```

---

## Adding a New Specialist Model

Adding a new model to Prism takes less than a minute. Open `models/config.py` and add an entry:

```python
"summarization": ModelConfig(
    name="Summarization Assistant",
    description="Specialized for summarizing long documents and articles.",
    openrouter_model="openai/gpt-4o-mini",
    system_prompt="You are an expert at summarizing content concisely and accurately..."
)
```

That's it. The router will automatically start routing relevant queries to it.

---

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `OPENROUTER_API_KEY` | OpenRouter API key for model access | Yes |
| `OPENAI_API_KEY` | OpenAI API key for DALL-E 3 image generation | Yes |
| `TAVILY_API_KEY` | Tavily API key for web search | Yes |
| `SUPABASE_URL` | Your Supabase project URL | Yes |
| `SUPABASE_KEY` | Supabase service role key (keep secret) | Yes |

---

## Tech Stack

| Technology | Purpose |
|------------|---------|
| **FastAPI** | High-performance async API framework |
| **OpenRouter** | Unified API gateway for LLMs |
| **GPT-4o-mini** | Intent classification and routing |
| **Tavily** | Real-time web search |
| **DALL-E 3** | AI image generation |
| **Plotly** | Interactive data visualization |
| **Supabase** | PostgreSQL database + Auth |
| **Docker** | Containerization |

---

## Contributing

Contributions are welcome! Please feel free to open an issue or submit a pull request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feat/amazing-feature`)
3. Commit your changes (`git commit -m 'feat: add amazing feature'`)
4. Push to the branch (`git push origin feat/amazing-feature`)
5. Open a Pull Request

---

## License

MIT License — feel free to use this in your own projects.

---

<p align="center">Built with ❤️ by <a href="https://github.com/your-username">Swapnil Bhattacharya</a></p>