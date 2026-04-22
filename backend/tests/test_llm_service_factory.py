from app.services.groq_service import GroqService
from app.services.huggingface_service import HuggingFaceService
from app.services.llm_service_factory import LLMRouterService, create_llm_provider
from app.services.openrouter_service import OpenRouterService


class _FakeService:
    def __init__(self, provider_name: str, result_status: str) -> None:
        self.provider_name = provider_name
        self.result_status = result_status
        self.api_key = "fake-key"
        self.analysis_strategy = "all"

    def close(self) -> None:
        return None

    def get_processing_chunk_size(self, total_documents=None) -> int:
        return 3

    def get_runtime_tuning(self, total_documents=None) -> dict[str, int]:
        return {
            "batch_size": 3,
            "target_prompt_tokens": 12000,
            "max_document_text_chars": 1200,
            "requests_per_minute": 3,
        }

    def should_use_llm_for_document(self, **kwargs) -> bool:
        return True

    def build_local_parser_result(self, **kwargs):
        return {"provider": "local-parser", "extraction_status": "skipped"}

    def analyze_invoices_batch(self, documents, **kwargs):
        callback = kwargs.get("request_event_callback")
        if callback:
            callback(
                {
                    "status": "success",
                    "strategy": "primary_only",
                    "requested_model": f"{self.provider_name}-model",
                    "effective_model": f"{self.provider_name}-model",
                    "attempted_models": [f"{self.provider_name}-model"],
                    "chunk_size": len(documents),
                    "duration_ms": 1000,
                    "fallback_used": False,
                }
            )
        return {
            str(item["document_id"]): {
                "provider": self.provider_name,
                "model": f"{self.provider_name}-model",
                "requested_model": f"{self.provider_name}-model",
                "fallback_used": False,
                "attempted_models": [f"{self.provider_name}-model"],
                "prompt_version": "test",
                "classification": "nota_fiscal",
                "risk_score": None,
                "summary": "ok",
                "inconsistencies": {},
                "confidence_overall": 0.9,
                "raw_response": "{}",
                "extraction_status": self.result_status,
                "missing_fields": [],
                "truncated_fields": [],
                "normalized_fields": {"numero_documento": "NF-1"},
            }
            for item in documents
        }


def test_create_llm_provider_supports_known_providers() -> None:
    openrouter = create_llm_provider("openrouter")
    groq = create_llm_provider("groq")
    huggingface = create_llm_provider("huggingface")
    try:
        assert isinstance(openrouter, OpenRouterService)
        assert isinstance(groq, GroqService)
        assert isinstance(huggingface, HuggingFaceService)
    finally:
        openrouter.close()
        groq.close()
        huggingface.close()


def test_router_falls_back_to_next_provider_when_primary_only_returns_fallback() -> None:
    router = LLMRouterService()
    original_order = router.provider_order
    original_providers = router.providers
    try:
        router.provider_order = ["openrouter", "groq"]
        router.providers = {
            "openrouter": _FakeService("openrouter", "fallback"),
            "groq": _FakeService("groq", "success"),
        }
        results = router.analyze_invoices_batch(
            [{"document_id": "doc-1", "parsed_fields": {}, "missing_fields": [], "truncated_fields": []}],
            total_documents=1,
        )
        assert results["doc-1"]["provider"] == "groq"
        assert results["doc-1"]["extraction_status"] == "success"
    finally:
        router.provider_order = original_order
        router.providers = original_providers
        router.close()
