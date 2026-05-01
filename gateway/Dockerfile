# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy

# uv installs deps from the lockfile so the container matches dev/CI exactly.
RUN pip install --no-cache-dir uv

WORKDIR /build
COPY pyproject.toml uv.lock ./

# --no-install-project: install deps only, not the gateway "package"
# (app/ is mounted in via the runtime stage, not pip-installed).
RUN uv sync --frozen --no-dev --no-install-project


FROM python:3.12-slim AS runtime

ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH

# Non-root runtime user. Numeric UID 1001 to avoid host UID collisions.
# /home/gateway is intentionally minimal (no shell, no full home tree) — only
# the cache dir nanoleaf-kitt expects for its layout cache is pre-created.
RUN groupadd --system --gid 1001 gateway \
    && useradd --system --uid 1001 --gid gateway --no-create-home gateway \
    && mkdir -p /home/gateway/.config/nanoleaf-direct \
    && chown -R gateway:gateway /home/gateway

COPY --from=builder /opt/venv /opt/venv

# Effect runners (stdlib-only Python; no extra image deps).
# Layout cache is fetched on first use into /home/gateway/.config/nanoleaf-direct/
# and persists across container restarts in the writable layer.
COPY effects/nanoleaf-kitt /usr/local/bin/nanoleaf-kitt
RUN chmod 0755 /usr/local/bin/nanoleaf-kitt

WORKDIR /app
COPY --chown=gateway:gateway app /app/app

USER gateway
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8080/health', timeout=2).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
