"""Middleware de seguranca HTTP para API publica."""

import logging
import time
from collections import defaultdict, deque
from collections.abc import Callable
from threading import Lock
from uuid import uuid4

from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from app.core.config import settings

logger = logging.getLogger("app.security")


class SecurityMiddleware(BaseHTTPMiddleware):
    """Aplica validacoes de transporte, rate limit e headers de seguranca."""

    def __init__(self, app) -> None:
        super().__init__(app)
        self._requests_by_key: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Envolve o ciclo da request com controles de seguranca e observabilidade."""
        request_id = str(uuid4())
        request.state.request_id = request_id
        start_time = time.perf_counter()

        if settings.require_https and not self._is_secure_request(request):
            logger.warning("request_blocked_insecure_transport request_id=%s path=%s", request_id, request.url.path)
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"detail": "HTTPS e obrigatorio para esta API."},
                headers={"x-request-id": request_id},
            )

        if request.url.path.startswith("/api/") and not self._allow_request(request):
            logger.warning(
                "request_rate_limited request_id=%s client=%s path=%s",
                request_id,
                self._get_client_ip(request),
                request.url.path,
            )
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Rate limit excedido. Tente novamente em instantes."},
                headers={"Retry-After": str(settings.rate_limit_window_seconds), "x-request-id": request_id},
            )

        response = await call_next(request)
        self._apply_security_headers(response, request)

        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        logger.info(
            "request_completed request_id=%s method=%s path=%s status=%s duration_ms=%s",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response

    def _allow_request(self, request: Request) -> bool:
        """Implementa janela deslizante por cliente + rota para rate limiting."""
        now = time.time()
        window = settings.rate_limit_window_seconds
        max_requests = settings.rate_limit_max_requests
        key = f"{self._get_client_ip(request)}:{request.url.path}"

        with self._lock:
            queue = self._requests_by_key[key]
            while queue and (now - queue[0]) > window:
                queue.popleft()
            if len(queue) >= max_requests:
                return False
            queue.append(now)
            return True

    @staticmethod
    def _get_client_ip(request: Request) -> str:
        """Extrai IP real priorizando x-forwarded-for em ambiente com proxy."""
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "unknown"

    @classmethod
    def _is_secure_request(cls, request: Request) -> bool:
        """Aceita HTTPS real, proxy HTTPS confiavel e probes locais do container."""
        if request.url.scheme == "https":
            return True

        client_ip = cls._get_client_ip(request)
        if client_ip in {"127.0.0.1", "::1", "localhost"}:
            return True

        forwarded_proto = request.headers.get("x-forwarded-proto", "")
        if any(item.strip().lower() == "https" for item in forwarded_proto.split(",")):
            return True

        forwarded = request.headers.get("forwarded", "").lower()
        return "proto=https" in forwarded

    @staticmethod
    def _apply_security_headers(response: Response, request: Request) -> None:
        """Define headers padrao de seguranca e propaga o request id da chamada."""
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'; base-uri 'none';"
        response.headers["X-Request-Id"] = getattr(request.state, "request_id", str(uuid4()))

        if settings.require_https or request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
