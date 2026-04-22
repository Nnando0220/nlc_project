"""Dependencias compartilhadas da camada de API."""

from collections.abc import Generator

from sqlalchemy.orm import Session

from app.db.session import SessionLocal


def get_db() -> Generator[Session, None, None]:
    """Cria uma sessao por request e garante fechamento ao final."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

__all__ = ["get_db"]
