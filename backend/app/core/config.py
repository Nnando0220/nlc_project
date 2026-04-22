from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    app_name: str = Field(validation_alias="APP_NAME")
    environment: str = Field(validation_alias="ENVIRONMENT")
    database_url: str = Field(validation_alias="DATABASE_URL")
    openrouter_model: str = "inclusionai/ling-2.6-flash:free"
    openrouter_bulk_model: str = "inclusionai/ling-2.6-flash:free"
    openrouter_api_key: str = Field(default="", validation_alias="OPENROUTER_API_KEY")
    openrouter_api_url: str = "https://openrouter.ai/api/v1/chat/completions"
    openrouter_prompt_version: str = "nf-audit-v1"
    openrouter_profile: str = "bulk_all"
    openrouter_processing_mode: str = "bulk"
    openrouter_analysis_strategy: str = "all"
    openrouter_batch_size: int = 12
    openrouter_target_prompt_tokens: int = 22000
    openrouter_max_document_text_chars: int = 2000
    openrouter_dynamic_tuning_enabled: bool = True
    openrouter_dynamic_batch_size_max: int = 12
    openrouter_dynamic_target_prompt_tokens_max: int = 22000
    openrouter_dynamic_requests_per_minute_max: int = 12
    openrouter_dynamic_max_document_text_chars_min: int = 900
    openrouter_fallback_models: list[str] = Field(
        default_factory=lambda: [
            "nvidia/nemotron-3-super-120b-a12b:free",
            "meta-llama/llama-3.3-70b-instruct:free",
        ],
    )
    openrouter_bulk_fallback_models: list[str] = Field(
        default_factory=lambda: [
            "nvidia/nemotron-3-super-120b-a12b:free",
            "meta-llama/llama-3.3-70b-instruct:free",
        ],
    )
    openrouter_requests_per_minute: int = 12
    openrouter_max_retries: int = 0
    openrouter_initial_backoff_seconds: float = 1
    openrouter_backoff_multiplier: float = 2
    openrouter_max_backoff_seconds: float = 4
    groq_model: str = "llama-3.3-70b-versatile"
    groq_bulk_model: str = "llama-3.3-70b-versatile"
    groq_api_key: str = Field(default="", validation_alias="GROQ_API_KEY")
    groq_api_url: str = "https://api.groq.com/openai/v1/chat/completions"
    groq_fallback_models: list[str] = Field(default_factory=list)
    huggingface_model: str = "meta-llama/Llama-3.1-8B-Instruct:cerebras"
    huggingface_bulk_model: str = "meta-llama/Llama-3.1-8B-Instruct:cerebras"
    huggingface_api_key: str = Field(default="", validation_alias="HUGGINGFACE_API_KEY")
    huggingface_api_url: str = "https://router.huggingface.co/v1/chat/completions"
    huggingface_fallback_models: list[str] = Field(default_factory=list)
    require_https: bool = Field(validation_alias="REQUIRE_HTTPS")
    rate_limit_max_requests: int = Field(validation_alias="RATE_LIMIT_MAX_REQUESTS")
    rate_limit_window_seconds: int = Field(validation_alias="RATE_LIMIT_WINDOW_SECONDS")
    allowed_hosts: list[str] = Field(validation_alias="ALLOWED_HOSTS")
    cors_allowed_origins: list[str] = Field(default_factory=list, validation_alias="CORS_ALLOWED_ORIGINS")
    processing_max_workers: int = Field(validation_alias="PROCESSING_MAX_WORKERS")
    upload_max_file_size_bytes: int = Field(validation_alias="UPLOAD_MAX_FILE_SIZE_BYTES")
    upload_max_total_size_bytes: int = Field(validation_alias="UPLOAD_MAX_TOTAL_SIZE_BYTES")

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
