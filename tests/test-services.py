#!/usr/bin/env python3
"""
Tank Trading System — Python Integration Tests
Usage: python tests/test-services.py
Requirements: Python 3.7+ stdlib only (no third-party packages needed)
"""
import sys
import json
import time
import urllib.request
import urllib.error

BASE = "http://localhost"
TIMEOUT = 10

SERVICES = {
    "api-proxy": 8001,
    "research": 8002,
    "decision": 8003,
    "executor": 8004,
    "ledger": 8005,
    "tournament": 8006,
    "monitor": 8007,
    "memory-sync": 8008,
    "banks-service": 8009,
    "meta-builder": 8010,
    "risk-manager": 8011,
    "portfolio-tracker": 8012,
    "market-data": 8013,
    "signal-generator": 8014,
    "order-router": 8015,
    "position-manager": 8016,
    "alert-service": 8017,
    "report-generator": 8018,
    "backtest-runner": 8019,
    "strategy-optimizer": 8020,
    "feed-aggregator": 8021,
    "auth-service": 8022,
    "notification-service": 8023,
    "analytics-service": 8024,
}

pass_count = 0
fail_count = 0


def check(name, condition, detail=""):
    global pass_count, fail_count
    if condition:
        print(f"  \033[32m✓\033[0m {name}")
        pass_count += 1
    else:
        print(f"  \033[31m✗\033[0m {name}{' — ' + detail if detail else ''}")
        fail_count += 1


def get(url):
    """GET request; returns (status_code, parsed_body). Returns (0, {}) on error."""
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
            raw = r.read()
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                body = {"_raw": raw.decode("utf-8", errors="replace")}
            return r.status, body
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
        except Exception:
            body = {}
        return e.code, body
    except Exception:
        return 0, {}


def post(url, data):
    """POST JSON; returns (status_code, parsed_body). Returns (0, {}) on error."""
    try:
        body_bytes = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body_bytes,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read()
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                body = {"_raw": raw.decode("utf-8", errors="replace")}
            return r.status, body
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
        except Exception:
            body = {}
        return e.code, body
    except Exception:
        return 0, {}


print("\n\033[1mTank Trading — Python Integration Tests\033[0m\n")

# ── Test 1: Health checks ──────────────────────────────────────────────────────
print("\033[1m\033[34m═══ Service Health Checks ═══\033[0m")
for svc, port in sorted(SERVICES.items(), key=lambda x: x[1]):
    status, body = get(f"{BASE}:{port}/health")
    check(
        f"{svc} (:{ port}) healthy",
        status == 200 and body.get("status") == "ok",
        f"HTTP {status}, body={json.dumps(body)[:80]}",
    )

# ── Test 2: Key trading flows ──────────────────────────────────────────────────
print("\n\033[1m\033[34m═══ Trading Flows ═══\033[0m")

# Submit market order
status, body = post(
    f"{BASE}:8004/orders",
    {"symbol": "ETH-USD", "side": "buy", "quantity": 1.0, "order_type": "market", "price": None},
)
check("Submit market order", status == 200 and "order_id" in body, str(body)[:120])

# Get research signals
status, body = get(f"{BASE}:8002/signals")
check("Get research signals", status == 200 and isinstance(body, list), str(body)[:120])

# Cast decision vote
status, body = post(
    f"{BASE}:8003/vote",
    {"symbol": "ETH-USD", "signal": "buy", "confidence": 0.75, "source": "test"},
)
check("Cast decision vote", status == 200 and body.get("accepted") is True, str(body)[:120])

# Risk check — small trade should be approved
status, body = post(
    f"{BASE}:8011/check",
    {"symbol": "BTC-USD", "side": "buy", "quantity": 0.1, "price": 50000},
)
check("Risk check (small trade approved)", status == 200 and "approved" in body, str(body)[:120])

# Add ledger entry
status, body = post(
    f"{BASE}:8005/entries",
    {"event_type": "test_trade", "data": {"symbol": "ETH-USD"}, "source": "test"},
)
check("Ledger entry created", status == 200 and "hash" in body, str(body)[:120])

# Tournament registration
status, body = post(
    f"{BASE}:8006/register",
    {"agent_id": "test-agent-001", "strategy": "momentum", "capital": 10000},
)
check("Tournament registration", status == 200, str(body)[:120])

# Signal generation
status, body = post(
    f"{BASE}:8014/generate",
    {"symbol": "BTC-USD", "timeframe": "1h"},
)
check("Signal generation request", status == 200 and "signal" in body, str(body)[:120])

# Order routing
status, body = post(
    f"{BASE}:8015/route",
    {"order_id": "test-ord-001", "symbol": "BTC-USD", "exchange": "auto"},
)
check("Order routing", status == 200, str(body)[:120])

