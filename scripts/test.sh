#!/usr/bin/env bash
# Tank Trading System — Comprehensive Test Suite
# Usage: bash scripts/test.sh [--url http://localhost] [--skip-load]
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost}"
SKIP_LOAD=false
PASS=0; FAIL=0

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
ok()      { echo -e "${GREEN}[PASS]${NC} $*"; ((PASS++)); }
fail()    { echo -e "${RED}[FAIL]${NC} $*"; ((FAIL++)); }
info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
section() { echo ""; echo -e "${YELLOW}=== $* ===${NC}"; }

for arg in "$@"; do case "$arg" in --skip-load) SKIP_LOAD=true ;; esac; done

# ── 1. Docker compose config syntax check ──
section "Docker Compose Validation"
if docker compose -f docker-compose.yml config --quiet 2>/dev/null; then
  ok "docker-compose.yml syntax valid"
else
  fail "docker-compose.yml syntax invalid"
fi

# ── 2. All containers running ──
section "Container Status"
SERVICES="tank-postgres tank-redis openclaw-gateway tank-agent tank-n8n tank-prometheus tank-grafana"
SVCS_8001_8024="tank-api-proxy tank-research tank-decision tank-executor tank-ledger tank-tournament tank-monitor tank-memory-sync tank-banks-service tank-meta-builder tank-risk-manager tank-portfolio-tracker tank-market-data tank-signal-generator tank-order-router tank-position-manager tank-alert-service tank-report-generator tank-backtest-runner tank-strategy-optimizer tank-feed-aggregator tank-auth-service tank-notification-service tank-analytics-service"
for svc in $SERVICES $SVCS_8001_8024; do
  status=$(docker inspect --format='{{.State.Status}}' "$svc" 2>/dev/null || echo "missing")
  if [[ "$status" == "running" ]]; then ok "Container $svc running"
  else fail "Container $svc: $status"; fi
done

# ── 3. Health check all services ──
section "Service Health Endpoints"
declare -A ENDPOINTS=(
  ["openclaw-gateway"]="${BASE_URL}:18789/health"
  ["tank-agent"]="${BASE_URL}:9000/health"
  ["api-proxy"]="${BASE_URL}:8001/health"
  ["research"]="${BASE_URL}:8002/health"
  ["decision"]="${BASE_URL}:8003/health"
  ["executor"]="${BASE_URL}:8004/health"
  ["ledger"]="${BASE_URL}:8005/health"
  ["tournament"]="${BASE_URL}:8006/health"
  ["monitor"]="${BASE_URL}:8007/health"
  ["memory-sync"]="${BASE_URL}:8008/health"
  ["banks-service"]="${BASE_URL}:8009/health"
  ["meta-builder"]="${BASE_URL}:8010/health"
  ["risk-manager"]="${BASE_URL}:8011/health"
  ["portfolio-tracker"]="${BASE_URL}:8012/health"
  ["market-data"]="${BASE_URL}:8013/health"
  ["signal-generator"]="${BASE_URL}:8014/health"
  ["order-router"]="${BASE_URL}:8015/health"
  ["position-manager"]="${BASE_URL}:8016/health"
  ["alert-service"]="${BASE_URL}:8017/health"
  ["report-generator"]="${BASE_URL}:8018/health"
  ["backtest-runner"]="${BASE_URL}:8019/health"
  ["strategy-optimizer"]="${BASE_URL}:8020/health"
  ["feed-aggregator"]="${BASE_URL}:8021/health"
  ["auth-service"]="${BASE_URL}:8022/health"
  ["notification-service"]="${BASE_URL}:8023/health"
  ["analytics-service"]="${BASE_URL}:8024/health"
  ["prometheus"]="${BASE_URL}:9090/-/healthy"
  ["grafana"]="${BASE_URL}:3000/api/health"
  ["n8n"]="${BASE_URL}:5678/healthz"
)
for svc in "${!ENDPOINTS[@]}"; do
  url="${ENDPOINTS[$svc]}"
  if curl -sf --max-time 5 "$url" >/dev/null 2>&1; then ok "$svc health OK ($url)"
  else fail "$svc health FAILED ($url)"; fi
