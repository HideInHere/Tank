#!/usr/bin/env bash
# ============================================================
# Tank Trading System — End-to-End Test Suite
# Usage: bash tests/test-e2e.sh [--quick] [--verbose]
# Requirements: docker, curl, jq
# ============================================================
set -euo pipefail

QUICK=false
VERBOSE=false
PASS=0
FAIL=0
SKIP=0

# Parse args
for arg in "$@"; do
    case "$arg" in
        --quick)   QUICK=true ;;
        --verbose) VERBOSE=true ;;
    esac
done

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

pass() { echo -e "  ${GREEN}✓${NC} $1"; ((PASS++)); }
fail() { echo -e "  ${RED}✗${NC} $1"; ((FAIL++)); }
skip() { echo -e "  ${YELLOW}○${NC} $1 (skipped)"; ((SKIP++)); }
section() { echo -e "\n${BOLD}${BLUE}═══ $1 ═══${NC}"; }

# Helper: curl with timeout, return HTTP status code
http_status() {
    curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 10 "$1" 2>/dev/null || echo "000"
}

# Helper: curl and get body
http_body() {
    curl -s --connect-timeout 5 --max-time 10 "$1" 2>/dev/null || echo "{}"
}

# Helper: POST with body
http_post() {
    curl -s -X POST -H "Content-Type: application/json" \
        --connect-timeout 5 --max-time 10 -d "$2" "$1" 2>/dev/null || echo "{}"
}

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║   Tank Trading System — E2E Tests        ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════╝${NC}"

# ── Section 1: Docker Compose Validation ──────────────────────────────────────
section "Docker Compose Validation"

if docker compose config -q 2>/dev/null; then
    pass "docker-compose.yml syntax valid"
else
    fail "docker-compose.yml syntax invalid"
fi

SVC_COUNT=$(docker compose config --services 2>/dev/null | wc -l | tr -d ' ')
if [[ "$SVC_COUNT" -ge 30 ]]; then
    pass "Service count: $SVC_COUNT (>=30 expected)"
else
    fail "Service count: $SVC_COUNT (expected >=30)"
fi

# ── Section 2: Infrastructure Health ──────────────────────────────────────────
section "Infrastructure Health"

# PostgreSQL — check via docker exec
if docker exec tank-postgres pg_isready -U "${POSTGRES_USER:-tank}" >/dev/null 2>&1; then
    pass "PostgreSQL (port 5432) — ready"
else
    fail "PostgreSQL (port 5432) — not ready"
fi

# Redis — check via docker exec
if docker exec tank-redis redis-cli -a "${REDIS_PASSWORD:-changeme_redis}" PING 2>/dev/null | grep -q PONG; then
    pass "Redis (port 6379) — ready"
else
    fail "Redis (port 6379) — not ready"
fi

# HTTP health checks for core infrastructure
declare -A INFRA_CHECKS
INFRA_CHECKS=(
    [openclaw-gateway]="http://localhost:18789/health"
    [tank-agent]="http://localhost:9000/health"
    [prometheus]="http://localhost:9090/-/healthy"
    [grafana]="http://localhost:3000/api/health"
    [unleash]="http://localhost:4242/health"
    [alertmanager]="http://localhost:9093/-/healthy"
    [n8n]="http://localhost:5678/healthz"
)

for svc in "${!INFRA_CHECKS[@]}"; do
    url="${INFRA_CHECKS[$svc]}"
    status=$(http_status "$url")
    if [[ "$status" == "200" ]]; then
        pass "$svc — healthy"
    else
        fail "$svc — health check failed (HTTP $status)"
    fi
done

# ── Section 3: Microservice Health Checks ─────────────────────────────────────
section "Microservice Health Checks (ports 8001-8024)"

declare -A SERVICES
SERVICES=(
    [api-proxy]=8001 [research]=8002 [decision]=8003 [executor]=8004
    [ledger]=8005 [tournament]=8006 [monitor]=8007 [memory-sync]=8008
    [banks-service]=8009 [meta-builder]=8010 [risk-manager]=8011 [portfolio-tracker]=8012
    [market-data]=8013 [signal-generator]=8014 [order-router]=8015 [position-manager]=8016
    [alert-service]=8017 [report-generator]=8018 [backtest-runner]=8019 [strategy-optimizer]=8020
    [feed-aggregator]=8021 [auth-service]=8022 [notification-service]=8023 [analytics-service]=8024
)

