FROM node:22-alpine AS web-build

WORKDIR /web
RUN corepack enable
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY web ./
RUN pnpm build

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# lxml/psycopg derleme bağımlılıkları
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install ".[discovery]"

COPY alembic.ini ./
COPY migrations ./migrations

COPY --from=web-build /web/dist ./web/dist

COPY seeds ./seeds

RUN groupadd --system jobradar \
    && useradd --system --gid jobradar --home-dir /app --no-create-home jobradar \
    && mkdir -p /app/data /app/secrets \
    && chown -R jobradar:jobradar /app

USER jobradar

EXPOSE 8000
CMD ["sh", "-c", "jobradar init-db && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
