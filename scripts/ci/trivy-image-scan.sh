#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "usage: $0 IMAGE" >&2
  exit 2
fi

: "${TRIVY_SEVERITY:?TRIVY_SEVERITY is required}"

image_ref=$1
max_attempts=3
attempt=1
retry_delay=${TRIVY_DB_RETRY_DELAY_SECONDS:-2}

case "$retry_delay" in
  ''|*[!0-9]*)
    echo "TRIVY_DB_RETRY_DELAY_SECONDS must be a non-negative integer" >&2
    exit 2
    ;;
esac

tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT HUP INT TERM

is_retryable_db_download_failure() {
  log_file=$1

  # Once Trivy emitted a report, the scan ran. Its non-zero status may be the
  # required vulnerability gate and must never be retried.
  if grep -Eiq 'report summary|total:[[:space:]]*[0-9]+' "$log_file"; then
    return 1
  fi

  # Authentication, authorization, repository, and image lookup failures are
  # never transient for this wrapper, even if another line mentions a timeout.
  if grep -Eiq \
    'unauthorized|authentication required|access forbidden|(^|[^[:alpha:]])denied([^[:alpha:]]|$)|manifest[_ ]unknown|name[_ ]unknown|not found|no such image|(^|[^0-9])(401|403)([^0-9]|$)' \
    "$log_file"; then
    return 1
  fi

  # Match a single error line that identifies both a Trivy DB download and a
  # narrow, explicitly temporary network condition. Other scan failures keep
  # their original exit status and are not retried.
  awk '
    {
      line = tolower($0)
      db = line ~ /(vulnerability db|java db|\[vulndb\]|\[javadb\])/ \
        && line ~ /(download|fetch|update)/ \
        && line ~ /(fail|error)/
      transient = line ~ /(context deadline exceeded|timeout|timed out|tls handshake timeout|i\/o timeout|connection reset|connection refused|temporary failure|no such host|network is unreachable|unexpected eof|too many requests|toomanyrequests|(^|[^0-9])(429|500|502|503|504)([^0-9]|$))/
      if (db && transient) {
        found = 1
      }
    }
    END { exit found ? 0 : 1 }
  ' "$log_file"
}

while [ "$attempt" -le "$max_attempts" ]; do
  log_file="$tmp_dir/attempt-$attempt.log"
  status_file="$tmp_dir/attempt-$attempt.status"

  set +e
  (
    trivy image \
      --scanners vuln \
      --exit-code 1 \
      --severity "$TRIVY_SEVERITY" \
      "$image_ref"
    printf '%s\n' "$?" >"$status_file"
  ) 2>&1 | tee "$log_file"
  tee_status=$?
  set -e

  if [ "$tee_status" -ne 0 ]; then
    exit "$tee_status"
  fi
  if [ ! -s "$status_file" ]; then
    echo "Trivy terminated before reporting an exit status" >&2
    exit 1
  fi
  status=$(cat "$status_file")

  if [ "$status" -eq 0 ]; then
    exit 0
  fi

  if [ "$attempt" -ge "$max_attempts" ] || \
    ! is_retryable_db_download_failure "$log_file"; then
    exit "$status"
  fi

  echo "Trivy DB download hit a temporary network error; retrying attempt $((attempt + 1))/$max_attempts in ${retry_delay}s" >&2
  sleep "$retry_delay"
  attempt=$((attempt + 1))
  retry_delay=$((retry_delay * 2))
done
