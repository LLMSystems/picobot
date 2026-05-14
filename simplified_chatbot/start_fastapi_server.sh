#!/usr/bin/env sh

set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
CONFIG_PATH="${CONFIG_PATH:-$SCRIPT_DIR/config.json}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

if [ -n "${PYTHON_BIN:-}" ]; then
  RESOLVED_PYTHON="$PYTHON_BIN"
elif command -v python3 >/dev/null 2>&1; then
  RESOLVED_PYTHON="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  RESOLVED_PYTHON="$(command -v python)"
else
  echo "Error: Could not find python3 or python in PATH"
  exit 1
fi

if [ ! -f "$CONFIG_PATH" ]; then
  echo "Error: Config not found at $CONFIG_PATH"
  exit 1
fi

cd "$SCRIPT_DIR"

exec "$RESOLVED_PYTHON" "$SCRIPT_DIR/fastapi_server.py" \
  --config "$CONFIG_PATH" \
  --host "$HOST" \
  --port "$PORT"
