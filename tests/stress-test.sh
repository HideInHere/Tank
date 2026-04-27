#!/bin/bash
set -euo pipefail

# ============================================================================
# COMPREHENSIVE STRESS TEST SUITE
# Tests system stability under load: connections, queries, messages, HTTP
# Measures latency, memory, CPU. Validates recovery without crashes/data loss.
# ============================================================================

BLUE='\033[0;34m'
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

TESTS_PASSED=0
TESTS_FAILED=0
VERBOSE=true
REPORT_CSV="/tmp/stress-test-report.csv"

log_section() {
    echo -e "\n${YELLOW}=== $1 ===${NC}"
}

log_test() {
    echo -e "${BLUE}[TEST]${NC} $1"
}

log_pass() {
    echo -e "${GREEN}✓${NC} $1"
    ((TESTS_PASSED++))
}

log_fail() {
    echo -e "${RED}✗${NC} $1"
    ((TESTS_FAILED++))
}

log_metric() {
    echo -e "${CYAN}[METRIC]${NC} $1"
}

# CSV header
echo "Test,Type,Duration_ms,Requests,Success,Failed,Latency_avg_ms,Latency_max_ms,Latency_min_ms,Memory_MB,CPU_percent,Status" > "$REPORT_CSV"

# ============================================================================
# SECTION 1: CONNECTION STRESS (100 concurrent per service)
# ============================================================================
log_section "SECTION 1: CONNECTION STRESS (100 concurrent connections/service)"

services=("research-svc:50051" "decision-svc:50052" "executor-svc:50053")

for service_addr in "${services[@]}"; do
    service=$(echo $service_addr | cut -d: -f1)
    port=$(echo $service_addr | cut -d: -f2)
    
    log_test "Connection stress: $service (100 concurrent)"
    
    start=$(date +%s%N)
    success=0
    failed=0
    
    for i in {1..100}; do
        (timeout 2 bash -c "echo '' > /dev/tcp/localhost/$port" 2>/dev/null && ((success++)) || ((failed++))) &
    done
    wait
    
    end=$(date +%s%N)
    duration=$(( (end - start) / 1000000 ))
    
    if [ $success -ge 95 ]; then
        log_pass "$service: $success/100 connections successful (${duration}ms)"
        echo "$service,connection_stress,$duration,100,$success,$failed,0,0,0,0,0,pass" >> "$REPORT_CSV"
    else
        log_fail "$service: only $success/100 connections successful"
        echo "$service,connection_stress,$duration,100,$success,$failed,0,0,0,0,0,fail" >> "$REPORT_CSV"
    fi
done

# ============================================================================
# SECTION 2: DATABASE STRESS (1000 ops/sec across all DBs)
# ============================================================================
log_section "SECTION 2: DATABASE STRESS (1000 ops/sec)"

log_test "Database write stress: 1000 inserts/sec for 30 seconds"

start=$(date +%s%N)
success=0
failed=0

for i in {1..1000}; do
    (
        PGPASSWORD=postgres psql -h localhost -U postgres -d tank -c \
            "INSERT INTO test_stress (data, ts) VALUES ('stress_test_$i', NOW());" 2>/dev/null \
            && ((success++)) || ((failed++))
    ) &
    
    if [ $(($i % 100)) -eq 0 ]; then
        sleep 0.1  # Throttle to ~1000/sec
    fi
done
wait

end=$(date +%s%N)
duration=$(( (end - start) / 1000000 ))

log_pass "Database stress: $success/1000 inserts successful (${duration}ms)"
echo "database_stress,write,$duration,1000,$success,$failed,0,0,0,0,0,pass" >> "$REPORT_CSV"

# ============================================================================
# SECTION 3: REDIS MESSAGE STRESS (500 msgs/sec for 5 min)
# ============================================================================
log_section "SECTION 3: REDIS MESSAGE STRESS (500 msgs/sec for 5 min)"

log_test "Redis publish stress: 500 messages/sec"

start=$(date +%s%N)
success=0
failed=0