for svc in "${!SERVICES[@]}"; do
    port="${SERVICES[$svc]}"
    status=$(http_status "http://localhost:${port}/health")
    if [[ "$status" == "200" ]]; then
        pass "$svc (:$port) — healthy"
    else
        fail "$svc (:$port) — health check failed (HTTP $status)"
    fi
done

# ── Section 4: Redis Event Bus ─────────────────────────────────────────────────
section "Redis Event Bus"

if docker exec tank-redis redis-cli -a "${REDIS_PASSWORD:-changeme_redis}" \
    XADD stream:test-e2e '*' test_key test_value >/dev/null 2>&1; then
    pass "Redis XADD to stream works"
else
    fail "Redis XADD failed"
fi

COUNT=$(docker exec tank-redis redis-cli -a "${REDIS_PASSWORD:-changeme_redis}" \
    XLEN stream:test-e2e 2>/dev/null || echo "0")
if [[ "$COUNT" -ge "1" ]]; then
    pass "Redis stream contains $COUNT entries"
else
    fail "Redis stream empty after write"
fi

if docker exec tank-redis redis-cli -a "${REDIS_PASSWORD:-changeme_redis}" \
    SET test:key "hello" >/dev/null 2>&1; then
    pass "Redis SET works"
else
    fail "Redis SET failed"
fi

# Clean up test stream
docker exec tank-redis redis-cli -a "${REDIS_PASSWORD:-changeme_redis}" \
    DEL stream:test-e2e >/dev/null 2>&1 || true

# ── Section 5: API Endpoint Tests ─────────────────────────────────────────────
section "API Endpoint Tests"

# POST /orders — executor service
ORDER_RESP=$(http_post "http://localhost:8004/orders" \
    '{"symbol":"BTC-USD","side":"buy","quantity":0.1,"order_type":"market","price":null}')
ORDER_STATUS=$(http_status "http://localhost:8004/orders" 2>/dev/null || echo "000")
# Re-check with proper method
ORDER_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
    -H "Content-Type: application/json" \
    --connect-timeout 5 --max-time 10 \
    -d '{"symbol":"BTC-USD","side":"buy","quantity":0.1,"order_type":"market","price":null}' \
    "http://localhost:8004/orders" 2>/dev/null || echo "000")
if [[ "$ORDER_STATUS" == "200" ]] && echo "$ORDER_RESP" | jq -e '.order_id' >/dev/null 2>&1; then
    pass "POST /orders — order submitted (has order_id)"
elif [[ "$ORDER_STATUS" == "200" ]]; then
    fail "POST /orders — 200 but missing order_id in response"
else
    fail "POST /orders — HTTP $ORDER_STATUS"
fi

# GET /signals — research service
SIG_STATUS=$(http_status "http://localhost:8002/signals")
SIG_BODY=$(http_body "http://localhost:8002/signals")
if [[ "$SIG_STATUS" == "200" ]] && echo "$SIG_BODY" | jq -e '. | arrays' >/dev/null 2>&1; then
    pass "GET /signals — returned list"
elif [[ "$SIG_STATUS" == "200" ]]; then
    fail "GET /signals — 200 but response is not a list"
else
    fail "GET /signals — HTTP $SIG_STATUS"
fi

# POST /vote — decision service
VOTE_RESP=$(http_post "http://localhost:8003/vote" \
    '{"symbol":"BTC-USD","signal":"buy","confidence":0.8,"source":"test"}')
VOTE_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
    -H "Content-Type: application/json" \
    --connect-timeout 5 --max-time 10 \
    -d '{"symbol":"BTC-USD","signal":"buy","confidence":0.8,"source":"test"}' \
    "http://localhost:8003/vote" 2>/dev/null || echo "000")
if [[ "$VOTE_STATUS" == "200" ]]; then
    pass "POST /vote — decision vote accepted (HTTP $VOTE_STATUS)"
else
    fail "POST /vote — HTTP $VOTE_STATUS"
fi

# GET /exposure — risk-manager
RISK_STATUS=$(http_status "http://localhost:8011/exposure")
if [[ "$RISK_STATUS" == "200" ]]; then
    pass "GET /exposure — risk exposure data returned"
else
    fail "GET /exposure — HTTP $RISK_STATUS"
fi

# GET /portfolio — portfolio-tracker
PORT_STATUS=$(http_status "http://localhost:8012/portfolio")
if [[ "$PORT_STATUS" == "200" ]]; then
    pass "GET /portfolio — portfolio data returned"
else
    fail "GET /portfolio — HTTP $PORT_STATUS"
fi

# POST /alerts — alert-service
ALERT_RESP=$(http_post "http://localhost:8017/alerts" \
    '{"title":"Test","message":"E2E test alert","severity":"info","source":"test"}')
