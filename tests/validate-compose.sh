#!/usr/bin/env bash
# Quick docker-compose validation — no running stack needed
set -euo pipefail

cd "$(dirname "$0")/.."

echo "[validate] Checking docker-compose.yml syntax..."
docker compose config -q && echo "[OK] Syntax valid"

echo "[validate] Services defined:"
docker compose config --services | sort | while read -r svc; do
    echo "  - $svc"
done

SVC_COUNT=$(docker compose config --services | wc -l | tr -d ' ')
echo "[validate] Total: $SVC_COUNT services"

echo "[validate] Checking required files..."
REQUIRED=(
    "Dockerfile"
    "Dockerfile.gateway"
    "backup-sync.sh"
    "setup.sh"
    "requirements.txt"
    "infra/postgres/init-dbs.sh"
    "infra/prometheus/prometheus.yml"
    "infra/alertmanager/alertmanager.yml"
    "gateway/server.js"
    "agent/main.py"
)
MISSING=0
for f in "${REQUIRED[@]}"; do
    if [[ -f "$f" ]]; then
        echo "  [OK] $f"
    else
        echo "  [MISSING] $f"
        ((MISSING++)) || true
    fi
done

# Check for service source directories
echo "[validate] Checking service source directories..."
EXPECTED_SVCS=(
    api-proxy research decision executor ledger tournament monitor memory-sync
    banks-service meta-builder risk-manager portfolio-tracker market-data
    signal-generator order-router position-manager alert-service report-generator
    backtest-runner strategy-optimizer feed-aggregator auth-service
    notification-service analytics-service
)
MISSING_SVCS=0
for svc in "${EXPECTED_SVCS[@]}"; do
    if [[ -f "services/${svc}/main.py" && -f "services/${svc}/Dockerfile" ]]; then
        echo "  [OK] services/${svc}/"
    else
        echo "  [MISSING] services/${svc}/"
        ((MISSING_SVCS++)) || true
    fi
done
echo "[validate] Service directories: $((${#EXPECTED_SVCS[@]} - MISSING_SVCS))/${#EXPECTED_SVCS[@]} present"
if [[ "$MISSING_SVCS" -gt 0 ]]; then
    echo "[WARN] $MISSING_SVCS service directories missing"
fi

if [[ "$MISSING" -gt 0 ]]; then
    echo "[WARN] $MISSING required files missing"
    exit 1
else
    echo "[OK] All required files present"
fi
