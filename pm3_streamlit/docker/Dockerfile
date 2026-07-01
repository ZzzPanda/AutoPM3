# syntax=docker/dockerfile:1.7
FROM python:3.11-slim

# Build-time metadata (provided by scripts/build.sh)
ARG VERSION=dev
ARG GIT_SHA=unknown
ARG BUILD_DATE=unknown

# OCI image labels — viewable via `docker inspect`
LABEL org.opencontainers.image.title="AutoPM3" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.source="https://github.com/<org>/AutoPM3" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app

# Try `pip install` with pre-built wheels only first; if a package needs to
# be compiled from source, fall back to installing build-essential and retrying.
# This saves ~14s on the common path where every requirement ships a wheel.
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    set -eux; \
    if ! pip install -r requirements.txt; then \
        echo "==> pip install failed, installing build-essential and retrying..." >&2; \
        apt-get update; \
        apt-get install -y --no-install-recommends build-essential; \
        pip install -r requirements.txt; \
    fi

# Copy application code (kept as a separate layer for cache friendliness).
# Use explicit COPY (not `COPY . .`) so the image only contains what the app
# actually needs — docs/, benchmarks/, docker/, config/ etc. are excluded
# by virtue of not being copied. `data/protein.txt` is the only data file
# required at runtime (resolved via __file__ from app/core/query.py).
COPY app ./app
COPY data/protein.txt ./data/protein.txt

# Surface the same metadata to the running process so the app can show it
ENV APP_VERSION=${VERSION} \
    APP_GIT_SHA=${GIT_SHA} \
    APP_BUILD_DATE=${BUILD_DATE}

# Expose Streamlit port
EXPOSE 8501

# Default command — runs main page
CMD ["streamlit", "run", "app/main.py", "--server.port=8501", "--server.address=0.0.0.0"]
