# Prism Backend

> The intelligent routing engine powering Prism — an AI copilot that sends every message to the right model.

![Python](https://img.shields.io/badge/Python-3.11-blue?style=flat-square&logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi)
![Supabase](https://img.shields.io/badge/Supabase-PostgreSQL-3ECF8E?style=flat-square&logo=supabase)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?style=flat-square&logo=docker)
![OpenAI](https://img.shields.io/badge/OpenAI-Whisper%20%7C%20GPT--4o-412991?style=flat-square&logo=openai)
![License](https://img.shields.io/badge/License-MIT-purple?style=flat-square)

---

## What is Prism?

Prism is an open-source AI copilot that routes every user message to the most capable specialist model. Instead of sending every question to the same general-purpose LLM, Prism reads what you are asking, decides what kind of help you need, and picks the best model for that specific task — automatically, in real time.

It also learns who you are. Prism extracts memories from your conversations, adapts to your feedback, and builds a profile of your preferences over time. The more you use it, the better it gets.

**The right model. Every time.**

---

## System Architecture

```mermaid
graph TB
    Client(["🖥️ Prism Frontend<br/>Next.js + TypeScript"])

    subgraph Backend ["⚡ Prism Backend — FastAPI"]
        Router["🧠 Router<br/>GPT-4o-mini<br/>Intent Classification"]
        Chat["💬 Chat Pipeline<br/>System Prompt Builder<br/>SSE Streaming"]
        Agent["🤖 Agent Mode<br/>Multi-Step Executor"]
        Memory["🧩 Memory Engine<br/>Extraction + Injection"]
        Scores["📊 Scoring Engine<br/>Productivity Analysis"]
        Embeddings["🔍 Embeddings<br/>Semantic Search"]
        Voice["🎙️ Voice<br/>Whisper + TTS"]
        Projects["📁 Projects<br/>Workspaces + Files"]
        Export["📤 Export<br/>MD / TXT / JSON"]
        Branch["🌿 Branching<br/>Conversation Forks"]
    end

    subgraph External ["🌐 External Services"]
        OpenRouter["OpenRouter<br/>Coding + Writing LLMs"]
        OpenAI["OpenAI<br/>GPT-4o · DALL-E 3<br/>Whisper · Embeddings · TTS"]
        Tavily["Tavily<br/>Web Search"]
        Sandbox["HuggingFace<br/>Code Sandbox"]
    end

    subgraph Storage ["🗄️ Supabase"]
        DB[("PostgreSQL<br/>Conversations · Messages<br/>Profiles · Memories<br/>Projects · Scores")]
        PGVector[("pgvector<br/>Conversation Embeddings")]
        Auth["Supabase Auth<br/>JWT Verification"]
    end

    Client -->|"SSE Stream + REST"| Backend
    Router -->|"11-tuple flags"| Chat
    Chat --> Agent
    Chat --> Memory
    Chat --> Scores
    Chat --> Embeddings
    Chat --> OpenRouter
    Chat --> OpenAI
    Chat --> Tavily
    Chat --> Sandbox
    Voice --> OpenAI
    Projects --> DB
    Export --> DB
    Branch --> DB
    Backend --> Storage
```

---

## Chat Request Flow

```mermaid
flowchart TD
    A(["User sends message"]) --> B["POST /api/v1/chat"]
    B --> C{"model_id == auto?"}
    C -->|Yes| D["route_message()\nGPT-4o-mini classifies intent\nreturns 11-tuple"]
    C -->|No| E["Use selected model directly"]
    D --> F{"needs_plot?"}
    D --> G{"needs_image?"}
    D --> H{"needs_execution?"}
    D --> I{"needs_agent?"}
    F -->|Yes| J["generate_plot_json()\nTavily + Plotly"] --> Z
    G -->|Yes| K["generate_dalle_image()\nDALL-E 3"] --> Z
    H -->|Yes| L["execute_code()\nHuggingFace Sandbox"] --> Z
    I -->|Yes| M["run_agent()\nMulti-step execution\nStream steps via SSE"] --> Z
    F & G & H & I -->|No| N["Build System Prompt"]
    N --> N1["Template (highest priority)"]
    N1 --> N2["+ Project context\n(instructions + files)"]
    N2 --> N3["+ File upload context"]
    N3 --> N4["+ User profile\n+ Custom instructions"]
    N4 --> N5["+ Memories\n(cross-conversation)"]
    N5 --> N6["+ Web search results"]
    N6 --> O["build_smart_context()\nCompress history if needed"]
    O --> P{"Image uploaded?"}
    P -->|Yes| Q["GPT-4o Vision\nMultimodal message"]
    P -->|No| R["Specialist model\nvia OpenRouter"]
    Q & R --> S["stream_response()\nSSE token stream"]
    S --> Z(["Response delivered\nto client"])
```

---

## Background Task Pipeline

```mermaid
sequenceDiagram
    participant C as Client
    participant H as history.py
    participant T as Title Generator
    participant M as Memory Engine
    participant S as Scoring Engine
    participant E as Embeddings

    C->>H: POST /api/v1/messages (assistant role)
    H->>H: get_messages(conversation_id)

    alt 2nd message (first exchange)
        H-->>T: asyncio.create_task()
        T->>T: GPT-4o-mini generates title
        T->>H: update_conversation_title()
    end

    alt Every 4th message
        H-->>M: asyncio.create_task()
        M->>M: Extract memories via GPT-4o-mini
        M->>M: Store in user_memories table

        H-->>S: asyncio.create_task()
        S->>S: Score conversation (productivity, complexity, satisfaction)
        S->>S: Store in conversation_scores table

        H-->>E: asyncio.create_task()
        E->>E: Generate summary via GPT-4o-mini
        E->>E: Generate embedding via text-embedding-3-small
        E->>E: Store in conversation_embeddings (pgvector)
    end

    H->>C: 200 OK (never blocks)
```

---

## Memory and Personalization Flow

```mermaid
flowchart LR
    A(["User conversation"]) --> B["Every 4th message\ntriggers extraction"]
    B --> C["GPT-4o-mini reads\nlast 10 messages"]
    C --> D["Extracts facts:\nname · role · preferences\nprojects · location · style"]
    D --> E[("user_memories\ntable")]

    F(["New conversation starts"]) --> G["Fetch top 20 memories\nfor this user"]
    G --> H["MEMORY INJECTION PROMPT\ninjected into system prompt"]
    H --> I["Model responds with\nfull user context"]

    J(["User gives feedback\nthumbs down + text"]) --> K["Every 3rd feedback\ntriggers evolution"]
    K --> L["GPT-4o-mini reads\nlast 10 feedbacks"]
    L --> M["Rewrites custom_instructions\nto match preferences"]
    M --> N[("user_profiles\ntable")]
    N --> H
```

---

## Smart Suggestions Data Flow

```mermaid
flowchart TD
    A(["User types in chat input\n4+ characters"]) -->|"150ms debounce"| B["POST /api/v1/suggestions\n{text: string}"]
    B --> C["generate_embedding(text)\ntext-embedding-3-small\n→ vector[1536]"]
    C --> D{"Embeddings exist\nin DB?"}
    D -->|Yes| E["pgvector cosine similarity\nmatch_conversation_embeddings()\nthreshold: 0.4"]
    D -->|No| F["Fallback: title text search\nilike query on conversations"]
    E --> G["Top 3 matches\nwith similarity scores"]
    F --> G
    G --> H(["Suggestion chips\nappear above input"])

    I(["Every 4th message"]) --> J["generate_conversation_summary()\nGPT-4o-mini → 1-2 sentences"]
    J --> K["generate_embedding(summary)\n→ vector[1536]"]
    K --> L[("conversation_embeddings\npgvector table")]
    L --> E
```

---

## Voice Pipeline

```mermaid
sequenceDiagram
    participant U as User (Browser)
    participant F as Frontend
    participant V as voice.py
    participant FF as FFmpeg
    participant W as OpenAI Whisper
    participant T as OpenAI TTS

    Note over U,T: Voice Input Flow
    U->>F: Hold mic button / press Space
    F->>F: MediaRecorder captures audio (webm)
    F->>V: POST /api/v1/voice/transcribe\nmultipart/form-data (audio blob)
    V->>FF: Convert webm → wav\n16kHz mono
    FF->>V: wav bytes
    V->>W: whisper-1 model\nverbose_json response
    W->>V: { text, duration }
    V->>F: { text: "transcribed text" }
    F->>U: Text appears in input field

    Note over U,T: Text to Speech Flow
    U->>F: Click speaker button on message
    F->>V: POST /api/v1/voice/speak\n{ text, voice, speed }
    V->>V: strip_markdown_for_tts()
    V->>T: tts-1 model, nova voice
    T->>V: MP3 audio stream
    V->>F: StreamingResponse (audio/mpeg)
    F->>U: Audio plays in browser\nAnimated bars while playing
```

---

## Project Workspace Flow

```mermaid
flowchart TD
    A(["User creates project"]) --> B["POST /api/v1/projects\n{name, instructions, color}"]
    B --> C[("projects table")]

    D(["User uploads file"]) --> E["POST /api/v1/projects/:id/files\nmultipart/form-data"]
    E --> F{"File type?"}
    F -->|PDF| G["pypdf extracts text"]
    F -->|DOCX| H["python-docx extracts text"]
    F -->|XLSX| I["openpyxl extracts text"]
    F -->|txt/md/py/js| J["UTF-8 decode"]
    G & H & I & J --> K["Truncate to 50k chars"]
    K --> L[("project_files table\nfile_content stored")]

    M(["User links conversation"]) --> N["POST /api/v1/conversations/:id/link-project\n{project_id}"]
    N --> O[("conversations.project_id updated")]

    P(["User sends chat message"]) --> Q{"project_id in request?"}
    Q -->|Yes| R["get_project_context()\nFetch instructions + files"]
    R --> S["Inject into system prompt:\n--- PROJECT CONTEXT ---\nInstructions + file contents\n(3000 chars per file)"]
    S --> T["Model responds with\nfull project awareness"]
    Q -->|No| T
```

---

## Conversation Branching Flow

```mermaid
flowchart TD
    A(["User hovers message\nin chat window"]) --> B["GitBranch icon appears\nin action bar"]
    B --> C["User clicks branch icon"]
    C --> D["Confirmation popup:\nmessage count to copy"]
    D -->|Confirm| E["POST /api/v1/conversations/:id/branch\n{message_index: N}"]
    E --> F["Fetch original conversation\nverify ownership"]
    F --> G["Slice messages 0..N inclusive"]
    G --> H["INSERT new conversation\n{title: 'Branch: Original Title'\nis_branch: true\nparent_conversation_id: original_id}"]
    H --> I["Copy all sliced messages\nto new conversation"]
    I --> J[("Both conversations\nnow in Supabase")]
    J --> K["Return branch_conversation_id\nto frontend"]
    K --> L["Frontend loads\nnew branch conversation"]
    L --> M(["User explores\nnew direction\nOriginal unchanged"])
```

---

## Database Schema

```mermaid
erDiagram
    USERS {
        uuid id PK
        string email
        string created_at
    }
    CONVERSATIONS {
        uuid id PK
        uuid user_id FK
        uuid project_id FK
        uuid parent_conversation_id FK
        string title
        string model_id
        boolean is_branch
        string branch_point_message_id
        timestamp created_at
        timestamp updated_at
    }
    MESSAGES {
        uuid id PK
        uuid conversation_id FK
        string role
        text content
        string model_id
        string routed_to
        string routing_reason
        boolean search_used
        string search_query
        boolean file_used
        string file_name
        timestamp created_at
    }
    USER_PROFILES {
        uuid id PK
        uuid user_id FK
        string display_name
        text about_you
        text custom_instructions
        string response_style
        boolean onboarding_completed
        timestamp updated_at
    }
    USER_MEMORIES {
        uuid id PK
        uuid user_id FK
        text memory
        string category
        int importance
        uuid source_conversation_id FK
        timestamp created_at
    }
    PROJECTS {
        uuid id PK
        uuid user_id FK
        string name
        text description
        text instructions
        string color
        timestamp updated_at
    }
    PROJECT_FILES {
        uuid id PK
        uuid project_id FK
        uuid user_id FK
        string file_name
        string file_type
        int file_size
        text file_content
        timestamp created_at
    }
    MESSAGE_FEEDBACK {
        uuid id PK
        uuid user_id FK
        uuid conversation_id FK
        uuid message_id FK
        int rating
        text feedback_text
        text message_content
        timestamp created_at
    }
    CONVERSATION_SCORES {
        uuid id PK
        uuid user_id FK
        uuid conversation_id FK
        int productivity_score
        int complexity_score
        int satisfaction_score
        string category
        text topics
        int time_saved_minutes
        int message_count
        text summary
        timestamp scored_at
    }
    CONVERSATION_EMBEDDINGS {
        uuid id PK
        uuid conversation_id FK
        uuid user_id FK
        vector embedding
        text content_summary
        timestamp updated_at
    }

    USERS ||--o{ CONVERSATIONS : owns
    USERS ||--o{ USER_PROFILES : has
    USERS ||--o{ USER_MEMORIES : stores
    USERS ||--o{ PROJECTS : creates
    USERS ||--o{ MESSAGE_FEEDBACK : gives
    CONVERSATIONS ||--o{ MESSAGES : contains
    CONVERSATIONS ||--o{ CONVERSATION_SCORES : scored_by
    CONVERSATIONS ||--o{ CONVERSATION_EMBEDDINGS : embedded_in
    CONVERSATIONS }o--|| PROJECTS : linked_to
    CONVERSATIONS }o--|| CONVERSATIONS : branched_from
    PROJECTS ||--o{ PROJECT_FILES : contains
    MESSAGES ||--o{ MESSAGE_FEEDBACK : receives
```

---

## Features

### Core
- **Auto Model Routing** — Classifies every message and routes to the best specialist model
- **Web Search Integration** — Detects when real-time information is needed, fetches via Tavily
- **AI Image Generation** — Creates images via DALL-E 3 from natural language prompts
- **Data Visualization** — Generates interactive Plotly JSON charts from descriptions
- **Code Execution** — Runs Python, JavaScript, TypeScript, and Bash in a sandboxed environment
- **Multi-Step Agent Mode** — Breaks complex tasks into steps and executes them sequentially
- **File Upload and Parsing** — Supports PDF, DOCX, CSV, XLSX, and common code files
- **GPT-4o Vision** — Analyzes images uploaded by the user

### Voice
- **Voice Transcription** — Records audio via MediaRecorder, converts via FFmpeg, transcribes via Whisper
- **Text to Speech** — Converts any response to audio using OpenAI TTS with six premium voices
- **FFmpeg Conversion** — webm/ogg audio converted to 16kHz WAV for optimal Whisper accuracy

### Intelligence
- **Cross-Conversation Memory** — Extracts and injects memories across all user sessions
- **Smart Context Compression** — Summarizes old messages to stay within token limits
- **Prompt Template Library** — Six built-in templates triggered via slash commands
- **Feedback Evolution** — Learns from thumbs up and down to rewrite custom instructions
- **Smart Context Suggestions** — Semantic similarity search using OpenAI embeddings and pgvector
- **Conversation Scoring** — Automatically scores productivity, complexity, and satisfaction per conversation

### Projects
- **Project Workspaces** — Users create projects with custom instructions and uploaded files
- **File Context Injection** — Project file contents are injected into the system prompt automatically
- **Conversation Linking** — Any conversation can be linked to a project
- **Storage Limits** — 5MB per file, 25MB per project, 100MB per user

### Conversations
- **Export** — Download any conversation as Markdown, plain text, or JSON
- **Branching** — Fork any conversation from any message point, original stays intact
- **Search** — Full-text search across titles and message content with snippet extraction
- **Auto Title** — GPT-4o-mini generates a specific title after the first exchange

### Infrastructure
- **Supabase Auth** — JWT verification, per-user data isolation
- **Persistent Storage** — All conversations, messages, memories, scores in Supabase PostgreSQL
- **Streaming SSE** — All responses stream token by token via Server-Sent Events
- **Background Tasks** — Memory extraction, scoring, and embedding run asynchronously
- **Docker Ready** — Single command to run the full backend locally

---

## API Endpoints

### Chat
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/chat` | Send a message, stream a response with routing metadata |
| `GET` | `/api/v1/models` | List all available specialist models |

### Files
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/file/parse` | Upload and parse a file |

### Conversations
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/conversations` | Create a new conversation |
| `GET` | `/api/v1/conversations` | List all conversations for the user |
| `GET` | `/api/v1/conversations/:id` | Get a single conversation |
| `GET` | `/api/v1/conversations/:id/messages` | Get all messages in a conversation |
| `DELETE` | `/api/v1/conversations/:id` | Delete a conversation |
| `POST` | `/api/v1/messages` | Save a message to a conversation |
| `GET` | `/api/v1/search?q=query` | Search conversations and message content |
| `GET` | `/api/v1/conversations/:id/export?format=md\|txt\|json` | Export a conversation |
| `POST` | `/api/v1/conversations/:id/branch` | Branch a conversation from a message index |
| `GET` | `/api/v1/conversations/:id/branches` | Get all branches of a conversation |

### Voice
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/voice/transcribe` | Transcribe audio via Whisper (multipart/form-data) |
| `POST` | `/api/v1/voice/speak` | Convert text to speech, returns MP3 stream |
| `GET` | `/api/v1/voice/voices` | List available TTS voices with descriptions |

### Profile and Memory
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/profile` | Get user profile |
| `POST` | `/api/v1/profile` | Create or update user profile |
| `POST` | `/api/v1/profile/complete-onboarding` | Mark onboarding as complete |
| `GET` | `/api/v1/memories` | Get all memories for the user |
| `DELETE` | `/api/v1/memories` | Delete all memories |
| `POST` | `/api/v1/memories/extract` | Manually trigger memory extraction |

### Projects
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/projects` | List all projects |
| `POST` | `/api/v1/projects` | Create a new project |
| `GET` | `/api/v1/projects/:id` | Get project with files |
| `PATCH` | `/api/v1/projects/:id` | Update project details |
| `DELETE` | `/api/v1/projects/:id` | Delete project and all its files |
| `POST` | `/api/v1/projects/:id/files` | Upload a file to a project |
| `GET` | `/api/v1/projects/:id/files` | List files in a project |
| `DELETE` | `/api/v1/projects/:id/files/:file_id` | Delete a project file |
| `POST` | `/api/v1/conversations/:id/link-project` | Link a conversation to a project |
| `GET` | `/api/v1/projects/:id/conversations` | Get conversations linked to a project |

### Feedback and Scores
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/feedback` | Submit message feedback |
| `GET` | `/api/v1/feedback/stats` | Get feedback statistics |
| `GET` | `/api/v1/scores/summary` | Get productivity dashboard summary |
| `GET` | `/api/v1/scores/recent` | Get recent conversation scores |
| `GET` | `/api/v1/scores/conversation/:id` | Get score for a specific conversation |

### Suggestions
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/suggestions` | Get smart context suggestions while typing |
| `POST` | `/api/v1/suggestions/embed-all` | Bulk embed all conversations |
| `POST` | `/api/v1/suggestions/embed-conversation` | Embed a single conversation |

### Sandbox
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/sandbox/execute` | Execute code in the sandbox |

### Templates
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/templates` | List all prompt templates |
| `GET` | `/api/v1/templates/:id` | Get a specific template |

### Demo
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/demo/chat` | Public demo endpoint, no auth, rate limited |
| `GET` | `/api/v1/demo/status` | Check demo usage for current IP |

---

## Chat Request and Response

### Request
```json
{
  "message": "write a binary search in Python",
  "model_id": "auto",
  "conversation_history": [
    { "role": "user", "content": "..." },
    { "role": "assistant", "content": "..." }
  ],
  "user_id": "uuid",
  "file_name": "data.csv",
  "file_type": "csv",
  "file_content": "...",
  "image_base64": "...",
  "image_media_type": "image/jpeg",
  "active_template": "code-review",
  "project_id": "uuid"
}
```

`model_id` can be `"auto"`, `"coding"`, or `"writing"`.

### SSE Event Types
```
metadata         — routing info, model name, flags
token            — streaming text chunk
agent_plan       — list of step titles and total count
agent_step_start — step number and title
agent_step_done  — step completed
done             — stream complete
error            — error message
```

### Metadata Event
```json
{
  "type": "metadata",
  "model_name": "Coding Assistant",
  "model_id": "coding",
  "routed_to": "coding",
  "routing_reason": "The request involves code generation.",
  "search_used": false,
  "file_used": false,
  "image_used": false,
  "is_agent": false,
  "active_template": null,
  "project_id": null
}
```

---

## Getting Started

### Prerequisites
- Docker and Docker Compose
- OpenRouter API key (free at [openrouter.ai](https://openrouter.ai))
- OpenAI API key (for DALL-E 3, Whisper, TTS, and embeddings)
- Tavily API key (free at [tavily.com](https://tavily.com))
- Supabase project (free at [supabase.com](https://supabase.com))

### 1. Clone the repository
```bash
git clone https://github.com/NorthCommits/Prism-backend.git
cd Prism-backend
```

### 2. Set up environment variables
```bash
cp .env.example .env
```

Edit `.env` with your keys:
```dotenv
OPENROUTER_API_KEY=your_openrouter_api_key
OPENAI_API_KEY=your_openai_api_key
TAVILY_API_KEY=your_tavily_api_key
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_service_role_key
SANDBOX_URL=https://your-sandbox.hf.space
```

### 3. Set up Supabase database

Run the following SQL in your Supabase SQL editor:

```sql
-- Core tables
CREATE TABLE conversations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title TEXT NOT NULL,
  model_id TEXT NOT NULL DEFAULT 'auto',
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  project_id UUID,
  parent_conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
  branch_point_message_id TEXT,
  is_branch BOOLEAN DEFAULT FALSE,
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

CREATE TABLE user_profiles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID UNIQUE REFERENCES auth.users(id) ON DELETE CASCADE,
  display_name TEXT,
  about_you TEXT,
  custom_instructions TEXT,
  response_style TEXT DEFAULT 'balanced',
  onboarding_completed BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE user_memories (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  memory TEXT NOT NULL,
  category TEXT,
  importance INTEGER CHECK (importance BETWEEN 1 AND 5),
  source_conversation_id UUID,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT,
  instructions TEXT,
  color TEXT DEFAULT '#8b5cf6',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE project_files (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  file_name TEXT NOT NULL,
  file_type TEXT NOT NULL,
  file_size INTEGER NOT NULL,
  file_content TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE message_feedback (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
  message_id UUID,
  rating INTEGER CHECK (rating IN (1, -1)),
  feedback_text TEXT,
  message_content TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE conversation_scores (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
  productivity_score INTEGER CHECK (productivity_score BETWEEN 1 AND 10),
  complexity_score INTEGER CHECK (complexity_score BETWEEN 1 AND 10),
  satisfaction_score INTEGER CHECK (satisfaction_score BETWEEN 1 AND 10),
  category TEXT DEFAULT 'general',
  topics TEXT[],
  time_saved_minutes INTEGER DEFAULT 0,
  message_count INTEGER DEFAULT 0,
  summary TEXT,
  scored_at TIMESTAMPTZ DEFAULT NOW(),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE conversation_embeddings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  embedding vector(1536),
  content_summary TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_messages_conversation_id ON messages(conversation_id);
CREATE INDEX idx_conversations_user_id ON conversations(user_id);
CREATE INDEX idx_conversations_project_id ON conversations(project_id);
CREATE INDEX idx_conversations_parent_id ON conversations(parent_conversation_id);
CREATE INDEX idx_projects_user_id ON projects(user_id);
CREATE INDEX idx_project_files_project_id ON project_files(project_id);
CREATE INDEX idx_conversation_scores_user_id ON conversation_scores(user_id);
CREATE INDEX idx_conversation_embeddings_user_id ON conversation_embeddings(user_id);
CREATE INDEX idx_conversation_embeddings_vector
  ON conversation_embeddings
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

CREATE OR REPLACE FUNCTION match_conversation_embeddings(
  query_embedding vector(1536),
  match_user_id UUID,
  match_threshold float DEFAULT 0.4,
  match_count int DEFAULT 3
)
RETURNS TABLE (
  conversation_id UUID,
  content_summary TEXT,
  similarity float
)
LANGUAGE plpgsql AS $$
BEGIN
  RETURN QUERY
  SELECT
    ce.conversation_id,
    ce.content_summary,
    1 - (ce.embedding <=> query_embedding) AS similarity
  FROM conversation_embeddings ce
  WHERE ce.user_id = match_user_id
    AND 1 - (ce.embedding <=> query_embedding) > match_threshold
  ORDER BY ce.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;
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
Prism-backend/
├── main.py                    # FastAPI app entry point, all routers registered
├── requirements.txt           # Python dependencies
├── Dockerfile                 # Includes FFmpeg for audio conversion
├── docker-compose.yml
├── .env                       # Environment variables (never commit this)
├── models/
│   ├── config.py              # Model registry
│   └── router_config.py       # Router system prompt
├── routes/
│   ├── chat.py                # Main chat endpoint, full routing pipeline
│   ├── router.py              # Intent classification, returns 11-tuple
│   ├── search.py              # Tavily web search
│   ├── image.py               # DALL-E 3 and Plotly JSON generation
│   ├── sandbox.py             # Code execution via HuggingFace sandbox
│   ├── file.py                # File parsing
│   ├── history.py             # Conversation CRUD, search, export, branching
│   ├── profile.py             # User profile and custom instructions
│   ├── memory.py              # Cross-conversation memory extraction
│   ├── agent.py               # Multi-step agent planner and executor
│   ├── templates.py           # Prompt template library
│   ├── feedback.py            # Message feedback and prompt evolution
│   ├── scores.py              # Conversation productivity scoring
│   ├── suggestions.py         # Smart context suggestions via embeddings
│   ├── projects.py            # Project workspaces and file management
│   ├── voice.py               # Whisper transcription and OpenAI TTS
│   └── demo.py                # Public demo endpoint
└── db/
    ├── supabase.py            # Supabase client singleton
    ├── auth.py                # JWT token verification
    ├── conversations.py       # Conversation DB operations
    └── messages.py            # Message DB operations
```

---

## Adding a New Specialist Model

Adding a new model takes less than a minute. Open `models/config.py` and add an entry:

```python
"summarization": ModelConfig(
    name="Summarization Assistant",
    description="Specialized for summarizing long documents.",
    openrouter_model="openai/gpt-4o-mini",
    system_prompt="You are an expert at summarizing content concisely..."
)
```

The router will automatically start sending relevant queries to it.

---

## Background Tasks

Several features run silently in the background after every assistant message:

| Task | Trigger | What it does |
|------|---------|--------------|
| Auto Title | 2nd message | Generates a specific conversation title via GPT-4o-mini |
| Memory Extraction | Every 4th message | Extracts facts about the user and stores them |
| Conversation Scoring | Every 4th message | Scores productivity, complexity, and satisfaction |
| Embedding Storage | Every 4th message | Generates and stores a vector embedding for suggestions |

All tasks use `asyncio.create_task` so they never block the response stream.

---

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `OPENROUTER_API_KEY` | OpenRouter API key for model access | Yes |
| `OPENAI_API_KEY` | OpenAI API key for DALL-E 3, Whisper, TTS, embeddings | Yes |
| `TAVILY_API_KEY` | Tavily API key for web search | Yes |
| `SUPABASE_URL` | Your Supabase project URL | Yes |
| `SUPABASE_KEY` | Supabase service role key | Yes |
| `SANDBOX_URL` | HuggingFace sandbox URL for code execution | Yes |

---

## Tech Stack

| Technology | Purpose |
|------------|---------|
| **FastAPI** | High-performance async API framework |
| **OpenRouter** | Unified API gateway for LLMs |
| **GPT-4o-mini** | Intent classification, routing, scoring, titles, memory extraction |
| **GPT-4o** | Vision analysis for uploaded images |
| **DALL-E 3** | AI image generation |
| **Whisper** | Speech to text transcription |
| **OpenAI TTS** | Text to speech with six premium voices |
| **text-embedding-3-small** | Conversation embeddings for smart suggestions |
| **Tavily** | Real-time web search |
| **Plotly** | Interactive data visualization |
| **FFmpeg** | Audio format conversion (webm to wav) |
| **Supabase** | PostgreSQL database and authentication |
| **pgvector** | Vector similarity search for suggestions |
| **Docker** | Containerization |
| **HuggingFace Spaces** | Sandboxed code execution |

---

## Contributing

Contributions are welcome. Please feel free to open an issue or submit a pull request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feat/amazing-feature`)
3. Commit your changes (`git commit -m 'feat: add amazing feature'`)
4. Push to the branch (`git push origin feat/amazing-feature`)
5. Open a Pull Request

---

## License

MIT License — free to use in your own projects.

---

<p align="center">Built by <a href="https://github.com/NorthCommits">NorthCommits</a></p>