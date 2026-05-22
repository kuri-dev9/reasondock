from fastapi import APIRouter
import httpx

from app.config import settings

router = APIRouter(prefix="/api/models", tags=["models"])

# 임베딩 전용 모델 패밀리
EMBEDDING_FAMILIES = {"bert", "nomic", "mxbai", "clip"}


def _is_embedding(model: dict) -> bool:
    details = model.get("details", {})
    family = str(details.get("family", "")).lower()
    families = [str(f).lower() for f in details.get("families", [])]
    all_families = {family} | set(families)
    return bool(all_families & EMBEDDING_FAMILIES)


@router.get("")
async def list_models():
    models = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(f"{settings.ollama_base_url}/api/tags")
        data = response.json()
        for m in data.get("models", []):
            embedding = _is_embedding(m)
            models.append({
                "provider": "ollama",
                "name": m["name"],
                "display": m["name"],
                "available": not embedding,
                "embedding": embedding,
                "size": m.get("size", 0),
                "modified_at": m.get("modified_at", ""),
                "family": m.get("details", {}).get("family", ""),
            })
    models.append({
        "provider": "openai",
        "name": settings.openai_model,
        "display": settings.openai_model.removeprefix("openai/"),
        "available": bool(settings.openai_api_key),
        "embedding": False,
    })
    models.append({
        "provider": "anthropic",
        "name": settings.anthropic_model,
        "display": settings.anthropic_model.removeprefix("anthropic/"),
        "available": bool(settings.anthropic_api_key),
        "embedding": False,
    })
    return models
