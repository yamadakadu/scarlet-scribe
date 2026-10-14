# Imagem do backend, usada pelos serviços api e worker do docker-compose.yml.
# Contexto de build: raiz do repositório (ver .dockerignore na raiz).
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependências primeiro, para aproveitar o cache das camadas.
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --locked --no-dev --no-install-project

# Código do pacote, Alembic e o próprio projeto (instalado em modo editável).
COPY backend/ ./
RUN uv sync --locked --no-dev

EXPOSE 8000

CMD ["uvicorn", "scarlet_scribe.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
