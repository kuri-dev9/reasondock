from fastapi import APIRouter
import httpx

from app.config import settings

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("")
async def list_models():
    models = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(f"{settings.ollama_base_url}/api/tags")
        data = response.json()
        models.extend(
            {
                "provider": "ollama",
                "name": m["name"],
                "display": m["name"],
                "available": True,
                "size": m.get("size", 0),
                "modified_at": m.get("modified_at", ""),
            }
            for m in data.get("models", [])
        )
    models.append({
        "provider": "openai",
        "name": settings.openai_model,
        "display": settings.openai_model.removeprefix("openai/"),
        "available": bool(settings.openai_api_key),
    })
    models.append({
        "provider": "anthropic",
        "name": settings.anthropic_model,
        "display": settings.anthropic_model.removeprefix("anthropic/"),
        "available": bool(settings.anthropic_api_key),
    })
    return models
