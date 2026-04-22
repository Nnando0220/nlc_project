from __future__ import annotations

import json
import logging
import random
import re
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

import httpx

from app.core.config import settings

logger = logging.getLogger("app.openrouter")
OPENROUTER_MAX_COMBINED_MODELS = 3
OPENROUTER_MODEL_ALIASES = {
    "openrouter/elephant-alpha": "inclusionai/ling-2.6-flash:free",
}
OPENROUTER_MODEL_SUGGESTION_PATTERN = re.compile(r"https?://openrouter\.ai/(?P<model>[\w.-]+/[\w.:-]+)")


class LLMProcessingCancelled(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ProviderErrorInfo:
    error_code: str
    http_status: int | None
    retryable: bool
    provider: str
    technical_message: str
    user_message: str


class ProviderRequestError(RuntimeError):
    # Encapsula a falha normalizada do provedor em uma excecao unica.
    def __init__(self, info: ProviderErrorInfo) -> None:
        self.info = info
        super().__init__(info.technical_message)

    @property
    # Retorna o codigo interno da falha.
    def error_code(self) -> str:
        return self.info.error_code

    @property
    # Retorna o status HTTP associado, quando existir.
    def http_status(self) -> int | None:
        return self.info.http_status

    @property
    # Informa se a falha permite nova tentativa.
    def retryable(self) -> bool:
        return self.info.retryable

    @property
    # Retorna o nome do provedor que gerou a falha.
    def provider(self) -> str:
        return self.info.provider

    @property
    # Retorna a mensagem tecnica registrada em log.
    def technical_message(self) -> str:
        return self.info.technical_message

    @property
    # Retorna a mensagem segura para exibir na aplicacao.
    def user_message(self) -> str:
        return self.info.user_message

    # Converte a falha para o payload salvo na auditoria.
    def to_payload(self) -> dict[str, object]:
        return {
            "error_code": self.error_code,
            "http_status": self.http_status,
            "retryable": self.retryable,
            "provider": self.provider,
            "technical_message": self.technical_message,
            "user_message": self.user_message,
        }


class OpenRouterService:
    # Inicializa o cliente do provedor com defaults internos e a chave vinda do .env.
    def __init__(
        self,
        *,
        provider_name: str = "openrouter",
        model_name: str | None = None,
        bulk_model_name: str | None = None,
        fallback_models: list[str] | None = None,
        bulk_fallback_models: list[str] | None = None,
        api_key: str | None = None,
        api_base_url: str | None = None,
        prompt_version: str | None = None,
        profile: str | None = None,
        processing_mode: str | None = None,
        analysis_strategy: str | None = None,
        batch_size: int | None = None,
        target_prompt_tokens: int | None = None,
        max_document_text_chars: int | None = None,
        dynamic_tuning_enabled: bool | None = None,
        dynamic_batch_size_max: int | None = None,
        dynamic_target_prompt_tokens_max: int | None = None,
        dynamic_requests_per_minute_max: int | None = None,
        dynamic_max_document_text_chars_min: int | None = None,
        requests_per_minute: int | None = None,
        max_retries: int | None = None,
        initial_backoff_seconds: float | None = None,
        backoff_multiplier: float | None = None,
        max_backoff_seconds: float | None = None,
        site_url: str | None = None,
        app_name: str | None = None,
        supports_combined_fallback_route: bool = True,
    ) -> None:
        self.provider_name = provider_name
        self.supports_combined_fallback_route = supports_combined_fallback_route
        resolved_profile = profile if profile is not None else settings.openrouter_profile
        resolved_processing_mode = (
            processing_mode
            if processing_mode is not None
            else settings.openrouter_processing_mode
        )
        resolved_analysis_strategy = (
            analysis_strategy
            if analysis_strategy is not None
            else settings.openrouter_analysis_strategy
        )
        resolved_batch_size = batch_size if batch_size is not None else settings.openrouter_batch_size
        resolved_target_prompt_tokens = (
            target_prompt_tokens
            if target_prompt_tokens is not None
            else settings.openrouter_target_prompt_tokens
        )
        resolved_max_document_text_chars = (
            max_document_text_chars
            if max_document_text_chars is not None
            else settings.openrouter_max_document_text_chars
        )
        resolved_dynamic_tuning_enabled = (
            dynamic_tuning_enabled
            if dynamic_tuning_enabled is not None
            else settings.openrouter_dynamic_tuning_enabled
        )
        resolved_dynamic_batch_size_max = (
            dynamic_batch_size_max
            if dynamic_batch_size_max is not None
            else settings.openrouter_dynamic_batch_size_max
        )
        resolved_dynamic_target_prompt_tokens_max = (
            dynamic_target_prompt_tokens_max
            if dynamic_target_prompt_tokens_max is not None
            else settings.openrouter_dynamic_target_prompt_tokens_max
        )
        resolved_dynamic_requests_per_minute_max = (
            dynamic_requests_per_minute_max
            if dynamic_requests_per_minute_max is not None
            else settings.openrouter_dynamic_requests_per_minute_max
        )
        resolved_dynamic_max_document_text_chars_min = (
            dynamic_max_document_text_chars_min
            if dynamic_max_document_text_chars_min is not None
            else settings.openrouter_dynamic_max_document_text_chars_min
        )
        resolved_requests_per_minute = (
            requests_per_minute
            if requests_per_minute is not None
            else settings.openrouter_requests_per_minute
        )
        resolved_max_retries = (
            max_retries if max_retries is not None else settings.openrouter_max_retries
        )
        resolved_initial_backoff_seconds = (
            initial_backoff_seconds
            if initial_backoff_seconds is not None
            else settings.openrouter_initial_backoff_seconds
        )
        resolved_backoff_multiplier = (
            backoff_multiplier
            if backoff_multiplier is not None
            else settings.openrouter_backoff_multiplier
        )
        resolved_max_backoff_seconds = (
            max_backoff_seconds
            if max_backoff_seconds is not None
            else settings.openrouter_max_backoff_seconds
        )

        self.model_name = model_name or settings.openrouter_model
        self.bulk_model_name = bulk_model_name or settings.openrouter_bulk_model or self.model_name
        self.fallback_models = [item.strip() for item in (fallback_models if fallback_models is not None else settings.openrouter_fallback_models) if item.strip()]
        self.bulk_fallback_models = [item.strip() for item in (bulk_fallback_models if bulk_fallback_models is not None else settings.openrouter_bulk_fallback_models) if item.strip()]
        self.api_key = api_key if api_key is not None else settings.openrouter_api_key
        self.api_base_url = api_base_url if api_base_url is not None else settings.openrouter_api_url
        self.prompt_version = prompt_version if prompt_version is not None else settings.openrouter_prompt_version
        self.profile = resolved_profile.lower().strip()
        self.processing_mode = resolved_processing_mode.lower().strip()
        self.analysis_strategy = resolved_analysis_strategy.lower().strip()
        self.bulk_batch_size = max(resolved_batch_size, 1)
        self.target_prompt_tokens = max(resolved_target_prompt_tokens, 1000)
        self.max_document_text_chars = max(resolved_max_document_text_chars, 200)
        self.dynamic_tuning_enabled = resolved_dynamic_tuning_enabled
        self.dynamic_batch_size_max = resolved_dynamic_batch_size_max
        self.dynamic_target_prompt_tokens_max = resolved_dynamic_target_prompt_tokens_max
        self.dynamic_requests_per_minute_max = resolved_dynamic_requests_per_minute_max
        self.dynamic_max_document_text_chars_min = resolved_dynamic_max_document_text_chars_min
        self.requests_per_minute = max(resolved_requests_per_minute, 1)
        self.max_retries = max(resolved_max_retries, 0)
        self.initial_backoff_seconds = max(resolved_initial_backoff_seconds, 0.1)
        self.backoff_multiplier = max(resolved_backoff_multiplier, 1.0)
        self.max_backoff_seconds = max(resolved_max_backoff_seconds, self.initial_backoff_seconds)
        self.site_url = (site_url or "").strip()
        self.app_name = (app_name if app_name is not None else settings.app_name).strip()
        self._rate_window_seconds = 60.0
        self._request_timestamps: deque[float] = deque()
        self._rate_lock = Lock()
        self._http_client = self._build_http_client()
        self._apply_profile_defaults()
        self.model_name = self._normalize_model_alias(self.model_name)
        self.bulk_model_name = self._normalize_model_alias(self.bulk_model_name or self.model_name)
        self.fallback_models = self._normalize_model_list(self.fallback_models)
        self.bulk_fallback_models = self._normalize_model_list(self.bulk_fallback_models)
        self._normalize_dynamic_limits()

    # Retorna o tamanho de micro-lote calculado para o volume atual.
    def get_processing_chunk_size(self, total_documents: int | None = None) -> int:
        tuning = self._build_runtime_tuning(total_documents)
        return max(int(tuning["batch_size"]), 1)

    # Expoe o tuning operacional efetivo para o lote corrente.
    def get_runtime_tuning(self, total_documents: int | None = None) -> dict[str, int | float]:
        return dict(self._build_runtime_tuning(total_documents))

    # Fecha o cliente HTTP compartilhado do provedor.
    def close(self) -> None:
        self._http_client.close()

    # Aplica aliases locais para modelos que mudaram de nome no provedor.
    def _normalize_model_alias(self, model_name: str) -> str:
        normalized_name = model_name.strip()
        aliased_name = OPENROUTER_MODEL_ALIASES.get(normalized_name, normalized_name)
        if aliased_name != normalized_name:
            logger.info(
                "openrouter_model_alias_redirect from=%s to=%s",
                normalized_name,
                aliased_name,
            )
        return aliased_name

    # Normaliza listas de modelos removendo duplicidades e aliases antigos.
    def _normalize_model_list(self, model_names: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in model_names:
            normalized_name = self._normalize_model_alias(item)
            if normalized_name and normalized_name not in normalized:
                normalized.append(normalized_name)
        return normalized

    # Tenta extrair do erro do provedor uma sugestao explicita de modelo.
    def _extract_model_suggestion(self, response_body: str) -> str | None:
        match = OPENROUTER_MODEL_SUGGESTION_PATTERN.search(response_body)
        if not match:
            return None
        return match.group("model").strip() or None

    # Cria o cliente HTTP com timeout e pool adequados para lotes.
    def _build_http_client(self) -> httpx.Client:
        client_options = {
            "timeout": httpx.Timeout(45.0),
            "limits": httpx.Limits(max_keepalive_connections=20, max_connections=50),
        }
        try:
            return httpx.Client(http2=True, **client_options)
        except ImportError:
            logger.info("openrouter_http2_unavailable falling back to HTTP/1.1")
            return httpx.Client(**client_options)

    # Ajusta limites dinamicos para nunca ficarem abaixo do minimo aceitavel.
    def _normalize_dynamic_limits(self) -> None:
        self.dynamic_batch_size_max = max(self.dynamic_batch_size_max or self.bulk_batch_size, self.bulk_batch_size)
        self.dynamic_target_prompt_tokens_max = max(
            self.dynamic_target_prompt_tokens_max or self.target_prompt_tokens,
            self.target_prompt_tokens,
        )
        self.dynamic_requests_per_minute_max = max(
            self.dynamic_requests_per_minute_max or self.requests_per_minute,
            self.requests_per_minute,
        )
        if self.dynamic_max_document_text_chars_min <= 0:
            self.dynamic_max_document_text_chars_min = min(900, self.max_document_text_chars)
        self.dynamic_max_document_text_chars_min = min(
            max(self.dynamic_max_document_text_chars_min, 200),
            self.max_document_text_chars,
        )

    # Aplica presets operacionais prontos para perfis conhecidos.
    def _apply_profile_defaults(self) -> None:
        if self.profile == "bulk_fast":
            self.processing_mode = "bulk"
            self.analysis_strategy = "all"
            if self.provider_name == "openrouter":
                self.model_name = "nvidia/nemotron-3-super-120b-a12b:free"
                self.bulk_model_name = self.model_name
                self.fallback_models = [
                    "meta-llama/llama-3.3-70b-instruct:free",
                    "z-ai/glm-4.5-air:free",
                    "openrouter/free",
                ]
                self.bulk_fallback_models = self.fallback_models.copy()
            self.bulk_batch_size = 8
            self.target_prompt_tokens = 22000
            self.max_document_text_chars = 900
            self.requests_per_minute = 8
            self.max_retries = 0
            self.initial_backoff_seconds = 1
            self.backoff_multiplier = 2
            self.max_backoff_seconds = 4
        elif self.profile == "demo_quality":
            self.processing_mode = "demo"
            self.analysis_strategy = "all"
            if self.provider_name == "openrouter":
                self.model_name = "openai/gpt-oss-120b:free"
                self.bulk_model_name = self.model_name
                self.fallback_models = [
                    "meta-llama/llama-3.3-70b-instruct:free",
                    "z-ai/glm-4.5-air:free",
                    "openrouter/free",
                ]
                self.bulk_fallback_models = self.fallback_models.copy()
            self.bulk_batch_size = 1
            self.target_prompt_tokens = 12000
            self.max_document_text_chars = 1400
            self.requests_per_minute = 4
            self.max_retries = 1
            self.initial_backoff_seconds = 2
            self.backoff_multiplier = 2
            self.max_backoff_seconds = 8
        elif self.profile == "bulk_selective":
            self.processing_mode = "bulk"
            self.analysis_strategy = "selective"
        elif self.profile == "bulk_all":
            self.processing_mode = "bulk"
            self.analysis_strategy = "all"
        elif self.profile == "demo":
            self.processing_mode = "demo"
            self.analysis_strategy = "all"

    # Decide se o documento precisa de reforco por IA.
    def should_use_llm_for_document(
        self,
        *,
        decode_status: str,
        parse_status: str,
        missing_fields: list[str],
        truncated_fields: list[str],
    ) -> bool:
        if not self.api_key:
            return False
        if self.analysis_strategy == "all":
            return True
        return (
            decode_status != "success"
            or parse_status != "success"
            or bool(missing_fields)
            or bool(truncated_fields)
        )

    # Monta um resultado local padrao quando a IA nao for usada.
    def build_local_parser_result(
        self,
        *,
        parsed_fields: dict[str, object],
        missing_fields: list[str],
        truncated_fields: list[str],
        message: str,
    ) -> dict[str, object]:
        return {
            "provider": "local-parser",
            "model": "deterministic-parser",
            "prompt_version": "deterministic-v1",
            "classification": "nota_fiscal",
            "risk_score": None,
            "summary": message,
            "inconsistencies": {},
            "confidence_overall": 0.95,
            "raw_response": None,
            "extraction_status": "skipped",
            "missing_fields": missing_fields,
            "truncated_fields": truncated_fields,
            "normalized_fields": parsed_fields,
        }

    # Processa um conjunto de documentos com retry, fallback e auditoria.
    def analyze_invoices_batch(
        self,
        documents: list[dict[str, object]],
        *,
        force_single: bool = False,
        cancel_checker: Callable[[], bool] | None = None,
        request_event_callback: Callable[[dict[str, object]], None] | None = None,
        total_documents: int | None = None,
    ) -> dict[str, dict[str, object]]:
        if not documents:
            return {}

        if not self.api_key:
            return {
                str(item["document_id"]): self._fallback_invoice_result(
                    parsed_fields=item["parsed_fields"] if isinstance(item.get("parsed_fields"), dict) else {},
                    missing_fields=item["missing_fields"] if isinstance(item.get("missing_fields"), list) else [],
                    truncated_fields=item["truncated_fields"] if isinstance(item.get("truncated_fields"), list) else [],
                    message=f"API key do provedor {self.provider_name} nao configurada.",
                    requested_model=self.model_name,
                    attempted_models=[self.model_name],
                )
                for item in documents
            }

        runtime_tuning = self._build_runtime_tuning(total_documents)
        chunk_size = 1 if force_single or self.processing_mode == "demo" else int(runtime_tuning["batch_size"])
        results: dict[str, dict[str, object]] = {}
        default_requested_model = self.model_name if chunk_size == 1 else self.bulk_model_name
        default_fallback_models = self.fallback_models if chunk_size == 1 else self.bulk_fallback_models
        default_attempted_models = [item for item in [default_requested_model, *default_fallback_models] if item]

        for chunk in self._chunk_documents(
            documents,
            chunk_size,
            max_document_text_chars=int(runtime_tuning["max_document_text_chars"]),
            target_prompt_tokens=int(runtime_tuning["target_prompt_tokens"]),
        ):
            if cancel_checker and cancel_checker():
                raise LLMProcessingCancelled(f"Processamento cancelado antes da chamada ao provedor {self.provider_name}.")
            chunk_requested_model = self.model_name if len(chunk) == 1 else self.bulk_model_name
            chunk_fallback_models = self.fallback_models if len(chunk) == 1 else self.bulk_fallback_models
            chunk_attempted_models = [item for item in [chunk_requested_model, *chunk_fallback_models] if item]
            try:
                chunk_results = self._request_batch(
                    chunk,
                    cancel_checker=cancel_checker,
                    request_event_callback=request_event_callback,
                    runtime_tuning=runtime_tuning,
                )
                results.update(chunk_results)
            except LLMProcessingCancelled:
                raise
            except Exception as exc:
                logger.debug("%s_batch_failed chunk_size=%s error=%s", self.provider_name, len(chunk), exc)
                for item in chunk:
                    document_id = str(item["document_id"])
                    provider_error = self._coerce_provider_error(exc)
                    results[document_id] = self._fallback_invoice_result(
                        parsed_fields=item["parsed_fields"] if isinstance(item.get("parsed_fields"), dict) else {},
                        missing_fields=item["missing_fields"] if isinstance(item.get("missing_fields"), list) else [],
                        truncated_fields=item["truncated_fields"] if isinstance(item.get("truncated_fields"), list) else [],
                        message=self._build_provider_fallback_summary(provider_error),
                        requested_model=chunk_requested_model,
                        attempted_models=chunk_attempted_models,
                        provider_error=provider_error.to_payload(),
                    )

        for item in documents:
            document_id = str(item["document_id"])
            if document_id not in results:
                results[document_id] = self._fallback_invoice_result(
                    parsed_fields=item["parsed_fields"] if isinstance(item.get("parsed_fields"), dict) else {},
                    missing_fields=item["missing_fields"] if isinstance(item.get("missing_fields"), list) else [],
                    truncated_fields=item["truncated_fields"] if isinstance(item.get("truncated_fields"), list) else [],
                    message=f"Resposta do provedor {self.provider_name} nao retornou resultado para o documento.",
                    requested_model=default_requested_model,
                    attempted_models=default_attempted_models,
                )

        return results

    # Executa um request de lote usando a estrategia mais adequada.
    def _request_batch(
        self,
        documents: list[dict[str, object]],
        *,
        cancel_checker: Callable[[], bool] | None = None,
        request_event_callback: Callable[[dict[str, object]], None] | None = None,
        runtime_tuning: dict[str, int | float],
    ) -> dict[str, dict[str, object]]:
        model_name = self.model_name if len(documents) == 1 else self.bulk_model_name
        fallback_models = self.fallback_models if len(documents) == 1 else self.bulk_fallback_models
        headers = self._build_headers()

        strategies = self._build_request_strategies(documents, model_name, fallback_models, runtime_tuning=runtime_tuning)
        errors: list[str] = []
        last_provider_error: ProviderRequestError | None = None

        for strategy in strategies:
            strategy_started_at = time.monotonic()
            try:
                if cancel_checker and cancel_checker():
                    raise LLMProcessingCancelled(f"Processamento cancelado antes da estrategia do provedor {self.provider_name}.")
                payload = self._perform_request(
                    headers=headers,
                    request_payload=strategy["payload"],
                    cancel_checker=cancel_checker,
                    requests_per_minute=int(runtime_tuning["requests_per_minute"]),
                )
                model_text = self._extract_text(payload)
                parsed = self._parse_response_json(model_text)
                effective_model = self._extract_effective_model(payload, str(strategy["requested_model"]))
                if request_event_callback:
                    request_event_callback(
                        {
                            "status": "success",
                            "strategy": strategy["label"],
                            "requested_model": str(strategy["requested_model"]),
                            "effective_model": effective_model,
                            "attempted_models": strategy["attempted_models"] if isinstance(strategy["attempted_models"], list) else [],
                            "chunk_size": len(documents),
                            "duration_ms": int((time.monotonic() - strategy_started_at) * 1000),
                            "fallback_used": effective_model != str(strategy["requested_model"]),
                            "runtime_tuning": runtime_tuning,
                        }
                    )
                return self._normalize_batch_response(
                    documents=documents,
                    model_name=str(strategy["requested_model"]),
                    attempted_models=strategy["attempted_models"] if isinstance(strategy["attempted_models"], list) else [],
                    payload=payload,
                    parsed=parsed,
                )
            except LLMProcessingCancelled:
                raise
            except Exception as exc:
                runtime_error = self._coerce_provider_error(exc)
                if request_event_callback:
                    event_payload = runtime_error.to_payload()
                    request_event_callback(
                        {
                            "status": "failed",
                            "strategy": strategy["label"],
                            "requested_model": str(strategy["requested_model"]),
                            "attempted_models": strategy["attempted_models"] if isinstance(strategy["attempted_models"], list) else [],
                            "chunk_size": len(documents),
                            "duration_ms": int((time.monotonic() - strategy_started_at) * 1000),
                            "error": runtime_error.technical_message,
                            "runtime_tuning": runtime_tuning,
                            **event_payload,
                        }
                    )
                logger.warning(
                    "provider_strategy_failed provider=%s strategy=%s error_code=%s http_status=%s error=%s",
                    self.provider_name,
                    strategy["label"],
                    runtime_error.error_code,
                    runtime_error.http_status,
                    runtime_error.technical_message,
                )
                errors.append(f"{strategy['label']}: {runtime_error.technical_message}")
                last_provider_error = runtime_error
                if not self._should_try_next_strategy(runtime_error):
                    break

        if last_provider_error is not None:
            raise self._build_provider_error(
                error_code=last_provider_error.error_code,
                http_status=last_provider_error.http_status,
                retryable=last_provider_error.retryable,
                technical_message=" | ".join(errors) if errors else last_provider_error.technical_message,
                user_message=last_provider_error.user_message,
            )

        raise RuntimeError(" | ".join(errors) if errors else f"Falha ao chamar o provedor {self.provider_name}.")

    # Monta os headers exigidos pelo provedor HTTP.
    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.provider_name == "openrouter":
            if self.site_url:
                headers["HTTP-Referer"] = self.site_url
            if self.app_name:
                headers["X-OpenRouter-Title"] = self.app_name
        return headers

    # Cria o payload final enviado ao endpoint de chat completions.
    def _build_batch_payload(
        self,
        documents: list[dict[str, object]],
        model_name: str,
        fallback_models: list[str],
        *,
        runtime_tuning: dict[str, int | float],
    ) -> dict[str, object]:
        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "user",
                    "content": self._build_batch_prompt(
                        documents,
                        max_document_text_chars=int(runtime_tuning["max_document_text_chars"]),
                    ),
                }
            ],
            "temperature": 0.1,
            "response_format": {
                "type": "json_object",
            },
        }
        fallback_chain = [item for item in [model_name, *fallback_models] if item]
        deduplicated_chain = list(dict.fromkeys(fallback_chain))
        if len(deduplicated_chain) > 1:
            payload["models"] = deduplicated_chain
            payload["route"] = "fallback"
        return payload

    # Monta a ordem de estrategias de chamada para o mesmo request.
    def _build_request_strategies(
        self,
        documents: list[dict[str, object]],
        model_name: str,
        fallback_models: list[str],
        *,
        runtime_tuning: dict[str, int | float],
    ) -> list[dict[str, object]]:
        normalized_fallbacks = [item for item in fallback_models if item and item != model_name]
        route_fallbacks = normalized_fallbacks[: max(OPENROUTER_MAX_COMBINED_MODELS - 1, 0)]
        combined_attempts = [model_name, *route_fallbacks]
        strategies: list[dict[str, object]] = []

        strategies.append(
            {
                "label": "primary_only",
                "requested_model": model_name,
                "attempted_models": [model_name],
                "payload": self._build_batch_payload(
                    documents,
                    model_name,
                    [],
                    runtime_tuning=runtime_tuning,
                ),
            }
        )

        if self.supports_combined_fallback_route and route_fallbacks:
            strategies.append(
                {
                    "label": "combined_fallback_route",
                    "requested_model": model_name,
                    "attempted_models": combined_attempts,
                    "payload": self._build_batch_payload(
                        documents,
                        model_name,
                        route_fallbacks,
                        runtime_tuning=runtime_tuning,
                    ),
                }
            )

        for fallback_model in normalized_fallbacks:
            strategies.append(
                {
                    "label": f"fallback_only:{fallback_model}",
                    "requested_model": fallback_model,
                    "attempted_models": [model_name, fallback_model],
                    "payload": self._build_batch_payload(
                        documents,
                        fallback_model,
                        [],
                        runtime_tuning=runtime_tuning,
                    ),
                }
            )

        return strategies

    # Executa uma estrategia de request com controle de rate limit e retry.
    def _perform_request(
        self,
        *,
        headers: dict[str, str],
        request_payload: dict[str, object],
        cancel_checker: Callable[[], bool] | None = None,
        requests_per_minute: int,
    ) -> dict[str, object]:
        last_error: ProviderRequestError | None = None
        backoff_seconds = self.initial_backoff_seconds

        for attempt in range(self.max_retries + 1):
            if cancel_checker and cancel_checker():
                raise LLMProcessingCancelled(f"Processamento cancelado antes do envio ao provedor {self.provider_name}.")
            self._wait_for_rate_limit_slot(requests_per_minute=requests_per_minute, cancel_checker=cancel_checker)
            try:
                response = self._http_client.post(self.api_base_url, headers=headers, json=request_payload)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                last_error, should_retry_request = self._classify_http_status_error(exc)
                if should_retry_request and attempt < self.max_retries:
                    self._sleep_with_backoff(backoff_seconds, cancel_checker=cancel_checker)
                    backoff_seconds = min(backoff_seconds * self.backoff_multiplier, self.max_backoff_seconds)
                    continue
                break
            except httpx.TimeoutException as exc:
                last_error = self._build_provider_error(
                    error_code="provider_timeout",
                    http_status=None,
                    retryable=True,
                    technical_message=f"Timeout: {exc}",
                    user_message="A validacao por IA demorou mais do que o esperado. Vamos tentar novamente e, se preciso, seguir com fallback.",
                )
                if attempt < self.max_retries:
                    self._sleep_with_backoff(backoff_seconds, cancel_checker=cancel_checker)
                    backoff_seconds = min(backoff_seconds * self.backoff_multiplier, self.max_backoff_seconds)
                    continue
                break
            except httpx.HTTPError as exc:
                last_error = self._build_provider_error(
                    error_code="provider_transport_error",
                    http_status=None,
                    retryable=True,
                    technical_message=str(exc),
                    user_message="Nao foi possivel se comunicar com o provedor de IA. Vamos tentar outra rota e, se necessario, seguir com fallback.",
                )
                if attempt < self.max_retries:
                    self._sleep_with_backoff(backoff_seconds, cancel_checker=cancel_checker)
                    backoff_seconds = min(backoff_seconds * self.backoff_multiplier, self.max_backoff_seconds)
                    continue
                break

        raise last_error or self._build_provider_error(
            error_code="provider_unknown_error",
            http_status=None,
            retryable=False,
            technical_message=f"Falha ao chamar o provedor {self.provider_name}.",
            user_message="A validacao por IA nao ficou disponivel neste momento. Seguiremos com fallback quando necessario.",
        )

    # Decide se vale trocar de estrategia apos a falha atual.
    def _should_try_next_strategy(self, error: RuntimeError) -> bool:
        if isinstance(error, ProviderRequestError):
            return error.error_code not in {
                "provider_auth_invalid",
                "provider_access_denied",
                "provider_daily_quota_exceeded",
            }

        message = str(error)
        return any(
            marker in message
            for marker in (
                "HTTP 400:",
                "HTTP 404:",
                "HTTP 422:",
                "HTTP 429:",
                "HTTP 500:",
                "HTTP 502:",
                "HTTP 503:",
                "HTTP 504:",
                "Timeout:",
                "Invalid JSON:",
            )
        )

    # Gera o prompt consolidado que descreve o contrato do lote.
    def _build_batch_prompt(self, documents: list[dict[str, object]], *, max_document_text_chars: int) -> str:
        compact_documents = [
            self._build_compact_document(item, max_document_text_chars=max_document_text_chars)
            for item in documents
        ]
        return (
            "Valide e normalize notas fiscais a partir de um JSON preliminar e de trechos do documento. "
            "Para cada item, responda APENAS JSON valido no formato "
            "{\"documents\":[{\"document_id\":\"...\",\"extraction_status\":\"success|partial|failed\",\"summary\":\"...\","
            "\"confidence_overall\":0.0,\"missing_fields\":[],\"truncated_fields\":[],\"normalized_fields\":{...},\"inconsistencies\":{}}]}. "
            "Nao invente dados. Use 'nao_extraido' quando faltar evidencia. "
            "Preserve campos corretos do parser local e corrija somente com base no texto fornecido. "
            "normalized_fields deve sempre conter todos os campos esperados da NF. "
            "Datas em YYYY-MM-DD, valor_bruto numerico, CNPJ so com digitos, status e tipo_documento em caixa alta.\n\n"
            f"prompt_version={self.prompt_version}\n"
            f"documentos={json.dumps(compact_documents, ensure_ascii=False)}"
        )

    # Normaliza a resposta do provedor para um resultado por documento.
    def _normalize_batch_response(
        self,
        *,
        documents: list[dict[str, object]],
        model_name: str,
        attempted_models: list[str],
        payload: dict[str, object],
        parsed: dict[str, object],
    ) -> dict[str, dict[str, object]]:
        parsed_documents = parsed.get("documents")
        if not isinstance(parsed_documents, list):
            raise self._build_provider_error(
                error_code="provider_invalid_response",
                http_status=None,
                retryable=True,
                technical_message=f"Resposta do provedor {self.provider_name} sem array documents",
                user_message="A resposta da IA veio em formato invalido. Vamos tentar outra estrategia ou seguir com fallback.",
            )

        source_by_id = {str(item["document_id"]): item for item in documents}
        results: dict[str, dict[str, object]] = {}

        for item in parsed_documents:
            if not isinstance(item, dict):
                continue
            document_id = str(item.get("document_id") or "").strip()
            if not document_id or document_id not in source_by_id:
                continue

            source = source_by_id[document_id]
            normalized_fields = item.get("normalized_fields") if isinstance(item.get("normalized_fields"), dict) else None
            has_structured_result = isinstance(normalized_fields, dict) and bool(normalized_fields)
            fallback = self._fallback_invoice_result(
                parsed_fields=source["parsed_fields"] if isinstance(source.get("parsed_fields"), dict) else {},
                missing_fields=source["missing_fields"] if isinstance(source.get("missing_fields"), list) else [],
                truncated_fields=source["truncated_fields"] if isinstance(source.get("truncated_fields"), list) else [],
                message=f"Resposta do provedor {self.provider_name} incompleta.",
                requested_model=model_name,
                attempted_models=attempted_models,
            )
            effective_model = self._extract_effective_model(payload, model_name)
            results[document_id] = {
                "provider": self.provider_name,
                "model": effective_model,
                "requested_model": model_name,
                "fallback_used": effective_model != model_name,
                "attempted_models": attempted_models,
                "prompt_version": self.prompt_version,
                "classification": item.get("classification") or fallback["classification"],
                "risk_score": None,
                "summary": item.get("summary") or (f"Analise {self.provider_name} concluida." if has_structured_result else fallback["summary"]),
                "inconsistencies": item.get("inconsistencies") if isinstance(item.get("inconsistencies"), dict) else {},
                "confidence_overall": float(item.get("confidence_overall") or (0.85 if has_structured_result else 0.0)),
                "raw_response": json.dumps(payload, ensure_ascii=False),
                "extraction_status": item.get("extraction_status") or ("success" if has_structured_result else fallback["extraction_status"]),
                "missing_fields": item.get("missing_fields") if isinstance(item.get("missing_fields"), list) else fallback["missing_fields"],
                "truncated_fields": item.get("truncated_fields") if isinstance(item.get("truncated_fields"), list) else fallback["truncated_fields"],
                "normalized_fields": normalized_fields if has_structured_result else fallback["normalized_fields"],
            }

        return results

    # Aguarda uma janela livre antes de disparar novo request.
    def _wait_for_rate_limit_slot(
        self,
        *,
        requests_per_minute: int,
        cancel_checker: Callable[[], bool] | None = None,
    ) -> None:
        while True:
            with self._rate_lock:
                now = time.monotonic()
                while self._request_timestamps and (now - self._request_timestamps[0]) >= self._rate_window_seconds:
                    self._request_timestamps.popleft()
                if len(self._request_timestamps) < requests_per_minute:
                    self._request_timestamps.append(now)
                    return
                sleep_seconds = max(self._rate_window_seconds - (now - self._request_timestamps[0]), 0.1)
            if cancel_checker and cancel_checker():
                raise LLMProcessingCancelled(f"Processamento cancelado durante espera por rate limit do provedor {self.provider_name}.")
            time.sleep(min(sleep_seconds, 1.0))

    # Aplica backoff com jitter sem perder suporte a cancelamento.
    def _sleep_with_backoff(self, base_seconds: float, *, cancel_checker: Callable[[], bool] | None = None) -> None:
        jitter = random.uniform(0, min(base_seconds * 0.25, 1.0))
        target_sleep = min(base_seconds + jitter, self.max_backoff_seconds)
        deadline = time.monotonic() + target_sleep
        while time.monotonic() < deadline:
            if cancel_checker and cancel_checker():
                raise LLMProcessingCancelled("Processamento cancelado durante backoff.")
            time.sleep(min(deadline - time.monotonic(), 0.25))

    # Divide o lote respeitando quantidade de itens e orcamento de tokens.
    def _chunk_documents(
        self,
        documents: list[dict[str, object]],
        chunk_size: int,
        *,
        max_document_text_chars: int,
        target_prompt_tokens: int,
    ) -> list[list[dict[str, object]]]:
        chunks: list[list[dict[str, object]]] = []
        current_chunk: list[dict[str, object]] = []
        # O lote respeita quantidade de itens e orcamento estimado de tokens,
        # evitando que um documento muito grande estoure o prompt inteiro.
        current_tokens = self._estimate_prompt_overhead_tokens()

        for document in documents:
            estimated_tokens = self._estimate_document_tokens(
                document,
                max_document_text_chars=max_document_text_chars,
            )
            would_exceed_size = len(current_chunk) >= chunk_size
            would_exceed_budget = bool(current_chunk) and (current_tokens + estimated_tokens) > target_prompt_tokens

            if would_exceed_size or would_exceed_budget:
                chunks.append(current_chunk)
                current_chunk = []
                current_tokens = self._estimate_prompt_overhead_tokens()

            current_chunk.append(document)
            current_tokens += estimated_tokens

        if current_chunk:
            chunks.append(current_chunk)
        return chunks

    # Reduz cada documento ao contexto minimo necessario para o prompt.
    def _build_compact_document(self, item: dict[str, object], *, max_document_text_chars: int) -> dict[str, object]:
        parsed_fields = item["parsed_fields"] if isinstance(item.get("parsed_fields"), dict) else {}
        compact_fields = {
            key: value
            for key, value in parsed_fields.items()
            if value not in {None, "", "nao_extraido"}
        }
        return {
            "document_id": str(item["document_id"]),
            "campos_extraidos": compact_fields,
            "campos_ausentes": item["missing_fields"] if isinstance(item.get("missing_fields"), list) else [],
            "campos_truncados": item["truncated_fields"] if isinstance(item.get("truncated_fields"), list) else [],
            "texto_relevante": self._compact_raw_text(
                str(item.get("raw_text") or ""),
                max_document_text_chars=max_document_text_chars,
            ),
        }

    # Compacta o texto bruto para caber no limite do prompt.
    def _compact_raw_text(self, raw_text: str, *, max_document_text_chars: int) -> str:
        compact_lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        compact_text = "\n".join(compact_lines)
        if len(compact_text) <= max_document_text_chars:
            return compact_text
        return f"{compact_text[: max_document_text_chars].rstrip()}..."

    # Estima o custo fixo do prompt alem dos documentos.
    def _estimate_prompt_overhead_tokens(self) -> int:
        return 450

    # Estima quantos tokens um documento deve consumir no prompt.
    def _estimate_document_tokens(self, document: dict[str, object], *, max_document_text_chars: int) -> int:
        compact_document = self._build_compact_document(
            document,
            max_document_text_chars=max_document_text_chars,
        )
        serialized = json.dumps(compact_document, ensure_ascii=False)
        return max(len(serialized) // 4, 1) + 32

    # Ajusta o tuning de acordo com o tamanho do lote.
    def _build_runtime_tuning(self, total_documents: int | None) -> dict[str, int | float]:
        if self.processing_mode == "demo":
            return {
                "batch_size": 1,
                "target_prompt_tokens": self.target_prompt_tokens,
                "max_document_text_chars": self.max_document_text_chars,
                "requests_per_minute": self.requests_per_minute,
            }

        if not self.dynamic_tuning_enabled:
            return {
                "batch_size": self.bulk_batch_size,
                "target_prompt_tokens": self.target_prompt_tokens,
                "max_document_text_chars": self.max_document_text_chars,
                "requests_per_minute": self.requests_per_minute,
            }

        document_count = max(total_documents or 0, 0)
        if document_count <= 25:
            return {
                "batch_size": min(self.bulk_batch_size, 4),
                "target_prompt_tokens": min(self.target_prompt_tokens, 14000),
                "max_document_text_chars": self.max_document_text_chars,
                "requests_per_minute": min(self.requests_per_minute, 4),
            }
        if document_count <= 100:
            return {
                "batch_size": self.bulk_batch_size,
                "target_prompt_tokens": self.target_prompt_tokens,
                "max_document_text_chars": max(
                    self.dynamic_max_document_text_chars_min,
                    min(self.max_document_text_chars, int(self.max_document_text_chars * 0.85)),
                ),
                "requests_per_minute": self.requests_per_minute,
            }
        return {
            "batch_size": self.dynamic_batch_size_max,
            "target_prompt_tokens": self.dynamic_target_prompt_tokens_max,
            "max_document_text_chars": self.dynamic_max_document_text_chars_min,
            "requests_per_minute": self.dynamic_requests_per_minute_max,
        }

    # Extrai o texto principal da resposta padrao do provedor.
    def _extract_text(self, payload: dict[str, object]) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise self._build_provider_error(
                error_code="provider_invalid_response",
                http_status=None,
                retryable=True,
                technical_message=f"Resposta do provedor {self.provider_name} sem choices",
                user_message="A resposta da IA veio em formato invalido. Vamos tentar outra estrategia ou seguir com fallback.",
            )
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise self._build_provider_error(
                error_code="provider_invalid_response",
                http_status=None,
                retryable=True,
                technical_message="Choice invalida",
                user_message="A resposta da IA veio em formato invalido. Vamos tentar outra estrategia ou seguir com fallback.",
            )
        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise self._build_provider_error(
                error_code="provider_invalid_response",
                http_status=None,
                retryable=True,
                technical_message=f"Resposta do provedor {self.provider_name} sem message",
                user_message="A resposta da IA veio em formato invalido. Vamos tentar outra estrategia ou seguir com fallback.",
            )
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts = []
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    text_parts.append(part["text"])
            if text_parts:
                return "".join(text_parts)
        raise self._build_provider_error(
            error_code="provider_invalid_response",
            http_status=None,
            retryable=True,
            technical_message=f"Resposta do provedor {self.provider_name} sem texto",
            user_message="A resposta da IA veio em formato invalido. Vamos tentar outra estrategia ou seguir com fallback.",
        )

    # Descobre o modelo efetivo usado quando o provedor o informa no retorno.
    def _extract_effective_model(self, payload: dict[str, object], requested_model: str) -> str:
        payload_model = payload.get("model")
        if isinstance(payload_model, str) and payload_model.strip():
            return payload_model.strip()
        return requested_model

    # Converte o texto do modelo para JSON validado.
    def _parse_response_json(self, model_text: str) -> dict[str, object]:
        normalized_text = model_text.strip()
        if normalized_text.startswith("```"):
            normalized_text = normalized_text.strip("`")
            if normalized_text.startswith("json"):
                normalized_text = normalized_text[4:].lstrip()
        try:
            parsed = json.loads(normalized_text)
            if isinstance(parsed, dict):
                return parsed
            raise self._build_provider_error(
                error_code="provider_invalid_response",
                http_status=None,
                retryable=True,
                technical_message="Invalid JSON: resposta nao e um objeto JSON.",
                user_message="A resposta da IA veio em formato invalido. Vamos tentar outra estrategia ou seguir com fallback.",
            )
        except json.JSONDecodeError as exc:
            candidate = self._extract_json_object(normalized_text)
            if candidate and candidate != normalized_text:
                try:
                    parsed = json.loads(candidate)
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    pass
            raise self._build_provider_error(
                error_code="provider_invalid_response",
                http_status=None,
                retryable=True,
                technical_message=f"Invalid JSON: {exc}",
                user_message="A resposta da IA veio em formato invalido. Vamos tentar outra estrategia ou seguir com fallback.",
            ) from exc

    # Tenta recuperar um objeto JSON mesmo quando ha texto em volta.
    def _extract_json_object(self, model_text: str) -> str | None:
        start = model_text.find("{")
        end = model_text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        return model_text[start : end + 1]

    # Gera o resultado de fallback preservando o parse local.
    def _fallback_invoice_result(
        self,
        *,
        parsed_fields: dict[str, object],
        missing_fields: list[str],
        truncated_fields: list[str],
        message: str,
        requested_model: str | None = None,
        attempted_models: list[str] | None = None,
        provider_error: dict[str, object] | None = None,
    ) -> dict[str, object]:
        requested = requested_model or self.model_name
        attempted = attempted_models or [requested]
        return {
            "provider": self.provider_name,
            "model": requested,
            "requested_model": requested,
            "fallback_used": len(attempted) > 1,
            "attempted_models": attempted,
            "prompt_version": self.prompt_version,
            "classification": "nota_fiscal",
            "risk_score": None,
            "summary": message,
            "inconsistencies": {},
            "confidence_overall": 0.25,
            "raw_response": None,
            "extraction_status": "fallback",
            "missing_fields": missing_fields,
            "truncated_fields": truncated_fields,
            "normalized_fields": parsed_fields,
            "provider_error": provider_error,
        }

    # Construi a excecao padronizada de erro do provedor.
    def _build_provider_error(
        self,
        *,
        error_code: str,
        http_status: int | None,
        retryable: bool,
        technical_message: str,
        user_message: str,
    ) -> ProviderRequestError:
        return ProviderRequestError(
            ProviderErrorInfo(
                error_code=error_code,
                http_status=http_status,
                retryable=retryable,
                provider=self.provider_name,
                technical_message=technical_message,
                user_message=user_message,
            )
        )

    # Converte qualquer excecao externa para o contrato interno de erro.
    def _coerce_provider_error(self, error: Exception) -> ProviderRequestError:
        if isinstance(error, ProviderRequestError):
            return error

        return self._build_provider_error(
            error_code="provider_unknown_error",
            http_status=None,
            retryable=False,
            technical_message=str(error),
            user_message="A validacao por IA nao ficou disponivel neste momento. Seguiremos com fallback quando necessario.",
        )

    # Traduz codigos HTTP do provedor em erros internos normalizados.
    def _classify_http_status_error(
        self,
        exc: httpx.HTTPStatusError,
    ) -> tuple[ProviderRequestError, bool]:
        # Normaliza falhas especificas do provedor em um contrato interno unico
        # para o dashboard e o audit.csv explicarem erros de forma consistente.
        status_code = exc.response.status_code
        response_body = exc.response.text.strip()
        if len(response_body) > 1000:
            response_body = f"{response_body[:1000]}..."

        technical_message = f"HTTP {status_code}: {exc}"
        if response_body:
            technical_message = f"{technical_message} | body={response_body}"

        if status_code == 400:
            return (
                self._build_provider_error(
                    error_code="provider_bad_request",
                    http_status=status_code,
                    retryable=True,
                    technical_message=technical_message,
                    user_message="O provedor de IA rejeitou a requisicao deste modelo. Vamos tentar uma alternativa.",
                ),
                False,
            )

        if status_code == 401:
            return (
                self._build_provider_error(
                    error_code="provider_auth_invalid",
                    http_status=status_code,
                    retryable=False,
                    technical_message=technical_message,
                    user_message="A credencial da API externa foi rejeitada. Vamos tentar outro provedor ou seguir com fallback local.",
                ),
                False,
            )

        if status_code == 403:
            return (
                self._build_provider_error(
                    error_code="provider_access_denied",
                    http_status=status_code,
                    retryable=False,
                    technical_message=technical_message,
                    user_message="O provedor de IA negou acesso ao modelo configurado. Vamos tentar outra alternativa disponivel.",
                ),
                False,
            )

        if status_code == 404:
            suggested_model = self._extract_model_suggestion(response_body)
            user_message = "O modelo ou rota configurada nao foi encontrado no provedor. Vamos tentar uma alternativa."
            if suggested_model:
                user_message = (
                    "O modelo configurado nao existe mais neste provedor. "
                    f"Use {suggested_model} ou mantenha outro fallback disponivel."
                )
                technical_message = f"{technical_message} | suggested_model={suggested_model}"
            return (
                self._build_provider_error(
                    error_code="provider_model_not_found",
                    http_status=status_code,
                    retryable=True,
                    technical_message=technical_message,
                    user_message=user_message,
                ),
                False,
            )

        if status_code == 422:
            return (
                self._build_provider_error(
                    error_code="provider_payload_invalid",
                    http_status=status_code,
                    retryable=True,
                    technical_message=technical_message,
                    user_message="O provedor recusou os parametros enviados para este modelo. Vamos tentar uma estrategia compativel.",
                ),
                False,
            )

        if status_code == 429 and "free-models-per-day" in response_body:
            return (
                self._build_provider_error(
                    error_code="provider_daily_quota_exceeded",
                    http_status=status_code,
                    retryable=False,
                    technical_message=technical_message,
                    user_message="A cota diaria do provedor foi atingida. O sistema seguira com outro provedor ou com o parser local.",
                ),
                False,
            )

        if status_code == 429:
            return (
                self._build_provider_error(
                    error_code="provider_rate_limited",
                    http_status=status_code,
                    retryable=True,
                    technical_message=technical_message,
                    user_message="O provedor de IA atingiu limite de requisicoes. Vamos tentar novamente e, se preciso, usar fallback.",
                ),
                True,
            )

        if status_code == 500:
            return (
                self._build_provider_error(
                    error_code="provider_internal_error",
                    http_status=status_code,
                    retryable=True,
                    technical_message=technical_message,
                    user_message="O provedor de IA falhou internamente. Vamos tentar novamente e seguir com fallback se necessario.",
                ),
                True,
            )

        if status_code == 502:
            return (
                self._build_provider_error(
                    error_code="provider_bad_gateway",
                    http_status=status_code,
                    retryable=True,
                    technical_message=technical_message,
                    user_message="O provedor de IA respondeu com erro intermediario. Vamos tentar novamente e seguir com fallback se necessario.",
                ),
                True,
            )

        if status_code == 503:
            return (
                self._build_provider_error(
                    error_code="provider_unavailable",
                    http_status=status_code,
                    retryable=True,
                    technical_message=technical_message,
                    user_message="O provedor de IA esta indisponivel no momento. Vamos tentar novamente e seguir com fallback se necessario.",
                ),
                True,
            )

        if status_code == 504:
            return (
                self._build_provider_error(
                    error_code="provider_gateway_timeout",
                    http_status=status_code,
                    retryable=True,
                    technical_message=technical_message,
                    user_message="O provedor de IA excedeu o tempo de resposta. Vamos tentar novamente e seguir com fallback se necessario.",
                ),
                True,
            )

        return (
            self._build_provider_error(
                error_code="provider_unknown_error",
                http_status=status_code,
                retryable=False,
                technical_message=technical_message,
                user_message="A validacao por IA encontrou uma falha externa inesperada. Seguiremos com fallback quando necessario.",
            ),
            False,
        )

    # Monta o resumo amigavel usado quando houve fallback por falha externa.
    def _build_provider_fallback_summary(self, error: ProviderRequestError) -> str:
        return f"{error.user_message} Seguimos com a extracao local deste documento."
