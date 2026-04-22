from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.routes import nf_audits
from app.core.config import settings
from app.core.security import SecurityMiddleware
from app.db.init_db import init_db
from app.services.nf_audit_service import file_processor


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    try:
        if settings.database_url.startswith("sqlite:///"):
            init_db()
        yield
    finally:
        file_processor.shutdown()


app = FastAPI(
    title="NLC Document Intelligence API",
    version="0.2.0",
    description="API para upload, auditoria de notas fiscais com IA e exportacao de relatorios.",
    lifespan=lifespan,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

cors_allowed_origins = settings.cors_allowed_origins
if not cors_allowed_origins and settings.environment == "development":
    cors_allowed_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]

app.add_middleware(SecurityMiddleware)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=sorted({*settings.allowed_hosts, "localhost", "127.0.0.1"}),
)
if cors_allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_allowed_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id"],
    )

app.include_router(nf_audits.router, prefix="/api/v1", tags=["nf-audits"])


@app.get("/")
def root() -> dict[str, str]:
    return {"status": "ok", "health": "/health", "docs": "/docs"}


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, _: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Erro interno ao processar a solicitacao.", "request_id": request_id},
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
