Estrutura Alembic ativa para migracoes versionadas do banco.

Fluxo recomendado:

1. Instalar dependencias do backend.
2. Rodar `alembic upgrade head` dentro de `backend/`.
3. Subir a aplicacao FastAPI.

Arquivos principais:

- `alembic.ini`: configuracao do Alembic
- `alembic/env.py`: integracao com `app.core.config` e metadata SQLAlchemy
- `alembic/schema.sql`: snapshot base do schema SQL usado na migration inicial
- `alembic/versions/*.py`: migracoes versionadas

Observacao:

- O startup da API nao cria mais schema automaticamente.
- Em ambiente novo, rode a migration antes de iniciar o servidor.
- `app/db/init_db.py` ficou apenas como apoio para testes automatizados e cenarios legados.
