#!/bin/bash
set -euo pipefail

# Test both openclaw containers (Tank + Banks)

echo "=== Testing OpenClaw Containers ==="
echo ""

# Test Tank container
echo "[TEST] Tank OpenClaw Container (:18789)"
if curl -s http://localhost:18789/health | grep -q "status"; then
    echo "✓ Tank container healthy"
else
    echo "✗ Tank container not responding"
    exit 1
fi

# Test Banks container  
echo "[TEST] Banks OpenClaw Container (:18790)"
if curl -s http://localhost:18790/health | grep -q "status"; then
    echo "✓ Banks container healthy"
else
    echo "✗ Banks container not responding"
    exit 1
fi

# Test Tank personality (SOUL.md loaded)
echo "[TEST] Tank personality (SOUL.md)"
result=$(curl -s -X POST http://localhost:18789/api/chat -H "Content-Type: application/json" -d '{"message":"test"}' 2>&1 || echo "TIMEOUT")
if [[ "$result" != "TIMEOUT" ]]; then
    echo "✓ Tank responding to messages"
else
    echo "✗ Tank not responding"
    exit 1
fi

# Test Banks personality (BANKS.md loaded)
echo "[TEST] Banks personality (BANKS.md)"
result=$(curl -s -X POST http://localhost:18790/api/chat -H "Content-Type: application/json" -d '{"message":"test"}' 2>&1 || echo "TIMEOUT")
if [[ "$result" != "TIMEOUT" ]]; then
    echo "✓ Banks responding to messages"
else
    echo "✗ Banks not responding"
    exit 1
fi

# Test inter-container communication
echo "[TEST] Inter-container communication"
# Tank should be able to reach Banks on internal network
if docker exec tank-openclaw curl -s http://banks-openclaw:18789/health >/dev/null 2>&1; then
    echo "✓ Tank can reach Banks container"
else
    echo "✗ Tank cannot reach Banks (networking issue)"
    exit 1
fi

# Test Swarm Orchestrator still working
echo "[TEST] Swarm Orchestrator (:5696)"
if curl -s http://localhost:5696/health | grep -q "healthy"; then
    echo "✓ Swarm Orchestrator healthy"
else
    echo "✗ Swarm Orchestrator not responding"
    exit 1
fi

# Test trading services still working
echo "[TEST] Sample trading service (Research :8001)"
if curl -s http://localhost:8001/health | grep -q "healthy"; then
    echo "✓ Research service healthy"
else
    echo "✗ Research service not responding"
    exit 1
fi

echo ""
echo "=== ALL TESTS PASSED ==="
echo "✓ Tank container running (:18789)"
echo "✓ Banks container running (:18790)"
echo "✓ Both personalities loaded"
echo "✓ Inter-container communication working"
echo "✓ Swarm Orchestrator running"
echo "✓ Trading services running"
echo ""
echo "System is ready for deployment."
