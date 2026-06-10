#!/usr/bin/env sh
set -eu

# Headless Chrome (used by agent-browser) needs an X display.
if command -v Xvfb >/dev/null 2>&1; then
  Xvfb :99 -screen 0 1280x800x24 -nolisten tcp >/dev/null 2>&1 &
fi
export DISPLAY="${DISPLAY:-:99}"

exec python3 fastapi_server.py \
  --config "${PICOBOT_CONFIG:-example_config.json}" \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --db-path "${PICOBOT_DB_PATH:-/app/data/sessions.db}"
