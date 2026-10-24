#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-8050}"
LOG="${LOG:-/tmp/laberinto-server.log}"

if command -v lsof >/dev/null 2>&1; then
  if lsof -ti tcp:"$PORT" >/dev/null 2>&1; then
    lsof -ti tcp:"$PORT" | xargs kill 2>/dev/null || true
    sleep 1
  fi
else
  pkill -f "maze serve --port $PORT" 2>/dev/null || true
  sleep 1
fi

nohup uv run maze serve --port "$PORT" >"$LOG" 2>&1 &
echo "Laberinto server restarted on http://127.0.0.1:$PORT"
echo "log: $LOG"
