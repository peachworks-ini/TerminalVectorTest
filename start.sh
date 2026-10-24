#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
BASE_URL="http://127.0.0.1:8080"
COMPOSE=(docker compose -f docker-compose.yml)
VIEWER_PID=""
COMPOSE_ATTEMPTED=0
FAILURE_LOG="$SCRIPT_DIR/.terminalvector-failure.log"

cleanup() {
  status=$?
  trap - EXIT INT TERM
  if [[ "$status" != 0 && "$COMPOSE_ATTEMPTED" == 1 ]]; then
    echo "[TerminalVector] Startup or runtime failed; collecting Docker diagnostics before cleanup..." >&2
    "${COMPOSE[@]}" ps >&2 || true
    "${COMPOSE[@]}" logs --no-color --tail=150 terminalvector director 2>&1 | tee "$FAILURE_LOG" >&2 || true
    echo "[TerminalVector] Diagnostic log saved to: $FAILURE_LOG" >&2
  fi
  if [[ -n "$VIEWER_PID" ]] && kill -0 "$VIEWER_PID" >/dev/null 2>&1; then
    kill "$VIEWER_PID" >/dev/null 2>&1 || true
    wait "$VIEWER_PID" 2>/dev/null || true
  fi
  if [[ "$COMPOSE_ATTEMPTED" == 1 ]]; then
    echo "[TerminalVector] Stopping Docker services..."
    "${COMPOSE[@]}" down --remove-orphans >/dev/null 2>&1 || true
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

command -v docker >/dev/null || { echo "Docker is required. Install Docker Desktop for Apple silicon and retry." >&2; exit 1; }

if [[ "$(uname -s)" == "Darwin" ]] && ! docker info >/dev/null 2>&1; then
  echo "[TerminalVector] Starting Docker Desktop..."
  open -a Docker >/dev/null 2>&1 || true
  for _ in {1..120}; do
    docker info >/dev/null 2>&1 && break
    sleep 1
  done
fi
docker info >/dev/null 2>&1 || { echo "Docker Engine did not start. Start Docker Desktop and retry." >&2; exit 1; }

if [[ "${HEADLESS:-0}" == "1" ]]; then
  export TERMINALVECTOR_HEADLESS=1
fi

echo "[TerminalVector] Building and starting the linux/arm64 backend and automated director..."
COMPOSE_ATTEMPTED=1
"${COMPOSE[@]}" up -d --build

ready=0
for _ in {1..60}; do
  if curl --silent --fail --max-time 1 "$BASE_URL/health" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [[ "$ready" != 1 ]]; then
  echo "Backend did not become ready on port 8080." >&2
  if command -v lsof >/dev/null 2>&1; then
    echo "Current port 8080 listener, if any:" >&2
    lsof -nP -iTCP:8080 -sTCP:LISTEN >&2 || true
  fi
  exit 1
fi

if [[ "$(uname -s)" == "Darwin" && "${HEADLESS:-0}" != "1" ]]; then
  NATIVE_VIEWER_BIN="$SCRIPT_DIR/TerminalVectorViewer"
  if [[ ! -x "$NATIVE_VIEWER_BIN" ]]; then
    echo "The bundled macOS viewer is missing: $NATIVE_VIEWER_BIN" >&2
    exit 1
  fi
  echo "[TerminalVector] Opening the control room and program preview in their demo positions..."
  "$NATIVE_VIEWER_BIN" "$BASE_URL" &
  VIEWER_PID=$!
  wait "$VIEWER_PID"
else
  echo "[TerminalVector] Headless show running. Press Ctrl-C to stop."
  "${COMPOSE[@]}" logs --follow director
fi

echo "[TerminalVector] Demo ended. Docker will be stopped."
