#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# uv installs to ~/.local/bin by default.
export PATH="$HOME/.local/bin:$PATH"

# Privacy / cache control (no telemetry)
export HF_HUB_DISABLE_TELEMETRY="1"
export HF_HUB_DISABLE_PROGRESS_BARS="1"
export HF_HOME="$SCRIPT_DIR/data/hf"

export PYTHONUNBUFFERED="1"
export PYTHONPATH="$SCRIPT_DIR/src"

if ! command -v uv >/dev/null 2>&1; then
  echo "[Speak->See] Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh -o /tmp/uv_install.sh
  sh /tmp/uv_install.sh
fi

if [[ ! -d "$SCRIPT_DIR/.venv" ]]; then
  echo "[Speak->See] Creating virtualenv..."
  # Prefer Python 3.11+; uv will auto-download if needed.
  uv python install 3.11 >/dev/null 2>&1 || true
  uv venv --python 3.11 "$SCRIPT_DIR/.venv" 2>/dev/null || uv venv "$SCRIPT_DIR/.venv"
fi

echo "[Speak->See] Syncing dependencies..."
uv sync --frozen 2>/dev/null || uv sync

HOST="${SPEAKSEE_HOST:-127.0.0.1}"
PORT="${SPEAKSEE_PORT:-7860}"
URL="http://${HOST}:${PORT}"

echo "[Speak->See] Starting server at $URL"

mkdir -p "$SCRIPT_DIR/data/logs"
LOG_FILE="$SCRIPT_DIR/data/logs/server.log"

if command -v lsof >/dev/null 2>&1; then
  if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "[Speak->See] ERROR: Port $PORT is already in use."
    echo "[Speak->See] Stop the process using $URL and re-run."
    lsof -nP -iTCP:"$PORT" -sTCP:LISTEN || true
    exit 1
  fi
fi

("$SCRIPT_DIR/.venv/bin/python" -m speaksee.server) >"$LOG_FILE" 2>&1 &
PID="$!"

cleanup() {
  kill "$PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "[Speak->See] Waiting for server..."
for _ in $(seq 1 60); do
  if ! kill -0 "$PID" >/dev/null 2>&1; then
    echo "[Speak->See] ERROR: Server exited during startup. Recent logs:"
    tail -n 120 "$LOG_FILE" || true
    exit 1
  fi
  if curl -sSf "$URL/" >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done

if command -v open >/dev/null 2>&1; then
  open "$URL" >/dev/null 2>&1 || true
fi

wait "$PID"
