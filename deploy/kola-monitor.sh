#!/usr/bin/env bash
set -Eeuo pipefail

die() {
    printf 'kola-monitor: ERROR: %s\n' "$*" >&2
    exit 1
}

command -v curl >/dev/null 2>&1 || die "required command is missing: curl"
command -v logger >/dev/null 2>&1 || die "required command is missing: logger"
: "${MONITOR_HEALTH_URL:?Set MONITOR_HEALTH_URL to the deployed application's /health/ URL.}"

timeout_seconds="${MONITOR_TIMEOUT_SECONDS:-5}"
[[ "$timeout_seconds" =~ ^[0-9]+$ ]] && (( timeout_seconds > 0 )) || die "MONITOR_TIMEOUT_SECONDS must be a positive integer."

while true; do
    status="$(
        curl --silent --show-error --output /dev/null \
            --write-out '%{http_code}' \
            --max-time "$timeout_seconds" \
            "$MONITOR_HEALTH_URL" 2>/dev/null || true
    )"

    case "$status" in
        503)
            logger --priority user.err --tag kola-monitor "health endpoint returned HTTP 503"
            ;;
        2??)
            ;;
        *)
            logger --priority user.warning --tag kola-monitor "health endpoint returned HTTP ${status:-unknown}"
            ;;
    esac

    sleep 30
done
