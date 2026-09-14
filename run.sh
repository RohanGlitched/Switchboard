#!/usr/bin/env bash
# Start Switchboard.
#
#   ./run.sh              -> http://127.0.0.1:8000
#   PORT=9000 ./run.sh
#
# Credentials: anything already in your environment is used as-is. Set either
#   AWS_BEARER_TOKEN_BEDROCK   (a Bedrock API key), or
#   AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY, or
#   ANTHROPIC_API_KEY          (to bypass Bedrock entirely)
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-8000}"
PY="${PY:-}"

if [ -z "$PY" ]; then
  for c in .venv/bin/python "$HOME/sbvenv/bin/python" python3; do
    if [ -x "$c" ] || command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
  done
fi

if ! "$PY" -c "import strands" >/dev/null 2>&1; then
  echo "Strands not found for $PY. Install first:"
  echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

echo "Switchboard on http://127.0.0.1:${PORT}"
exec "$PY" -m uvicorn switchboard.server:app --host 0.0.0.0 --port "$PORT"
