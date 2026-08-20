ARG PYTHON_IMAGE="python:3.12-slim-trixie@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36"
ARG UV_VERSION="0.12.3"
ARG UV_IMAGE="ghcr.io/astral-sh/uv:${UV_VERSION}@sha256:2d890623d310b57771ce840f0da5eed5fc6d657da05ffaa45d82797b53fa3abc"

FROM ${UV_IMAGE} AS uv
FROM ${PYTHON_IMAGE} AS builder

ARG VCS_REF
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/agent-venv \
    UV_PYTHON_DOWNLOADS=never

COPY --from=uv /uv /uvx /usr/local/bin/
WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY agent/pyproject.toml ./agent/pyproject.toml
COPY eval/pyproject.toml ./eval/pyproject.toml
RUN test -n "${VCS_REF}" \
    && uv sync \
      --frozen \
      --package syshin0116-dev-agent \
      --no-dev \
      --no-install-project

COPY agent/src ./agent/src
COPY agent/skills ./agent/skills
COPY agent/bm25-policy.toml agent/corpus-policy.toml ./agent/
RUN uv sync \
      --frozen \
      --package syshin0116-dev-agent \
      --no-dev \
      --no-editable

COPY content ./content
COPY scripts/build_index.py ./scripts/build_index.py
RUN /opt/agent-venv/bin/python scripts/build_index.py

FROM ${PYTHON_IMAGE} AS runtime

ARG VCS_REF
LABEL org.opencontainers.image.source="https://github.com/syshin0116/syshin0116.dev" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.title="syshin0116.dev native Aegra agent"

ENV AEGRA_CONFIG=/app/aegra.json \
    BLOG_INDEX_PATH=/app/agent/.index \
    HOST=0.0.0.0 \
    PATH=/opt/agent-venv/bin:${PATH} \
    PORT=8080 \
    PYTHONPATH=/app/agent/src \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1

RUN groupadd --gid 10001 agent \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin agent

WORKDIR /app
COPY --from=builder --chown=10001:10001 /opt/agent-venv /opt/agent-venv
COPY --chown=10001:10001 aegra.json ./aegra.json
COPY --chown=10001:10001 agent/src ./agent/src
COPY --chown=10001:10001 agent/skills ./agent/skills
COPY --from=builder --chown=10001:10001 /app/agent/.index ./agent/.index

USER 10001:10001
EXPOSE 8080

ENTRYPOINT ["uvicorn"]
CMD ["aegra_api.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