done

# ── 4. Database connectivity ──
section "Database Connectivity"
DBS="tank research decision executor tournament ledger banks memory unleash n8n"
for db in $DBS; do
  if docker exec tank-postgres psql -U tank -d "$db" -c "SELECT 1" >/dev/null 2>&1; then
    ok "DB $db accessible"
  else
    fail "DB $db not accessible"
  fi
done

# ── 5. Redis connectivity ──
section "Redis Event Bus"
REDIS_PASS=$(docker exec tank-redis env | grep REDIS_PASSWORD | cut -d= -f2 2>/dev/null || echo "")
if docker exec tank-redis redis-cli ${REDIS_PASS:+-a "$REDIS_PASS"} ping 2>/dev/null | grep -q PONG; then
  ok "Redis ping OK"
else
  fail "Redis ping failed"
fi
# Pub/sub test
if docker exec tank-redis redis-cli ${REDIS_PASS:+-a "$REDIS_PASS"} publish tank:test "hello" >/dev/null 2>&1; then
  ok "Redis publish to tank:test OK"
else
  fail "Redis publish failed"
fi

# ── 6. Service API tests ──
section "Service API Tests"
# Research: create and read signal
SIGNAL=$(curl -sf -X POST "${BASE_URL}:8002/signals" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","direction":"long","confidence":0.8,"strategy":"sma_crossover"}' 2>/dev/null || echo "")
if echo "$SIGNAL" | grep -q "symbol"; then ok "research: POST /signals OK"
else fail "research: POST /signals failed"; fi

# Decision: post vote
VOTE=$(curl -sf -X POST "${BASE_URL}:8003/vote" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","action":"buy","confidence":0.75,"strategy":"sma"}' 2>/dev/null || echo "")
if echo "$VOTE" | grep -q "ok"; then ok "decision: POST /vote OK"
else fail "decision: POST /vote failed"; fi

# Risk manager: check trade
RISK=$(curl -sf -X POST "${BASE_URL}:8011/check" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","side":"buy","qty":0.1,"price":50000}' 2>/dev/null || echo "")
if echo "$RISK" | grep -q "approved"; then ok "risk-manager: POST /check OK"
else fail "risk-manager: POST /check failed"; fi

# Executor: place paper order
ORDER=$(curl -sf -X POST "${BASE_URL}:8004/execute" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","side":"buy","qty":0.01,"order_type":"market"}' 2>/dev/null || echo "")
if echo "$ORDER" | grep -qi "order\|id\|status"; then ok "executor: POST /execute (paper) OK"
else fail "executor: POST /execute failed"; fi

# Auth service: create key
AUTH=$(curl -sf -X POST "${BASE_URL}:8022/keys" \
  -H "Content-Type: application/json" \
  -d '{"name":"test-key","permissions":["read"]}' 2>/dev/null || echo "")
if echo "$AUTH" | grep -q "key"; then ok "auth-service: POST /keys OK"
else fail "auth-service: POST /keys failed"; fi

# Memory sync: store and retrieve
SYNC=$(curl -sf -X POST "${BASE_URL}:8008/sync" \
  -H "Content-Type: application/json" \
  -d '{"key":"test","value":{"ts":"now"},"namespace":"test"}' 2>/dev/null || echo "")
if echo "$SYNC" | grep -q "ok"; then ok "memory-sync: POST /sync OK"
else fail "memory-sync: POST /sync failed"; fi

# ── 7. OpenClaw Gateway tests ──
section "OpenClaw Gateway"
AGENTS=$(curl -sf "${BASE_URL}:18789/agents" 2>/dev/null || echo "")
if echo "$AGENTS" | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0 if isinstance(d,list) else 1)" 2>/dev/null; then
  ok "openclaw: GET /agents returns array"
else
  fail "openclaw: GET /agents failed"
fi
SESSIONS=$(curl -sf "${BASE_URL}:18789/sessions" 2>/dev/null || echo "")
if echo "$SESSIONS" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
  ok "openclaw: GET /sessions OK"
else
  fail "openclaw: GET /sessions failed"
fi

# ── 8. Tank agent message test ──
section "Tank Agent AI"
MSG=$(curl -sf -X POST "${BASE_URL}:9000/message" \
  -H "Content-Type: application/json" \
  -d '{"content":"hello tank, what is your status?","from_id":"test","session_id":"test-session-1"}' \
  --max-time 30 2>/dev/null || echo "")
if echo "$MSG" | grep -qi "response\|tank\|status"; then ok "tank-agent: message processed OK"
else fail "tank-agent: message failed (check ANTHROPIC_API_KEY)"; fi

# ── 9. Backup script dry run ──
section "Backup Script"
if [[ -f backup-sync.sh ]]; then
  if bash -n backup-sync.sh 2>/dev/null; then ok "backup-sync.sh syntax OK"
  else fail "backup-sync.sh syntax error"; fi
  # Verify 30-min cron comment
  if grep -q "0,30" backup-sync.sh; then ok "backup-sync.sh has 30-min cron schedule"
  else fail "backup-sync.sh missing 30-min cron schedule"; fi
else
  fail "backup-sync.sh not found"
fi

# ── 10. Prometheus metrics ──
section "Prometheus Metrics"
TARGETS=$(curl -sf "${BASE_URL}:9090/api/v1/targets" 2>/dev/null || echo "")
if echo "$TARGETS" | grep -q "activeTargets"; then ok "Prometheus targets API responding"
else fail "Prometheus targets API failed"; fi

# ── 11. Grafana health ──
section "Grafana"
GF=$(curl -sf "${BASE_URL}:3000/api/health" 2>/dev/null || echo "")
if echo "$GF" | grep -q "ok\|database"; then ok "Grafana health OK"
else fail "Grafana health failed"; fi

# ── 12. n8n health ──
section "n8n Workflow Engine"
N8N=$(curl -sf "${BASE_URL}:5678/healthz" 2>/dev/null || echo "")
if echo "$N8N" | grep -qi "ok\|status"; then ok "n8n health OK"
else fail "n8n health failed"; fi

# ── 13. Load test (10 concurrent requests) ──
section "Load Test (api-proxy)"
if [[ "$SKIP_LOAD" == "false" ]]; then
  info "Running 10 concurrent requests to api-proxy..."
  START=$(date +%s%N)
  for i in $(seq 1 10); do
    curl -sf "${BASE_URL}:8001/proxy/price?symbol=BTC" >/dev/null 2>&1 &
  done
  wait
  END=$(date +%s%N)
  ELAPSED=$(( (END - START) / 1000000 ))
  if [[ $ELAPSED -lt 10000 ]]; then ok "Load test: 10 concurrent requests in ${ELAPSED}ms"
  else fail "Load test: took ${ELAPSED}ms (>10s)"; fi
else
  info "Load test skipped (--skip-load)"
fi

# ── 14. Container restart recovery ──
section "Service Restart Recovery"
if docker inspect tank-monitor >/dev/null 2>&1; then
  docker restart tank-monitor >/dev/null 2>&1
  sleep 5
  STATUS=$(docker inspect --format='{{.State.Status}}' tank-monitor 2>/dev/null)
  if [[ "$STATUS" == "running" ]]; then ok "monitor-svc: restarted and running"
  else fail "monitor-svc: restart failed (status: $STATUS)"; fi
fi

# ── Summary ──
echo ""
echo "═══════════════════════════════════════════════════════"
TOTAL=$((PASS + FAIL))
echo -e "${GREEN}PASSED: $PASS/$TOTAL${NC}  ${RED}FAILED: $FAIL/$TOTAL${NC}"
echo "═══════════════════════════════════════════════════════"
[[ $FAIL -eq 0 ]]
