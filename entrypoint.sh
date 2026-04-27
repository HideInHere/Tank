#!/usr/bin/env bash
set -euo pipefail

# ── Wait for PostgreSQL ───────────────────────────────────────────────────────
echo "[entrypoint] Waiting for PostgreSQL at ${POSTGRES_HOST:-postgres}:${POSTGRES_PORT:-5432}..."
pg_deadline=$(( $(date +%s) + 60 ))
pg_ready=false
while [ "$(date +%s)" -lt "$pg_deadline" ]; do
    if pg_isready -h "${POSTGRES_HOST:-postgres}" -p "${POSTGRES_PORT:-5432}" -U "${POSTGRES_USER:-tank}" -q; then
        echo "[entrypoint] PostgreSQL is ready."
        pg_ready=true
        break
    fi
    sleep 2
done
if [ "$pg_ready" = false ]; then
    echo "[entrypoint] WARNING: PostgreSQL not ready after 60s — continuing anyway."
fi

# ── Wait for Redis ────────────────────────────────────────────────────────────
echo "[entrypoint] Waiting for Redis at ${REDIS_HOST:-redis}:${REDIS_PORT:-6379}..."
redis_deadline=$(( $(date +%s) + 30 ))
redis_ready=false
while [ "$(date +%s)" -lt "$redis_deadline" ]; do
    if redis-cli -h "${REDIS_HOST:-redis}" -p "${REDIS_PORT:-6379}" -a "${REDIS_PASSWORD:-}" ping 2>/dev/null | grep -q "PONG"; then
        echo "[entrypoint] Redis is ready."
        redis_ready=true
        break
    fi
    sleep 2
done
if [ "$redis_ready" = false ]; then
    echo "[entrypoint] WARNING: Redis not ready after 30s — continuing anyway."
fi

# ── Wait for openclaw-gateway ─────────────────────────────────────────────────
echo "[entrypoint] Waiting for openclaw-gateway at http://openclaw-gateway:18789/health..."
gw_deadline=$(( $(date +%s) + 90 ))
gw_ready=false
while [ "$(date +%s)" -lt "$gw_deadline" ]; do
    if curl -sf http://openclaw-gateway:18789/health > /dev/null 2>&1; then
        echo "[entrypoint] openclaw-gateway is ready."
        gw_ready=true
        break
    fi
    sleep 3
done
if [ "$gw_ready" = false ]; then
    echo "[entrypoint] WARNING: openclaw-gateway not ready after 90s — continuing anyway."
fi

# ── Start agent ───────────────────────────────────────────────────────────────
echo "[entrypoint] Starting Tank Agent on port ${SERVICE_PORT:-9000}..."
exec python -m uvicorn agent.main:app \
    --host 0.0.0.0 \
    --port "${SERVICE_PORT:-9000}" \
    --workers 1