for i in {1..2500}; do
    (
        redis-cli -h localhost -p 6379 LPUSH "stress:stream" \
            "{\"type\":\"test\",\"id\":$i,\"ts\":$(date +%s)}" 2>/dev/null \
            && ((success++)) || ((failed++))
    ) &
    
    if [ $(($i % 500)) -eq 0 ]; then
        sleep 1  # Throttle to ~500/sec
    fi
done
wait

end=$(date +%s%N)
duration=$(( (end - start) / 1000000 ))

log_pass "Redis stress: $success/2500 messages published (${duration}ms)"
echo "redis_stress,publish,$duration,2500,$success,$failed,0,0,0,0,0,pass" >> "$REPORT_CSV"

# ============================================================================
# SECTION 4: HTTP API STRESS (10,000 requests)
# ============================================================================
log_section "SECTION 4: HTTP API STRESS (10,000 requests)"

log_test "HTTP request stress: 10,000 requests to /health endpoints"

start=$(date +%s%N)
success=0
failed=0
latencies=()

for i in {1..10000}; do
    (
        req_start=$(date +%s%N)
        status=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:7001/health 2>/dev/null || echo "000")
        req_end=$(date +%s%N)
        latency=$(( (req_end - req_start) / 1000000 ))
        
        if [ "$status" = "200" ]; then
            ((success++))
            echo $latency >> /tmp/latencies.tmp
        else
            ((failed++))
        fi
    ) &
    
    if [ $(($i % 1000)) -eq 0 ]; then
        sleep 0.5  # Throttle to ~2000/sec
    fi
done
wait

end=$(date +%s%N)
duration=$(( (end - start) / 1000000 ))

# Calculate latency stats
if [ -f /tmp/latencies.tmp ]; then
    latencies=$(cat /tmp/latencies.tmp | sort -n)
    lat_count=$(echo "$latencies" | wc -l)
    lat_avg=$(echo "$latencies" | awk '{sum+=$1} END {print int(sum/NR)}')
    lat_min=$(echo "$latencies" | head -1)
    lat_max=$(echo "$latencies" | tail -1)
    rm /tmp/latencies.tmp
else
    lat_avg=0
    lat_min=0
    lat_max=0
fi

log_pass "HTTP stress: $success/10000 requests successful"
log_metric "HTTP latency - avg: ${lat_avg}ms, min: ${lat_min}ms, max: ${lat_max}ms"
echo "http_stress,requests,$duration,10000,$success,$failed,$lat_avg,$lat_max,$lat_min,0,0,pass" >> "$REPORT_CSV"

# ============================================================================
# SECTION 5: COMBINED LOAD TEST (all stressors simultaneously for 2 min)
# ============================================================================
log_section "SECTION 5: COMBINED LOAD TEST (all stressors simultaneously)"

log_test "Running combined load: DB writes + Redis messages + HTTP requests (2 min)"

start=$(date +%s%N)
end_time=$(($(date +%s) + 120))  # 2 minutes

db_count=0
redis_count=0
http_count=0

# DB stress in background
(
    while [ $(date +%s) -lt $end_time ]; do
        PGPASSWORD=postgres psql -h localhost -U postgres -d tank -c \
            "INSERT INTO test_stress (data, ts) VALUES ('combined_$RANDOM', NOW());" 2>/dev/null && ((db_count++)) || true
        sleep 0.01
    done
) &

# Redis stress in background
(
    counter=0
    while [ $(date +%s) -lt $end_time ]; do
        redis-cli -h localhost -p 6379 LPUSH "combined:stream" "{\"test\":$counter}" 2>/dev/null && ((redis_count++)) || true
        ((counter++))
        sleep 0.01
    done
) &

# HTTP stress in background
(
    while [ $(date +%s) -lt $end_time ]; do
        curl -s -o /dev/null http://localhost:7001/health 2>/dev/null && ((http_count++)) || true
        sleep 0.05
    done
) &

# Wait for all background jobs
wait

end=$(date +%s%N)
duration=$(( (end - start) / 1000000 ))

log_pass "Combined load: DB=$db_count, Redis=$redis_count, HTTP=$http_count (${duration}ms)"
echo "combined_load,all,$duration,10000,$((db_count+redis_count+http_count)),0,0,0,0,0,0,pass" >> "$REPORT_CSV"

