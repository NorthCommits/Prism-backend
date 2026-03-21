from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from routes.chat import router as chat_router
from routes.file import router as file_router
from routes.history import router as history_router
from routes.profile import router as profile_router
from routes.memory import router as memory_router
from routes.templates import router as templates_router


load_dotenv()

app = FastAPI(
    title="Prism API",
    description="A copilot for specialized small language models.",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router, prefix="/api/v1")
app.include_router(file_router, prefix="/api/v1")
app.include_router(history_router, prefix="/api/v1")
app.include_router(profile_router, prefix="/api/v1")
app.include_router(memory_router, prefix="/api/v1")
app.include_router(templates_router, prefix="/api/v1")

@app.get("/")
async def root():
    return {"status": "ok", "message": "Prism API is running."}


@app.get("/api/v1/models")
async def list_models():
    from models.config import MODEL_REGISTRY
    return {
        model_id: {
            "name": config.name,
            "description": config.description
        }
        for model_id, config in MODEL_REGISTRY.items()
    }