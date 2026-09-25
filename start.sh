#!/bin/bash
set -e

echo "=================================================="
echo " Starting VERTEX Platform"
echo "=================================================="

# 1. Start FastAPI backend on internal port 8000
echo "[1/2] Starting FastAPI Backend on 127.0.0.1:8000..."
cd /app/backend
python -m uvicorn main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!

# Wait for FastAPI backend to be fully ready before starting Next.js
echo "Waiting for FastAPI backend to become ready..."
for i in $(seq 1 30); do
    if curl -s http://127.0.0.1:8000/api/v1/health >/dev/null 2>&1; then
        echo "FastAPI backend is ready on 127.0.0.1:8000 (attempt $i)."
        break
    fi
    sleep 1
done

# 2. Start Next.js frontend on public port (provided by Render via $PORT)
TARGET_PORT="${PORT:-10000}"
echo "[2/2] Starting Next.js Frontend on 0.0.0.0:${TARGET_PORT}..."
cd /app/frontend

# Gracefully terminate background processes on shutdown
cleanup() {
    echo "Shutting down VERTEX services..."
    kill -TERM "$BACKEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" 2>/dev/null || true
    exit 0
}
trap cleanup SIGTERM SIGINT

npx next start -p "$TARGET_PORT" -H 0.0.0.0 &
FRONTEND_PID=$!

# Wait for either process to terminate
wait -n "$BACKEND_PID" "$FRONTEND_PID"
