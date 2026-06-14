#!/bin/bash
set -e

echo "=== FastAgent Bootstrap ==="
uv run python -m app.bootstrap

echo "=== Starting API Server ==="
exec uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
