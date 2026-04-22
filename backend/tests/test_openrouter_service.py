import httpx
import pytest

from app.services.openrouter_service import OpenRouterService


def _build_http_status_error(status_code: int, body: str = "") -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://provider.example/api")
    response = httpx.Response(status_code, text=body, request=request)
    return httpx.HTTPStatusError(
        f"HTTP {status_code}",
        request=request,
        response=response,
    )


@pytest.mark.parametrize(
    ("status_code", "body", "expected_error_code", "expected_retryable", "expected_request_retry"),
    [
        (400, "", "provider_bad_request", True, False),
        (401, "", "provider_auth_invalid", False, False),
        (403, "", "provider_access_denied", False, False),
        (404, "", "provider_model_not_found", True, False),
        (422, "", "provider_payload_invalid", True, False),
        (429, "", "provider_rate_limited", True, True),
        (429, "Rate limit exceeded: free-models-per-day", "provider_daily_quota_exceeded", False, False),
        (500, "", "provider_internal_error", True, True),
        (502, "", "provider_bad_gateway", True, True),
        (503, "", "provider_unavailable", True, True),
        (504, "", "provider_gateway_timeout", True, True),
    ],
)
def test_classify_http_status_errors(
    status_code: int,
    body: str,
    expected_error_code: str,
    expected_retryable: bool,
    expected_request_retry: bool,
) -> None:
    service = OpenRouterService()
    try:
        error, should_retry_request = service._classify_http_status_error(
            _build_http_status_error(status_code, body),
        )
        assert error.error_code == expected_error_code
        assert error.retryable is expected_retryable
        assert error.http_status == status_code
        assert should_retry_request is expected_request_retry
    finally:
        service.close()


def test_should_not_try_next_strategy_for_free_models_daily_cap() -> None:
    service = OpenRouterService()
    try:
        error, _ = service._classify_http_status_error(
            _build_http_status_error(429, "Rate limit exceeded: free-models-per-day"),
        )
        assert service._should_try_next_strategy(error) is False
    finally:
        service.close()


def test_should_try_next_strategy_for_invalid_json() -> None:
    service = OpenRouterService()
    try:
        error = service._build_provider_error(
            error_code="provider_invalid_response",
            http_status=None,
            retryable=True,
            technical_message="Invalid JSON: Expecting ',' delimiter",
            user_message="Resposta invalida",
        )
        assert service._should_try_next_strategy(error) is True
    finally:
        service.close()


def test_parse_response_json_recovers_json_inside_code_fence() -> None:
    service = OpenRouterService()
    try:
        parsed = service._parse_response_json("```json\n{\"documents\": []}\n```")
        assert parsed == {"documents": []}
    finally:
        service.close()


def test_parse_response_json_raises_normalized_error_for_invalid_json() -> None:
    service = OpenRouterService()
    try:
        with pytest.raises(Exception) as exc_info:
            service._parse_response_json("{invalid json")
        error = exc_info.value
        assert getattr(error, "error_code", "") == "provider_invalid_response"
        assert getattr(error, "retryable", False) is True
    finally:
        service.close()


def test_normalize_legacy_openrouter_model_aliases() -> None:
    service = OpenRouterService(
        api_key="test-key",
        model_name="openrouter/elephant-alpha",
        bulk_model_name="openrouter/elephant-alpha",
        fallback_models=["openrouter/elephant-alpha", "meta-llama/llama-3.3-70b-instruct:free"],
        bulk_fallback_models=["openrouter/elephant-alpha"],
    )
    try:
        assert service.model_name == "inclusionai/ling-2.6-flash:free"
        assert service.bulk_model_name == "inclusionai/ling-2.6-flash:free"
        assert service.fallback_models == [
            "inclusionai/ling-2.6-flash:free",
            "meta-llama/llama-3.3-70b-instruct:free",
        ]
        assert service.bulk_fallback_models == ["inclusionai/ling-2.6-flash:free"]
    finally:
        service.close()


def test_classify_404_can_surface_openrouter_suggested_model() -> None:
    service = OpenRouterService()
    try:
        error, should_retry_request = service._classify_http_status_error(
            _build_http_status_error(
                404,
                '{"error":{"message":"Elephant Alpha was a stealth model revealed on April 21st as Ling-2.6-flash. '
                'Find it here: https://openrouter.ai/inclusionai/ling-2.6-flash:free","code":404}}',
            ),
        )
        assert error.error_code == "provider_model_not_found"
        assert should_retry_request is False
        assert "inclusionai/ling-2.6-flash:free" in error.user_message
        assert "suggested_model=inclusionai/ling-2.6-flash:free" in error.technical_message
    finally:
        service.close()


def test_analyze_invoices_batch_reports_normalized_error_event(monkeypatch: pytest.MonkeyPatch) -> None:
    service = OpenRouterService(
        api_key="test-key",
        fallback_models=[],
        bulk_fallback_models=[],
        max_retries=0,
    )
    try:
        expected_error = service._build_provider_error(
            error_code="provider_unavailable",
            http_status=503,
            retryable=True,
            technical_message="HTTP 503: upstream unavailable",
            user_message="O provedor de IA esta indisponivel no momento. Vamos tentar novamente e seguir com fallback se necessario.",
        )

        def fake_perform_request(**kwargs):
            raise expected_error

        monkeypatch.setattr(service, "_perform_request", fake_perform_request)
        events: list[dict[str, object]] = []

        results = service.analyze_invoices_batch(
            [
                {
                    "document_id": "doc-1",
                    "raw_text": "NUMERO_DOCUMENTO: NF-1",
                    "parsed_fields": {"numero_documento": "NF-1"},
                    "missing_fields": [],
                    "truncated_fields": [],
                }
            ],
            force_single=True,
            request_event_callback=events.append,
            total_documents=1,
        )

        assert events
        failed_event = events[0]
        assert failed_event["status"] == "failed"
        assert failed_event["error_code"] == "provider_unavailable"
        assert failed_event["http_status"] == 503
        assert failed_event["retryable"] is True
        assert "user_message" in failed_event
        assert results["doc-1"]["extraction_status"] == "fallback"
        assert results["doc-1"]["provider_error"]["error_code"] == "provider_unavailable"
        assert "Seguimos com a extracao local" in str(results["doc-1"]["summary"])
    finally:
        service.close()
