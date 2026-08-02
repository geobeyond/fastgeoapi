# Hardened, registry-agnostic image for fastgeoapi (published to GHCR).
#
# Base choice: python:3.12-slim, NOT the GDAL/ubuntu image the fly.io
# deployment uses. The geospatial wheels we depend on ship their own
# native libraries (rasterio bundles GDAL, shapely bundles GEOS); a
# system GDAL is only needed by pygeoapi's optional providers, which
# this runtime does not enable. Dropping it removes a large attack
# surface along with the size.
#
# Multi-stage: git and the uv toolchain live in the builder only; the
# runtime carries the virtualenv plus the application, nothing else —
# no build toolchain, no repository checkout, no baked .env.

# ---------- builder ----------
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.10.9 /uv /bin/uv

# git resolves the git-sourced dependencies pinned in uv.lock
RUN apt-get update \
    && apt-get install --yes --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml uv.lock ./

# Install into a self-contained virtualenv, pinned to uv.lock.
# `uv export --frozen` only transcribes the lockfile (it fails on a
# stale lock), with git sources pinned to exact commits — no fresh
# resolution, so rebuilds are reproducible instead of silently picking
# up brand-new upstream releases.
ENV UV_LINK_MODE=copy
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /opt/venv \
    && uv export --frozen --no-dev --no-emit-project --no-hashes -o /tmp/requirements.lock \
    && VIRTUAL_ENV=/opt/venv uv pip install -r /tmp/requirements.lock

# ---------- runtime ----------
FROM python:3.12-slim AS runtime

# tini reaps zombies and forwards signals for a clean shutdown
RUN apt-get update \
    && apt-get install --yes --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser

COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FASTGEOAPI_CACHE_DIR=/home/appuser/.cache/fastgeoapi \
    LOG_PATH=/tmp

WORKDIR /home/appuser/app
COPY --chown=appuser:appuser app ./app
# Default pygeoapi configuration + the 40K demo dataset it references,
# so `docker run` serves a working API out of the box. Both are meant
# to be overridden at runtime (PYGEOAPI_CONFIG + a mounted volume or
# config store) for real deployments.
COPY --chown=appuser:appuser pygeoapi-config.yml ./
COPY --chown=appuser:appuser tests/data ./tests/data

# Configuration is supplied by the environment (12-factor) or by a
# config store mounted at runtime: no .env is baked into the image.
RUN mkdir -p /home/appuser/.cache/fastgeoapi \
    && chown -R appuser:appuser /home/appuser

ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=$GIT_COMMIT

LABEL org.opencontainers.image.source="https://github.com/geobeyond/fastgeoapi" \
      org.opencontainers.image.description="Security facade for OGC API servers (pygeoapi) with OIDC, OPA and MCP" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.revision=$GIT_COMMIT

USER appuser
EXPOSE 5000

# Liveness against the unauthenticated probe orchestrators use.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/healthz', timeout=4).status == 200 else 1)"

ENTRYPOINT ["tini", "-g", "--"]
# uvicorn directly rather than the `fastapi run` CLI: the CLI expects a
# project layout (pyproject.toml) that a runtime-only image has no
# reason to carry, and resolving the app by import path is unambiguous.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5000", "--proxy-headers", "--forwarded-allow-ips", "*"]
