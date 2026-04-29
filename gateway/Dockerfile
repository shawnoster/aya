# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

# Install runtime dependencies into the venv. Pinned ranges match
# pyproject.toml; will switch to a lockfile-driven install once we have
# more than two deps to manage.
RUN pip install --no-cache-dir \
    "fastapi>=0.115" \
    "uvicorn[standard]>=0.32"


FROM python:3.12-slim AS runtime

ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH

# Non-root runtime user. Numeric UID 1001 to avoid host UID collisions.
RUN groupadd --system --gid 1001 gateway \
    && useradd --system --uid 1001 --gid gateway --no-create-home gateway

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=gateway:gateway app /app/app

USER gateway
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8080/health').status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
