# Comprehensive Containerized Trading System with OpenClaw Gateway

## Overview
Build a production-grade, fully containerized trading system integrating:
- OpenClaw Gateway (official docker setup from docs)
- 24 microservices (each with dedicated Postgres DB)
- Tank-agent as persistent OpenClaw agent
- n8n for workflow orchestration
- Memory persistence to GitHub (30-min intervals)
- Complete end-to-end testing (service comms, APIs, trading endpoints)

## Architecture

### Database Strategy (Lean)
- **Central:** tank_db (tank-agent state + decisions)
- **Per-service:** Each microservice has isolated Postgres instance
  - research_db (research-svc)
  - decision_db (decision-svc)
  - executor_db (executor-svc)
  - ledger_db (ledger-svc)
  - tournament_db (tournament-svc)
  - memory_db (memory-sync-svc)
  - banks_db (banks-service)
  - market_db (market-data-svc)
  - portfolio_db (portfolio-tracker)
  - (+ 14 more for remaining services)
- **Event bus:** Redis Streams (inter-service async comms)
- **Backup:** All DBs dumped to GitHub every 30 mins

### Service Communication (Slash New Protocol)
- **Hot path (<5ms):** gRPC for research→decision→executor
- **Async:** Redis Streams for event broadcasts
- **Slash new protocol:** Agent-to-agent messaging via OpenClaw sessions
- **REST:** Public APIs for external integrations

### Components

#### 1. OpenClaw Gateway (Official Docker)
- Use official openclaw docker image from GHCR
- Setup via `./scripts/docker/setup.sh`
- Bind to :18789 (LAN mode)
- Telegram channel configured
- Tank-agent spawned as persistent agent (not separate container)

#### 2. Microservices (24 total, each in docker)
| Service | Port | DB | Purpose |
|---------|------|----|---------| 
| api-proxy | 8001 | — | Market data + news + sentiment proxy |
| research-svc | 8002 | research_db | Quant research, signals, backtesting |
| decision-svc | 8003 | decision_db | Strategy voting, ensemble decisions |
| executor-svc | 8004 | executor_db | Order execution, Alpaca integration |
| ledger-svc | 8005 | ledger_db | Hash-chain audit log |
| tournament-svc | 8006 | tournament_db | Weekly strategy backtest |
| monitor-svc | 8007 | tank_db | System health monitoring |
| memory-sync-svc | 8008 | memory_db | State sync to PostgreSQL |
| banks-service | 8009 | banks_db | Code modifier + blue-green deploy |
| meta-builder | 8010 | tank_db | Service scaffolder |
| risk-manager | 8011 | tank_db | Portfolio risk checks |
| portfolio-tracker | 8012 | portfolio_db | Position tracking |
| market-data | 8013 | market_db | Live OHLCV feed aggregator |
| signal-generator | 8014 | decision_db | Alpha signals from research |
| order-router | 8015 | executor_db | Smart order routing |
| position-manager | 8016 | ledger_db | Position P&L tracking |
| alert-service | 8017 | tank_db | Alerts + notifications |
| report-generator | 8018 | ledger_db | Backtest + live reports |
| backtest-runner | 8019 | research_db | Strategy backtester |
| strategy-optimizer | 8020 | decision_db | ML strategy tuning |
| feed-aggregator | 8021 | market_db | Multi-exchange feeds |
| auth-service | 8022 | tank_db | API key management |
| notification-service | 8023 | tank_db | Telegram + email alerts |
| analytics-service | 8024 | ledger_db | Trade analytics |

#### 3. Infrastructure
- **Redis:** Event bus + caching (:6379)
- **n8n:** Workflow orchestration (:5678, remapped to :5672 in docker)
- **Prometheus:** Metrics collection (:9091)
- **Grafana:** Dashboards (:3003)
- **Alertmanager:** Alert routing (:9093)
- **Unleash:** Feature flags (:4242)

#### 4. Memory Persistence
- **Schedule:** Cron job every 30 mins
- **Action:** `bash scripts/backup-sync.sh`
  - Dump all 27 postgres databases (1 central + 26 per-service)
  - Git commit with timestamp
  - Git push to BACKUP_GITHUB_REPO
- **Storage:** GitHub private repo (one commit per 30 mins)
- **Recovery:** Clone repo, `docker compose up -d`, restore from latest dump

