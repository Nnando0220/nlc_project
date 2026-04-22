"""Configuracao de engine, sessao e metadata do SQLAlchemy."""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings


def _ensure_sqlite_directory() -> None:
	"""Garante que o diretorio do arquivo SQLite exista antes da conexao."""
	if not settings.database_url.startswith("sqlite:///"):
		return
	db_file = settings.database_url.replace("sqlite:///", "", 1)
	db_path = Path(db_file)
	if not db_path.is_absolute():
		db_path = Path.cwd() / db_path
	db_path.parent.mkdir(parents=True, exist_ok=True)


# Em SQLite local, o diretorio do arquivo precisa existir antes de criar a engine.
_ensure_sqlite_directory()

engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
Base = declarative_base()
