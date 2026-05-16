from __future__ import annotations

from app.adapters.anthropic import AnthropicAdapter
from app.adapters.base import ModelAdapter
from app.adapters.ollama import OllamaAdapter
from app.adapters.openai import OpenAIAdapter
from app.config import settings


def get_adapter(model: str) -> ModelAdapter:
    if model.startswith("openai/"):
        return OpenAIAdapter(api_key=settings.openai_api_key)
    if model.startswith("anthropic/"):
        return AnthropicAdapter(api_key=settings.anthropic_api_key)
    return OllamaAdapter(base_url=settings.ollama_base_url)
