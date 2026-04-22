from __future__ import annotations

from app.core.config import settings
from app.services.openrouter_service import OpenRouterService


class GroqService(OpenRouterService):
    # Inicializa o adaptador do Groq reaproveitando a base do OpenRouterService.
    def __init__(self) -> None:
        super().__init__(
            provider_name="groq",
            model_name=settings.groq_model,
            bulk_model_name=settings.groq_bulk_model or settings.groq_model,
            fallback_models=settings.groq_fallback_models,
            bulk_fallback_models=settings.groq_fallback_models,
            api_key=settings.groq_api_key,
            api_base_url=settings.groq_api_url,
            site_url="",
            app_name="",
            supports_combined_fallback_route=False,
        )
