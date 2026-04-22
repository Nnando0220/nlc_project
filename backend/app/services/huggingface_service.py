from __future__ import annotations

from app.core.config import settings
from app.services.openrouter_service import OpenRouterService


class HuggingFaceService(OpenRouterService):
    # Inicializa o adaptador do Hugging Face reaproveitando a base comum.
    def __init__(self) -> None:
        super().__init__(
            provider_name="huggingface",
            model_name=settings.huggingface_model,
            bulk_model_name=settings.huggingface_bulk_model or settings.huggingface_model,
            fallback_models=settings.huggingface_fallback_models,
            bulk_fallback_models=settings.huggingface_fallback_models,
            api_key=settings.huggingface_api_key,
            api_base_url=settings.huggingface_api_url,
            site_url="",
            app_name="",
            supports_combined_fallback_route=False,
        )
