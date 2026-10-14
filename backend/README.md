# scarlet-scribe (backend)

Pacote Python do backend: API (FastAPI), worker de sync e migrations (Alembic). Gerenciado com `uv`.

```bash
uv sync                                        # cria/atualiza o .venv
uv run uvicorn scarlet_scribe.api.app:app      # API
uv run scarlet-scribe-worker                   # worker de sync
uv run alembic upgrade head                    # aplica as migrations
```

As variáveis de ambiente estão documentadas no `.env.example` da raiz do repositório. O `.env` fica na raiz e é lido tanto a partir da raiz quanto de `backend/`.
