# Tank Trading System

Fully containerized trading platform: openclaw gateway + 24 microservices + 8 Postgres databases + Redis + Prometheus/Grafana + Unleash feature flags.

---

## One-liner install

### macOS

```bash
curl -sSL https://raw.githubusercontent.com/HideInHere/Tank/main/scripts/install.sh | bash
```

### Linux (Ubuntu / Debian / RHEL / Fedora / Arch)

```bash
curl -sSL https://raw.githubusercontent.com/HideInHere/Tank/main/scripts/install-linux.sh | bash
```

### Windows (PowerShell — run as Administrator)

```powershell
iex (New-Object Net.WebClient).DownloadString('https://raw.githubusercontent.com/HideInHere/Tank/main/scripts/install.ps1')
```

Each one-liner:
- Detects OS and installs Docker if needed
- Clones this (private) repo — set `GIT_TOKEN` env var first
- Auto-generates secrets in `.env`
- Runs `docker compose up -d --build`
- Waits for health checks
- Prints **Ready at http://localhost:18789**

---

## Prerequisites (one-liners handle these automatically)

| Tool | Version |
|------|---------|
| Docker Engine | 24.0+ |
| docker compose | v2 plugin |
| git | any |

For the private repo, set `GIT_TOKEN` before running:
```bash
export GIT_TOKEN=ghp_yourPersonalAccessToken
```

---

## Architecture

```
                        ┌─────────────────────────────────┐
                        │       Openclaw Gateway :18789    │
                        │     (+ tank-agent persistent)    │
                        └──────────────┬──────────────────┘
                                       │
              ┌────────────────────────┼────────────────────────┐
              │                        │                        │
     ┌────────┴────────┐    ┌──────────┴──────────┐   ┌────────┴────────┐
     │  Trading Svcs   │    │   Infrastructure     │   │  Observability  │
     │  (24 services)  │    │  Postgres (8 DBs)    │   │  Prometheus     │
     │  :8001–:8024    │    │  Redis event bus     │   │  Grafana        │
     └─────────────────┘    │  Unleash flags       │   │  Alertmanager   │
                            └──────────────────────┘   └─────────────────┘
```

### Services

| Service | Port | Database |
|---------|------|----------|
| openclaw-gateway | 18789 | tank |
| tank-agent | 9000 (internal) | — |
| api-proxy | 8001 | — |
| research | 8002 | research |
| decision | 8003 | decision |
| executor | 8004 | executor |
| ledger | 8005 | ledger |
| tournament | 8006 | tournament |
| monitor | 8007 | tank |
| memory-sync | 8008 | memory |
| banks-service | 8009 | banks |
| meta-builder | 8010 | tank |
| risk-manager | 8011 | tank |
| portfolio-tracker | 8012 | ledger |
| market-data | 8013 | research |
| signal-generator | 8014 | decision |
| order-router | 8015 | executor |
| position-manager | 8016 | ledger |
| alert-service | 8017 | tank |
| report-generator | 8018 | ledger |
| backtest-runner | 8019 | research |
| strategy-optimizer | 8020 | decision |
| feed-aggregator | 8021 | research |
| auth-service | 8022 | tank |
| notification-service | 8023 | tank |
| analytics-service | 8024 | ledger |

---

## Dashboard URLs

| Service | URL |
|---------|-----|
| Openclaw Gateway | http://localhost:18789 |
| Grafana | http://localhost:3000 |
| Prometheus | http://localhost:9090 |
| Alertmanager | http://localhost:9093 |
| Unleash Feature Flags | http://localhost:4242 |

Grafana login: `admin` / `GRAFANA_PASSWORD` from `.env`

---

## Manual setup (if you prefer step-by-step)

```bash
# 1. Clone
export GIT_TOKEN=ghp_yourtoken
git clone https://${GIT_TOKEN}@github.com/HideInHere/Tank ~/tank
cd ~/tank

# 2. Configure
cp .env.example .env
# Edit .env — add exchange API keys, ANTHROPIC_API_KEY, etc.

# 3. Start
docker compose up -d --build

# 4. Check health
docker compose ps
```

---

## Configuration (`.env`)

Key variables:

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Required for tank-agent AI capabilities |
| `POSTGRES_PASSWORD` | Auto-generated on first run |
| `TRADING_ENV` | `production` / `paper` / `backtest` |
| `PAPER_TRADING` | `true` to disable real order execution |
| `BINANCE_API_KEY` | Exchange credentials |
| `GIT_TOKEN` | GitHub PAT for private repo + backup push |

Full reference: [`.env.example`](.env.example)

---

## Backups

Automated hourly backup of all 8 Postgres databases:

```bash
# Installed automatically by setup scripts as cron job:
# 0 * * * * bash ~/tank/backup-sync.sh >> /tmp/tank-backup.log 2>&1

# Run manually:
bash ~/tank/backup-sync.sh

# View backup log:
tail -f /tmp/tank-backup.log
```

Backups are pushed to `BACKUP_GITHUB_REPO` (set in `.env`).
Retention: `BACKUP_RETENTION_DAYS` (default 30 days).

---

## Common operations

```bash
# View all service status
docker compose ps

# Follow logs for a service
docker compose logs -f executor

# Follow all logs
docker compose logs -f

# Restart a service
docker compose restart decision

# Stop everything
docker compose down

# Stop and remove volumes (DESTRUCTIVE — deletes all data)
docker compose down -v

# Rebuild a single service after code change
docker compose up -d --build research

# Open postgres shell
docker exec -it tank-postgres psql -U tank -d tank

# Open redis shell
docker exec -it tank-redis redis-cli -a "$REDIS_PASSWORD"
```

---

## Upgrading

```bash
cd ~/tank
git pull
docker compose pull
docker compose up -d --build
```

---

## Troubleshooting

### Gateway not starting

```bash
docker compose logs openclaw-gateway
# Check: postgres and redis must be healthy first
docker compose ps postgres redis
```

### Postgres not healthy

```bash
docker compose logs postgres
# If init-dbs failed, recreate:
docker compose down postgres
docker volume rm tank_postgres-data
docker compose up -d postgres
```

### Port already in use

```bash
# Find what's using port 18789:
lsof -i :18789          # macOS/Linux
netstat -ano | findstr 18789  # Windows

# Change ports in .env:
OPENCLAW_PORT=19789
GRAFANA_PORT=3001
```

### Docker daemon not running (macOS)

```bash
open -a Docker
# Wait ~30s then retry
```

### Permission denied (Linux)

```bash
sudo usermod -aG docker $USER
newgrp docker
# Then re-run setup
```

### Paper trading mode

```bash
# Enable before first run:
echo "PAPER_TRADING=true" >> .env
echo "TRADING_ENV=paper" >> .env
docker compose up -d --build executor order-router
```

---

## Security notes

- All service ports except 18789 (gateway) and 3000 (Grafana) bind to `127.0.0.1` only
- Postgres and Redis are not exposed externally
- Rotate secrets in `.env` and `docker compose restart` after any credential change
- Never commit `.env` to version control

---

## License

See [LICENSE](LICENSE) in this repository.