ALERT_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
    -H "Content-Type: application/json" \
    --connect-timeout 5 --max-time 10 \
    -d '{"title":"Test","message":"E2E test alert","severity":"info","source":"test"}' \
    "http://localhost:8017/alerts" 2>/dev/null || echo "000")
if [[ "$ALERT_STATUS" == "200" ]]; then
    pass "POST /alerts — alert created (HTTP $ALERT_STATUS)"
else
    fail "POST /alerts — HTTP $ALERT_STATUS"
fi

# GET /analytics/summary — analytics-service
ANALYTICS_STATUS=$(http_status "http://localhost:8024/analytics/summary")
if [[ "$ANALYTICS_STATUS" == "200" ]]; then
    pass "GET /analytics/summary — analytics data returned"
else
    fail "GET /analytics/summary — HTTP $ANALYTICS_STATUS"
fi

# ── Section 6: Slash New Protocol ─────────────────────────────────────────────
section "Slash New Protocol"

SLASH_RESP=$(http_post "http://localhost:18789/slash" \
    '{"session_id":"test-session-001","command":"/research/signals?symbol=BTC-USD"}')
if echo "$SLASH_RESP" | jq -e . >/dev/null 2>&1; then
    pass "Slash command returned valid JSON"
else
    fail "Slash command failed: $SLASH_RESP"
fi

# ── Section 7: Database Connectivity ──────────────────────────────────────────
section "Database Connectivity"

DBS="tank research decision executor tournament ledger banks memory portfolio unleash"
for db in $DBS; do
    if docker exec tank-postgres psql -U "${POSTGRES_USER:-tank}" -d "$db" \
        -c "SELECT 1" >/dev/null 2>&1; then
        pass "Database '$db' accessible"
    else
        fail "Database '$db' not accessible"
    fi
done

# ── Section 8: Prometheus Metrics ─────────────────────────────────────────────
section "Prometheus Metrics"

TARGETS=$(http_body "http://localhost:9090/api/v1/targets" | jq -r '.data.activeTargets | length' 2>/dev/null || echo "0")
if [[ "$TARGETS" -gt "0" ]]; then
    pass "Prometheus has $TARGETS active targets"
else
    fail "Prometheus has no active targets"
fi

for port in 8001 8002 8003 8004; do
    status=$(http_status "http://localhost:${port}/metrics")
    if [[ "$status" == "200" ]]; then
        pass "Service :$port exposes Prometheus metrics"
    else
        fail "Service :$port metrics endpoint failed (HTTP $status)"
    fi
done

# ── Section 9: Backup Script Validation ───────────────────────────────────────
section "Backup Script"

if [[ -f "backup-sync.sh" ]]; then
    pass "backup-sync.sh exists"
else
    fail "backup-sync.sh missing"
fi

if bash -n backup-sync.sh 2>/dev/null; then
    pass "backup-sync.sh syntax valid"
else
    fail "backup-sync.sh has syntax errors"
fi

# ── Section 10: Load Test ──────────────────────────────────────────────────────
section "Load Test"

if [[ "$QUICK" == "true" ]]; then
    skip "Load test (use without --quick to run)"
else
    start_time=$(date +%s%N)
    for i in $(seq 1 10); do
        curl -s "http://localhost:8001/health" >/dev/null 2>&1 &
    done
    wait
    end_time=$(date +%s%N)
    elapsed_ms=$(( (end_time - start_time) / 1000000 ))

    if [[ "$elapsed_ms" -lt 5000 ]]; then
        pass "10 concurrent requests completed in ${elapsed_ms}ms (<5000ms)"
    else
        fail "10 concurrent requests took ${elapsed_ms}ms (>5000ms threshold)"
    fi
fi

# ── Summary ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║              Test Summary                ║${NC}"
echo -e "${BOLD}╠══════════════════════════════════════════╣${NC}"
echo -e "${BOLD}║${NC}  ${GREEN}PASS: $PASS${NC}                               ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}  ${RED}FAIL: $FAIL${NC}                               ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}  ${YELLOW}SKIP: $SKIP${NC}                               ${BOLD}║${NC}"
TOTAL=$((PASS + FAIL + SKIP))
echo -e "${BOLD}║${NC}  Total: $TOTAL                              ${BOLD}║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════╝${NC}"
echo ""

if [[ "$FAIL" -gt 0 ]]; then
    echo -e "${RED}Some tests failed. Check logs: docker compose logs [service]${NC}"
    exit 1
else
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
fi
