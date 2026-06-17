#!/usr/bin/env bash
#
# Build a versioned AutoPM3 Docker image.
#
# Usage:
#   ./scripts/build.sh                       # default: autopm3:dev
#   ./scripts/build.sh 1.0.0                 # autopm3:1.0.0 + autopm3:latest (+ v1.0, v1)
#   ./scripts/build.sh v1.0.0                # leading 'v' is stripped
#   ./scripts/build.sh 1.0.0 --save          # export linux/amd64 + linux/arm64 .tar files
#   ./scripts/build.sh 1.0.0 --save --platforms linux/amd64,linux/arm64
#   ./scripts/build.sh 1.0.0 --no-latest     # skip the :latest tag
#   ./scripts/build.sh 1.0.0 --push user     # also push to Docker Hub as `user/autopm3:1.0.0`
#
# Requirements: bash 4+, docker, git.

set -euo pipefail

# ---------- args ----------
VERSION_RAW="dev"
VERSION_SET="false"
SAVE_TAR=""
NO_LATEST="false"
PUSH_USER=""
SAVE_PLATFORMS="linux/amd64,linux/arm64"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --save)        SAVE_TAR="true" ;;
    --platforms)
      if [[ -z "${2:-}" || "${2:-}" == --* ]]; then
        echo "--platforms requires a comma-separated platform list, e.g. linux/amd64,linux/arm64" >&2
        exit 2
      fi
      SAVE_PLATFORMS="${2}"
      shift
      ;;
    --no-latest)   NO_LATEST="true" ;;
    --push)
      if [[ -z "${2:-}" || "${2:-}" == --* ]]; then
        echo "--push requires a Docker Hub username or namespace" >&2
        exit 2
      fi
      PUSH_USER="${2}"
      shift
      ;;
    -h|--help)
      sed -n '2,12p' "$0"; exit 0 ;;
    *)
      if [[ "${VERSION_SET}" == "true" ]]; then
        echo "Unknown arg: $1" >&2
        exit 2
      fi
      VERSION_RAW="$1"
      VERSION_SET="true"
      ;;
  esac
  shift
done

# ---------- helpers ----------
# Strip leading 'v' so semver matching works.
VERSION="${VERSION_RAW#v}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker not found in PATH" >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "docker daemon not reachable (is it running?)" >&2
  exit 1
fi
if [[ "${SAVE_TAR}" == "true" ]]; then
  if ! docker buildx version >/dev/null 2>&1; then
    echo "docker buildx is required for per-platform tar exports" >&2
    exit 1
  fi
  if [[ -n "${PUSH_USER}" ]]; then
    echo "--save exports per-platform tar files. Use --push in a separate run for registry publishing." >&2
    exit 2
  fi
fi

# ---------- metadata ----------
GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
GIT_DIRTY=""
if [[ -n "${GIT_SHA}" && "${GIT_SHA}" != "unknown" ]]; then
  if ! git diff --quiet HEAD 2>/dev/null; then
    GIT_DIRTY="-dirty"
  fi
fi

# ISO 8601 UTC; works on both GNU and BSD date.
BUILD_DATE="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

echo "==> Building AutoPM3"
echo "    VERSION    = ${VERSION}"
echo "    GIT_SHA    = ${GIT_SHA}${GIT_DIRTY}"
echo "    BUILD_DATE = ${BUILD_DATE}"
if [[ "${SAVE_TAR}" == "true" ]]; then
  echo "    PLATFORMS  = ${SAVE_PLATFORMS}"
fi
echo

# ---------- tags ----------
TAG_ARGS=( "-t" "autopm3:${VERSION}" )

# Auto-add :1.0 / :1 / :latest for clean semver x.y.z
if [[ "${VERSION}" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)(-.+)?$ ]]; then
  TAG_ARGS+=( "-t" "autopm3:${BASH_REMATCH[1]}.${BASH_REMATCH[2]}" )
  TAG_ARGS+=( "-t" "autopm3:${BASH_REMATCH[1]}" )
fi

if [[ "${NO_LATEST}" != "true" ]]; then
  TAG_ARGS+=( "-t" "autopm3:latest" )
fi

# Always include the SHA tag so any build is reproducible.
TAG_ARGS+=( "-t" "autopm3:${VERSION}-${GIT_SHA}${GIT_DIRTY}" )

# ---------- build ----------
build_args=(
  --build-arg "VERSION=${VERSION}"
  --build-arg "GIT_SHA=${GIT_SHA}${GIT_DIRTY}"
  --build-arg "BUILD_DATE=${BUILD_DATE}"
  "${TAG_ARGS[@]}"
)

if [[ "${SAVE_TAR}" == "true" ]]; then
  IFS=',' read -r -a PLATFORM_LIST <<< "${SAVE_PLATFORMS}"
  for platform in "${PLATFORM_LIST[@]}"; do
    platform="${platform//[[:space:]]/}"
    if [[ -z "${platform}" ]]; then
      echo "empty platform in --platforms list" >&2
      exit 2
    fi

    platform_suffix="${platform//\//-}"
    OUT="autopm3-${VERSION}-${GIT_SHA}${GIT_DIRTY}-${platform_suffix}.tar"

    echo "==> Building ${platform}"
    docker buildx build \
      --platform "${platform}" \
      --load \
      "${build_args[@]}" \
      .

    echo
    echo "==> Saving ${platform} to ${OUT}"
    docker save -o "${OUT}" "autopm3:${VERSION}" "autopm3:${VERSION}-${GIT_SHA}${GIT_DIRTY}"
    ls -lh "${OUT}"
    echo
  done
else
  docker build \
    "${build_args[@]}" \
    .
fi

# ---------- optional push ----------
if [[ -n "${PUSH_USER}" ]]; then
  echo
  echo "==> Pushing to docker.io/${PUSH_USER}/autopm3"
  for tag in "${VERSION}" "${VERSION}-${GIT_SHA}${GIT_DIRTY}"; do
    docker tag "autopm3:${tag}" "${PUSH_USER}/autopm3:${tag}"
    docker push "${PUSH_USER}/autopm3:${tag}"
  done
  if [[ "${NO_LATEST}" != "true" ]]; then
    docker tag "autopm3:latest" "${PUSH_USER}/autopm3:latest"
    docker push "${PUSH_USER}/autopm3:latest"
  fi
fi

# ---------- summary ----------
echo
echo "==> Done. Image tags:"
docker images autopm3 --format "    {{.Repository}}:{{.Tag}}\t({{.Size}}, created {{.CreatedSince}})"

# Echo the OCI version label so the user can sanity-check.
VERSION_LABEL="$(docker inspect "autopm3:${VERSION}" --format '{{ index .Config.Labels "org.opencontainers.image.version" }}' 2>/dev/null || echo "<not set>")"
echo
echo "    OCI label org.opencontainers.image.version = ${VERSION_LABEL}"