# ── Test 3: Analytics & Market Data ───────────────────────────────────────────
print("\n\033[1m\033[34m═══ Analytics & Market Data ═══\033[0m")

status, body = get(f"{BASE}:8024/analytics/summary")
check("Analytics summary endpoint", status == 200 and "total_trades" in body, str(body)[:120])

status, body = get(f"{BASE}:8012/portfolio")
check("Portfolio summary", status == 200 and "total_value" in body, str(body)[:120])

status, body = get(f"{BASE}:8013/ticker/BTC-USD")
check("Market data ticker (BTC-USD)", status == 200 and "price" in body, str(body)[:120])

status, body = get(f"{BASE}:8013/orderbook/BTC-USD")
check("Market data order book", status == 200, str(body)[:120])

status, body = get(f"{BASE}:8018/reports/daily")
check("Daily report generation", status == 200, str(body)[:120])

status, body = get(f"{BASE}:8011/exposure")
check("Risk exposure summary", status == 200, str(body)[:120])

status, body = get(f"{BASE}:8016/positions")
check("Open positions list", status == 200, str(body)[:120])

# ── Test 4: Auth Flow ──────────────────────────────────────────────────────────
print("\n\033[1m\033[34m═══ Auth Flow ═══\033[0m")

status, body = post(
    f"{BASE}:8022/keys",
    {"name": "test-key", "permissions": ["read"]},
)
check("Create API key", status == 200 and "key_id" in body, str(body)[:120])

if "key_value" in body:
    key_val = body["key_value"]
    status2, body2 = post(f"{BASE}:8022/verify", {"api_key": key_val})
    check("Verify API key", status2 == 200 and body2.get("valid") is True, str(body2)[:120])
else:
    check("Verify API key", False, "no key_value in create response")

# Token-based login
status, body = post(
    f"{BASE}:8022/login",
    {"username": "test-user", "password": "test-password"},
)
check("Login endpoint responds", status in (200, 401, 403), str(body)[:120])

# ── Test 5: Notifications & Alerts ────────────────────────────────────────────
print("\n\033[1m\033[34m═══ Notifications & Alerts ═══\033[0m")

status, body = post(
    f"{BASE}:8017/alerts",
    {"title": "E2E Test Alert", "message": "Integration test", "severity": "info", "source": "test"},
)
check("Create alert", status == 200, str(body)[:120])

status, body = get(f"{BASE}:8017/alerts")
check("List alerts", status == 200 and isinstance(body, (list, dict)), str(body)[:120])

status, body = post(
    f"{BASE}:8023/send",
    {"channel": "email", "recipient": "test@example.com", "subject": "Test", "body": "E2E test notification"},
)
check("Send notification", status == 200, str(body)[:120])

# ── Test 6: Backtest & Strategy ────────────────────────────────────────────────
print("\n\033[1m\033[34m═══ Backtest & Strategy ═══\033[0m")

status, body = post(
    f"{BASE}:8019/run",
    {
        "strategy": "momentum",
        "symbol": "BTC-USD",
        "from": "2024-01-01",
        "to": "2024-03-31",
        "initial_capital": 10000,
    },
)
check("Backtest run submitted", status == 200 and ("job_id" in body or "result" in body), str(body)[:120])

status, body = post(
    f"{BASE}:8020/optimize",
    {"strategy": "momentum", "symbol": "BTC-USD", "metric": "sharpe_ratio"},
)
check("Strategy optimization request", status == 200, str(body)[:120])

# ── Test 7: Feed Aggregator & Memory ──────────────────────────────────────────
print("\n\033[1m\033[34m═══ Feed Aggregator & Memory ═══\033[0m")

status, body = get(f"{BASE}:8021/feeds")
check("List active feeds", status == 200, str(body)[:120])

status, body = post(
    f"{BASE}:8008/sync",
    {"namespace": "test", "key": "e2e-test", "value": {"timestamp": int(time.time())}},
)
check("Memory sync write", status == 200, str(body)[:120])

status, body = get(f"{BASE}:8008/keys/test:e2e-test")
check("Memory sync read-back", status == 200, str(body)[:120])

# ── Test 8: Metrics Endpoints ──────────────────────────────────────────────────
print("\n\033[1m\033[34m═══ Metrics Endpoints ═══\033[0m")

for svc, port in [("api-proxy", 8001), ("research", 8002), ("executor", 8004), ("risk-manager", 8011)]:
    status, body = get(f"{BASE}:{port}/metrics")
    check(f"{svc} /metrics endpoint", status == 200, f"HTTP {status}")

# ── Summary ────────────────────────────────────────────────────────────────────
total = pass_count + fail_count
print(
    f"\n\033[1mResults: \033[32m{pass_count} passed\033[0m, "
    f"\033[31m{fail_count} failed\033[0m, {total} total\033[0m\n"
)
sys.exit(0 if fail_count == 0 else 1)
