#!/usr/bin/env bash
set -Eeuo pipefail

base_url="https://ai.youdoogo.com/"
health_url="https://ai.youdoogo.com/api/v1/health"
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

fetch() {
  local url="$1" body="$2" headers="$3" metadata="$4"
  curl --fail --silent --show-error \
    --proto '=https' --tlsv1.2 \
    --location --max-redirs 3 \
    --retry 12 --retry-delay 5 --retry-all-errors \
    --connect-timeout 10 --max-time 30 \
    --dump-header "$headers" --output "$body" \
    --write-out '%{http_code}\n%{url_effective}\n' \
    "$url" >"$metadata"
}

fetch "$base_url" "$work_dir/root.html" "$work_dir/root.headers" "$work_dir/root.meta"
mapfile -t root_meta <"$work_dir/root.meta"
if [[ "${root_meta[0]:-}" != "200" || "${root_meta[1]:-}" != "$base_url" ]]; then
  echo "ERROR: root smoke ended at ${root_meta[1]:-unknown} with HTTP ${root_meta[0]:-unknown}" >&2
  exit 1
fi
grep -Eiq '^content-type:[[:space:]]*text/html' "$work_dir/root.headers"
grep -q '<title>创想悦动AI决策大脑</title>' "$work_dir/root.html"

fetch "$health_url" "$work_dir/health.json" "$work_dir/health.headers" "$work_dir/health.meta"
mapfile -t health_meta <"$work_dir/health.meta"
if [[ "${health_meta[0]:-}" != "200" || "${health_meta[1]:-}" != "$health_url" ]]; then
  echo "ERROR: health smoke ended at ${health_meta[1]:-unknown} with HTTP ${health_meta[0]:-unknown}" >&2
  exit 1
fi
grep -Eiq '^content-type:[[:space:]]*application/json' "$work_dir/health.headers"
python3 - "$work_dir/health.json" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert payload.get("code") == 0, payload
data = payload.get("data", {})
assert data.get("version"), payload
assert data.get("env") == "production", payload
PY

echo "Public smoke passed for ${base_url} and ${health_url}"