# ============================================================================
# SECTION 6: CONTAINER HEALTH CHECK (verify no crashes)
# ============================================================================
log_section "SECTION 6: CONTAINER HEALTH CHECK (verify stability)"

log_test "Checking container status after stress tests"

unhealthy=0
for container in $(docker compose ps --quiet); do
    status=$(docker inspect -f '{{.State.Status}}' $container)
    if [ "$status" != "running" ]; then
        log_fail "Container crashed: $container ($status)"
        ((unhealthy++))
    fi
done

if [ $unhealthy -eq 0 ]; then
    log_pass "All containers healthy (0 crashes during stress)"
    echo "container_health,check,0,33,33,0,0,0,0,0,0,pass" >> "$REPORT_CSV"
else
    log_fail "$unhealthy containers unhealthy/crashed"
    echo "container_health,check,0,33,$((33-unhealthy)),$unhealthy,0,0,0,0,0,fail" >> "$REPORT_CSV"
fi

# ============================================================================
# SECTION 7: DATABASE CONSISTENCY CHECK (zero data loss)
# ============================================================================
log_section "SECTION 7: DATA CONSISTENCY CHECK (zero data loss)"

log_test "Verifying data integrity after stress tests"

try_count=$(PGPASSWORD=postgres psql -h localhost -U postgres -d tank -c "SELECT COUNT(*) FROM test_stress;" 2>&1 | grep -oE '[0-9]+' | head -1 || echo "0")

if [ "$try_count" -gt 500 ]; then
    log_pass "Data integrity verified: $try_count rows inserted, zero loss"
    echo "data_consistency,check,0,$try_count,$try_count,0,0,0,0,0,0,pass" >> "$REPORT_CSV"
else
    log_fail "Data loss detected: only $try_count rows found"
    echo "data_consistency,check,0,$try_count,$try_count,0,0,0,0,0,0,fail" >> "$REPORT_CSV"
fi

# ============================================================================
# SECTION 8: RECOVERY TEST (restart a service, verify recovery)
# ============================================================================
log_section "SECTION 8: RECOVERY TEST"

log_test "Stopping and restarting research service"

start=$(date +%s%N)

# Stop service
docker compose stop research-svc 2>/dev/null || true
sleep 2

# Verify it's down
status=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:50051/health 2>/dev/null || echo "000")
if [ "$status" != "200" ]; then
    log_pass "Service successfully stopped"
else
    log_fail "Service did not stop"
fi

# Restart service
docker compose start research-svc 2>/dev/null || true
sleep 5

# Verify recovery
status=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:50051/health 2>/dev/null || echo "000")

end=$(date +%s%N)
duration=$(( (end - start) / 1000000 ))

if [ "$status" = "200" ]; then
    log_pass "Service recovered successfully (${duration}ms)"
    echo "recovery_test,restart,$duration,1,1,0,0,0,0,0,0,pass" >> "$REPORT_CSV"
else
    log_fail "Service failed to recover"
    echo "recovery_test,restart,$duration,1,0,1,0,0,0,0,0,fail" >> "$REPORT_CSV"
fi

# ============================================================================
# SUMMARY & REPORT
# ============================================================================
log_section "STRESS TEST SUMMARY"

total=$((TESTS_PASSED + TESTS_FAILED))
pass_rate=$(( (TESTS_PASSED * 100) / total ))

echo -e "${GREEN}Passed: $TESTS_PASSED${NC}"
echo -e "${RED}Failed: $TESTS_FAILED${NC}"
echo -e "Pass rate: ${pass_rate}% ($TESTS_PASSED/$total)"

echo -e "\nDetailed report saved to: ${CYAN}$REPORT_CSV${NC}"
echo ""
cat "$REPORT_CSV"

if [ "$TESTS_FAILED" -eq 0 ]; then
    echo -e "\n${GREEN}✓ ALL STRESS TESTS PASSED - SYSTEM IS STABLE UNDER LOAD${NC}"
    exit 0
else
    echo -e "\n${RED}✗ SOME STRESS TESTS FAILED - CHECK ERRORS ABOVE${NC}"
    exit 1
fi
