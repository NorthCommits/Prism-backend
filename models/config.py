from pydantic import BaseModel
from typing import Dict


class ModelConfig(BaseModel):
    name: str
    description: str
    openrouter_model: str
    system_prompt: str


MODEL_REGISTRY: Dict[str, ModelConfig] = {
    "coding": ModelConfig(
        name="Coding Assistant",
        description="Specialized for code generation, debugging, and technical problems.",
        openrouter_model="openai/gpt-4o-mini",
        system_prompt=(
            "You are an expert software engineer. "
            "Help the user with coding problems, debugging, code reviews, and technical explanations. "
            "Always write clean, well-commented code. Prefer concise and correct solutions."
        ),
    ),
    "writing": ModelConfig(
        name="Writing Assistant",
        description="Specialized for writing, summarization, and general language tasks.",
        openrouter_model="openai/gpt-4o-mini",
        system_prompt=(
            "You are a professional writing assistant. "
            "Help the user with writing, editing, summarizing, and general language tasks. "
            "Keep your tone clear, concise, and natural."
        ),
    ),
}