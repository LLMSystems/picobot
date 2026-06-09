#!/usr/bin/env sh

set -eu

echo "[1/4] Installing Node.js and npm..."
apt-get update
apt-get install -y nodejs npm
apt-get install -y bubblewrap

echo "[2/4] Installing Chrome runtime dependencies..."
apt-get install -y \
  libnspr4 \
  libnss3 \
  libatk-bridge2.0-0 \
  libatk1.0-0 \
  libcups2 \
  libdrm2 \
  libxkbcommon0 \
  libxcomposite1 \
  libxdamage1 \
  libxfixes3 \
  libxrandr2 \
  libgbm1 \
  libasound2 \
  libpango-1.0-0 \
  libcairo2 \
  libatspi2.0-0 \
  libgtk-3-0 \
  ca-certificates

apt-get update && apt-get install -y \
  fontconfig \
  fonts-noto-cjk \
  fonts-noto-color-emoji \
  fonts-dejavu-core \
  fonts-liberation

fc-cache -fv

echo "[3/4] Installing agent-browser..."
npm install -g agent-browser

echo "[4/4] Installing Chrome for agent-browser..."
agent-browser install

apt-get update && apt-get install -y xvfb
Xvfb :99 -screen 0 1280x800x24 -nolisten tcp &
export DISPLAY=:99

if ! command -v git >/dev/null 2>&1; then
  echo "git not found. Installing git..."
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update && apt-get install -y git
  else
    echo "Error: Package manager apt-get not found. Please install git manually."
    exit 1
  fi
fi

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
CONFIG_PATH="${CONFIG_PATH:-$SCRIPT_DIR/config.json}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8080}"

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

echo "Starting FastAPI server with config: $CONFIG_PATH"
echo "Using Python interpreter: $RESOLVED_PYTHON"
echo "script directory: $SCRIPT_DIR"

exec "$RESOLVED_PYTHON" "$SCRIPT_DIR/fastapi_server.py" \
  --config "$CONFIG_PATH" \
  --host "$HOST" \
  --port "$PORT"