## Deliverables

### 1. Docker Compose (Complete Stack)
- OpenClaw gateway container (official image)
- 24 microservice containers
- 27 Postgres instances (1 central + 26 per-service)
- Redis, n8n, Prometheus, Grafana, Alertmanager, Unleash
- All proper networking, health checks, logging, restart policies

### 2. Service Dockerfiles (24 + gateway)
- Each microservice: minimal, optimized image
- Environment vars for DB connection, Redis, OpenClaw URL
- Health checks for each service
- Proper signal handling (SIGTERM)

### 3. Database Init Scripts
- Central: tank_db schema + tank-agent tables
- Per-service: minimal schema for each service
- All migrations idempotent

### 4. Setup & Deployment Scripts
- `setup.sh` — interactive setup (API keys, secrets, etc.)
- `install.sh` (macOS), `install-linux.sh`, `install.ps1` (Windows)
- `backup-sync.sh` — 30-min cron job for postgres dump + git push
- `.env.example` — all required vars with descriptions

### 5. Comprehensive Testing
Test each component:
- **Docker compose validation:** Syntax check, all services spin up
- **Service startup:** All 24 services + infrastructure healthy within 60s
- **Database connectivity:** Each service connects to its DB + central tank_db
- **Redis event bus:** Publish/subscribe test
- **API endpoints:** Health check each service's REST API
- **gRPC paths:** research→decision→executor latency <5ms
- **Slash new protocol:** Tank-agent receives/responds to messages
- **n8n workflows:** Test sample workflow execution
- **Telegram integration:** Send message to tank-agent, verify response
- **Trading endpoints:** Verify executor can call Alpaca (paper mode)
- **Backup script:** Run backup, verify git commit + push
- **Recovery test:** Kill postgres, restart, verify data restored
- **Service restart:** Kill a service, verify auto-restart
- **Load test:** 10 concurrent requests to API, latency check

### 6. Documentation
- Complete README with architecture diagrams
- One-liner installation commands (macOS/Linux/Windows)
- API documentation (OpenAPI/Swagger)
- Troubleshooting guide
- Monitoring guide (Grafana, Prometheus, Alertmanager)
- Recovery procedures

## Implementation Notes

### Slash New Protocol
- Tank-agent communicates with microservices via OpenClaw's `/` prefix
- Format: `/servicename/method/args`
- Example: `/research/get_signals`, `/executor/place_order`
- Routed through Redis Streams for async safety

### n8n Integration
- Webhook triggers for market events
- Workflow nodes for each microservice (REST calls)
- Error handling + retry logic
- Audit log of all workflow executions

### Memory Persistence
```bash
# Every 30 mins (crontab):
0,30 * * * * bash /path/to/backup-sync.sh
```
- Dumps: `pg_dump tank_db`, `pg_dump research_db`, ... (all 27)
- Commits: `git add backups/ && git commit -m "backup: $(date)"`
- Pushes: `git push origin backups`
- Retention: 30 days (configurable)

### Testing Strategy
- Unit tests: Per service (in their Dockerfile)
- Integration tests: All services communicate correctly
- End-to-end tests: Full trading flow (research→decision→execute)
- Load tests: 1000 req/s to APIs
- Chaos tests: Kill services, verify recovery
- Backup tests: Verify dump + restore cycle

## Acceptance Criteria
✅ Docker compose builds without errors
✅ All 26 services + infrastructure start healthily
✅ Tank-agent spawns as OpenClaw persistent agent
✅ Each service can read/write to its own DB
✅ gRPC hot path <5ms latency
✅ Redis Streams event bus working
✅ Slash new protocol messages routed correctly
✅ n8n workflows execute without errors
✅ Telegram: "hello" → tank responds
✅ API endpoints respond with correct data
✅ Executor can place orders on Alpaca (paper)
✅ Backup script runs every 30 mins, commits to github
✅ Recovery: Kill postgres, restart, data restored
✅ One-liner installation works on macOS/Linux/Windows
✅ Complete documentation with troubleshooting

## Timeline
- Build docker setup + services: 2 hours (ruflo with sonnet)
- Test all components: 1 hour (parallel test agents)
- Document + finalize: 30 mins
- Push to github: 10 mins

Total: ~3.5 hours for fully tested, production-ready system.
