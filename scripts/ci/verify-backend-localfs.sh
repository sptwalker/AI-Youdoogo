#!/usr/bin/env bash
set -Eeuo pipefail

: "${CI_PROJECT_DIR:?CI_PROJECT_DIR is required}"
: "${CI_COMMIT_SHA:?CI_COMMIT_SHA is required}"

if [ ! -d "$CI_PROJECT_DIR" ]; then
    printf 'CI_PROJECT_DIR does not exist: %s\n' "$CI_PROJECT_DIR" >&2
    exit 1
fi

workdir="/tmp/youdoogo-verify-${CI_JOB_ID:-local}"
local_uv_cache="/tmp/youdoogo-uv-cache-${CI_JOB_ID:-local}"
source_uv_cache="${UV_CACHE_DIR:-$CI_PROJECT_DIR/.cache/uv}"

if [[ "$source_uv_cache" == '$CI_PROJECT_DIR/'* ]]; then
    source_uv_cache="$CI_PROJECT_DIR/${source_uv_cache#\$CI_PROJECT_DIR/}"
elif [[ "$source_uv_cache" == '${CI_PROJECT_DIR}/'* ]]; then
    source_uv_cache="$CI_PROJECT_DIR/${source_uv_cache#\$\{CI_PROJECT_DIR\}/}"
elif [[ "$source_uv_cache" != /* ]]; then
    source_uv_cache="$CI_PROJECT_DIR/$source_uv_cache"
fi

cleanup() {
    rm -rf -- "$workdir" "$local_uv_cache"
}
trap cleanup EXIT

command -v git >/dev/null
command -v tar >/dev/null

rm -rf -- "$workdir"
mkdir -p -- "$workdir"

if git -C "$CI_PROJECT_DIR" cat-file -e "$CI_COMMIT_SHA:.env" 2>/dev/null; then
    printf 'Refusing to verify commit with tracked .env\n' >&2
    exit 1
fi

(
    cd "$CI_PROJECT_DIR"
    git archive --format=tar "$CI_COMMIT_SHA" | tar -xf - -C "$workdir"
)

cd "$workdir"

export UV_CACHE_DIR="$local_uv_cache"
mkdir -p -- "$UV_CACHE_DIR"

if [ -d "$source_uv_cache" ] && [ "$source_uv_cache" != "$UV_CACHE_DIR" ]; then
    (
        cd "$source_uv_cache"
        tar -cf - . | tar -xf - -C "$UV_CACHE_DIR"
    )
fi

uv sync --frozen
uv run --frozen ruff check .
uv run --frozen mypy app
uv run --frozen pytest -q -m "not delivery_contract" --durations=25 --cov=app --cov-report=term-missing:skip-covered
