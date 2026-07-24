# syntax=docker/dockerfile:1

FROM python:3.12-slim AS python-base

ARG APP_UID=10001
ARG APP_GID=10001

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/opt/venv/bin:${PATH}" \
    APP_HOST="0.0.0.0" \
    APP_PORT="8000" \
    APP_WORKERS="2" \
    UVICORN_LOG_LEVEL="info"

RUN groupadd --gid "${APP_GID}" --system app \
    && useradd --uid "${APP_UID}" --gid app --system --create-home app


FROM python-base AS builder

WORKDIR /build

RUN python -m venv /opt/venv

COPY pyproject.toml ./
COPY src ./src

RUN /opt/venv/bin/python -m pip install .


FROM python-base AS development

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

USER app

EXPOSE 8000

CMD ["sh", "-c", "exec uvicorn autonomous_ai_company.api.app:create_app --factory --host \"${APP_HOST}\" --port \"${APP_PORT}\" --reload --reload-dir /app/src --log-level \"${UVICORN_LOG_LEVEL}\""]


FROM python-base AS production

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"APP_PORT\", \"8000\")}/health', timeout=3).read()"

CMD ["sh", "-c", "exec uvicorn autonomous_ai_company.api.app:create_app --factory --host \"${APP_HOST}\" --port \"${APP_PORT}\" --workers \"${APP_WORKERS}\" --log-level \"${UVICORN_LOG_LEVEL}\""]
