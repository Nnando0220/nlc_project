from __future__ import annotations

from collections.abc import Callable

from app.services.groq_service import GroqService
from app.services.huggingface_service import HuggingFaceService
from app.services.openrouter_service import OpenRouterService

DEFAULT_PROVIDER_ORDER = ["openrouter", "groq", "huggingface"]


# Cria a implementacao concreta do provedor solicitado.
def create_llm_provider(provider_name: str):
    normalized = provider_name.lower().strip()
    if normalized == "openrouter":
        return OpenRouterService()
    if normalized == "groq":
        return GroqService()
    if normalized == "huggingface":
        return HuggingFaceService()
    raise ValueError(f"Provedor de LLM nao suportado: {provider_name}")


class LLMRouterService:
    # Inicializa os provedores em uma ordem fixa e pula os que estiverem sem chave.
    def __init__(self) -> None:
        self.provider_order = self._normalize_provider_order(DEFAULT_PROVIDER_ORDER)
        self.providers = {
            provider_name: create_llm_provider(provider_name)
            for provider_name in self.provider_order
        }

    @property
    # Retorna o nome do provedor principal da cadeia.
    def primary_provider_name(self) -> str:
        return self.provider_order[0]

    @property
    # Retorna a instancia principal usada como referencia do roteador.
    def primary_service(self):
        return self.providers[self.primary_provider_name]

    @property
    # Expoe a chave do provedor principal para facilitar testes e overrides locais.
    def api_key(self) -> str:
        return getattr(self.primary_service, "api_key", "")

    @api_key.setter
    # Replica a chave manualmente para todos os provedores carregados.
    def api_key(self, value: str) -> None:
        for service in self.providers.values():
            service.api_key = value

    @property
    # Expoe a estrategia principal de analise em uso.
    def analysis_strategy(self) -> str:
        return getattr(self.primary_service, "analysis_strategy", "all")

    @analysis_strategy.setter
    # Sincroniza a estrategia de analise entre os provedores ativos.
    def analysis_strategy(self, value: str) -> None:
        for service in self.providers.values():
            service.analysis_strategy = value

    # Fecha os clientes HTTP abertos pelos provedores.
    def close(self) -> None:
        for service in self.providers.values():
            service.close()

    # Repassa o tamanho do micro-lote calculado pelo provedor principal.
    def get_processing_chunk_size(self, total_documents: int | None = None) -> int:
        return self.primary_service.get_processing_chunk_size(total_documents)

    # Repassa o tuning dinamico calculado pelo provedor principal.
    def get_runtime_tuning(self, total_documents: int | None = None) -> dict[str, int | float]:
        return self.primary_service.get_runtime_tuning(total_documents)

    # Decide se um documento precisa passar pelo LLM.
    def should_use_llm_for_document(self, **kwargs) -> bool:
        return self.primary_service.should_use_llm_for_document(**kwargs)

    # Gera um resultado local quando a etapa de IA nao for necessaria.
    def build_local_parser_result(self, **kwargs) -> dict[str, object]:
        return self.primary_service.build_local_parser_result(**kwargs)

    # Tenta os provedores em ordem ate obter uma resposta real de LLM.
    def analyze_invoices_batch(
        self,
        documents: list[dict[str, object]],
        *,
        force_single: bool = False,
        cancel_checker: Callable[[], bool] | None = None,
        request_event_callback: Callable[[dict[str, object]], None] | None = None,
        total_documents: int | None = None,
    ) -> dict[str, dict[str, object]]:
        last_results: dict[str, dict[str, object]] | None = None

        for provider_name in self.provider_order:
            service = self.providers[provider_name]
            if not getattr(service, "api_key", ""):
                continue
            provider_events: list[dict[str, object]] = []

            # Anexa o nome do provedor aos eventos emitidos para auditoria.
            def wrapped_request_event(event: dict[str, object]) -> None:
                payload = dict(event)
                payload["provider"] = provider_name
                provider_events.append(payload)
                if request_event_callback:
                    request_event_callback(payload)

            results = service.analyze_invoices_batch(
                documents,
                force_single=force_single,
                cancel_checker=cancel_checker,
                request_event_callback=wrapped_request_event,
                total_documents=total_documents,
            )
            last_results = results
            if self._results_have_real_llm_output(results):
                return results

        if last_results is not None:
            return last_results

        return {
            str(item["document_id"]): self.primary_service.build_local_parser_result(
                parsed_fields=item["parsed_fields"] if isinstance(item.get("parsed_fields"), dict) else {},
                missing_fields=item["missing_fields"] if isinstance(item.get("missing_fields"), list) else [],
                truncated_fields=item["truncated_fields"] if isinstance(item.get("truncated_fields"), list) else [],
                message="Nenhum provedor de IA retornou resultado utilizavel.",
            )
            for item in documents
        }

    # Remove duplicidades e valores vazios na ordem de fallback.
    def _normalize_provider_order(self, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in values:
            candidate = item.lower().strip()
            if candidate and candidate not in normalized:
                normalized.append(candidate)
        return normalized or ["openrouter"]

    # Detecta se ao menos um resultado veio de uma chamada real ao LLM.
    def _results_have_real_llm_output(self, results: dict[str, dict[str, object]]) -> bool:
        return any(result.get("extraction_status") != "fallback" for result in results.values())
