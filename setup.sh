#!/usr/bin/env bash
# ============================================================
# Tank Trading System — Setup Script
# Usage: bash setup.sh [--paper] [--no-build]
# ============================================================
set -euo pipefail

TANK_DIR="${TANK_DIR:-$HOME/tank}"
TANK_REPO="${TANK_REPO_URL:-https://github.com/HideInHere/Tank}"
ENV_FILE="$TANK_DIR/.env"
LOG_FILE="/tmp/tank-setup.log"
PAPER=false
NO_BUILD=false

# ── Colors ─────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*" | tee -a "$LOG_FILE"; }
success() { echo -e "${GREEN}[OK]${NC}    $*" | tee -a "$LOG_FILE"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*" | tee -a "$LOG_FILE"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" | tee -a "$LOG_FILE"; exit 1; }

# ── Parse args ─────────────────────────────────────────────
for arg in "$@"; do
    case "$arg" in
        --paper)    PAPER=true ;;
        --no-build) NO_BUILD=true ;;
        --help|-h)
            echo "Usage: bash setup.sh [--paper] [--no-build]"
            echo "  --paper     Enable paper trading mode (no real orders)"
            echo "  --no-build  Skip docker image builds (use existing images)"
            exit 0 ;;
    esac
done

echo "" | tee -a "$LOG_FILE"
echo -e "${BOLD}╔══════════════════════════════════════════╗${NC}" | tee -a "$LOG_FILE"
echo -e "${BOLD}║   Tank Trading System — Setup v1.0       ║${NC}" | tee -a "$LOG_FILE"
echo -e "${BOLD}╚══════════════════════════════════════════╝${NC}" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# ── Prerequisite checks ────────────────────────────────────
check_prereqs() {
    info "Checking prerequisites..."
    local missing=()

    command -v docker >/dev/null 2>&1    || missing+=("docker")
    command -v git    >/dev/null 2>&1    || missing+=("git")

    if [[ ${#missing[@]} -gt 0 ]]; then
        error "Missing required tools: ${missing[*]}. Install them and re-run."
    fi

    # Docker daemon running?
    docker info >/dev/null 2>&1 || error "Docker daemon is not running. Start Docker and re-run."

    # docker compose v2?
    if ! docker compose version >/dev/null 2>&1; then
        error "docker compose v2 not found. Install Docker Desktop or 'docker-compose-plugin'."
    fi

    success "Prerequisites OK"
}

# ── Clone or update repo ───────────────────────────────────
clone_repo() {
    if [[ -d "$TANK_DIR/.git" ]]; then
        info "Repo exists at $TANK_DIR — pulling latest..."
        git -C "$TANK_DIR" pull --ff-only || warn "Could not pull latest (local changes?). Continuing with existing code."
    else
        info "Cloning $TANK_REPO → $TANK_DIR ..."
        if [[ -n "${GIT_TOKEN:-}" ]]; then
            local url="${TANK_REPO/https:\/\//https://${GIT_TOKEN}@}"
            git clone "$url" "$TANK_DIR" || error "Clone failed. Check GIT_TOKEN and repo access."
        else
            git clone "$TANK_REPO" "$TANK_DIR" || error "Clone failed. Set GIT_TOKEN env var for private repo."
        fi
    fi
    success "Repo ready at $TANK_DIR"
}

# ── Build .env ─────────────────────────────────────────────
setup_env() {
    if [[ -f "$ENV_FILE" ]]; then
        warn ".env already exists — skipping (delete it to regenerate)"
        return
    fi

    info "Generating .env from template..."
    cp "$TANK_DIR/.env.example" "$ENV_FILE"

    # Auto-fill from environment variables if set
    fill_env() {
        local key="$1" val="$2"
        if [[ -n "$val" ]]; then
            sed -i.bak "s|^${key}=.*|${key}=${val}|" "$ENV_FILE" && rm -f "${ENV_FILE}.bak"
        fi
    }

    fill_env "POSTGRES_PASSWORD"   "${POSTGRES_PASSWORD:-$(openssl rand -hex 16)}"
    fill_env "REDIS_PASSWORD"      "${REDIS_PASSWORD:-$(openssl rand -hex 16)}"
    fill_env "OPENCLAW_SECRET"     "${OPENCLAW_SECRET:-$(openssl rand -hex 32)}"
    fill_env "OPENCLAW_ADMIN_TOKEN" "${OPENCLAW_ADMIN_TOKEN:-$(openssl rand -hex 32)}"
    fill_env "GRAFANA_PASSWORD"    "${GRAFANA_PASSWORD:-$(openssl rand -hex 12)}"
    fill_env "UNLEASH_SECRET"      "${UNLEASH_SECRET:-$(openssl rand -hex 16)}"
    fill_env "GIT_TOKEN"           "${GIT_TOKEN:-}"
    fill_env "ANTHROPIC_API_KEY"   "${ANTHROPIC_API_KEY:-}"
    fill_env "BINANCE_API_KEY"     "${BINANCE_API_KEY:-}"
    fill_env "BINANCE_API_SECRET"  "${BINANCE_API_SECRET:-}"

    if [[ "$PAPER" == "true" ]]; then
        fill_env "PAPER_TRADING" "true"
        fill_env "TRADING_ENV"   "paper"
        warn "Paper trading mode ENABLED — no real orders will be placed"
    fi

    success ".env written to $ENV_FILE"
    warn "Review $ENV_FILE and add exchange API keys before trading"
}

# ── Docker volumes ─────────────────────────────────────────
create_volumes() {
    info "Ensuring Docker volumes exist..."
    local vols=(
        tank_postgres-data tank_redis-data tank_prometheus-data
        tank_grafana-data tank_alertmanager-data tank_unleash-data tank_backup-data
    )
    for v in "${vols[@]}"; do
        docker volume inspect "$v" >/dev/null 2>&1 \
            && info "  Volume $v already exists" \
            || { docker volume create "$v" >/dev/null; success "  Created volume $v"; }
    done
}

# ── Docker compose up ──────────────────────────────────────
compose_up() {
    info "Starting Tank trading system..."
    cd "$TANK_DIR"

    local build_flag=""
    [[ "$NO_BUILD" == "false" ]] && build_flag="--build"

    docker compose --env-file "$ENV_FILE" pull --ignore-pull-failures 2>/dev/null || true

    # Bring up infra first, then services
    docker compose --env-file "$ENV_FILE" up -d $build_flag \
        postgres redis \
        || error "Failed to start infrastructure containers"

    info "Waiting for postgres to be healthy..."
    wait_healthy "tank-postgres" 60

    docker compose --env-file "$ENV_FILE" up -d $build_flag \
        || error "Failed to start all services"

    success "All containers started"
}

# ── Health wait ────────────────────────────────────────────
wait_healthy() {
    local container="$1" timeout="${2:-120}" elapsed=0
    until [[ "$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null)" == "healthy" ]]; do
        if (( elapsed >= timeout )); then
            warn "Container $container did not become healthy within ${timeout}s"
            return 1
        fi
        sleep 3; ((elapsed+=3))
        echo -n "."
    done
    echo ""
    success "$container is healthy"
}

wait_all_healthy() {
    info "Waiting for all services to be healthy (up to 3 minutes)..."
    local critical=("tank-postgres" "tank-redis" "openclaw-gateway" "tank-grafana" "tank-prometheus")
    for c in "${critical[@]}"; do
        wait_healthy "$c" 180 || warn "  $c not healthy — check: docker logs $c"
    done
}

# ── Print dashboard URLs ───────────────────────────────────
print_urls() {
    # Read ports from .env if available
    local gf_port
    gf_port=$(grep -E '^GRAFANA_PORT=' "$ENV_FILE" 2>/dev/null | cut -d= -f2 || echo "3000")

    echo ""
    echo -e "${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}║               Tank Trading System — Ready!                   ║${NC}"
    echo -e "${BOLD}╠══════════════════════════════════════════════════════════════╣${NC}"
    echo -e "${BOLD}║${NC}  ${GREEN}Openclaw Gateway${NC}  →  http://localhost:18789                  ${BOLD}║${NC}"
    echo -e "${BOLD}║${NC}  ${GREEN}Grafana${NC}           →  http://localhost:${gf_port}                     ${BOLD}║${NC}"
    echo -e "${BOLD}║${NC}  ${GREEN}Prometheus${NC}        →  http://localhost:9090                   ${BOLD}║${NC}"
    echo -e "${BOLD}║${NC}  ${GREEN}Alertmanager${NC}      →  http://localhost:9093                   ${BOLD}║${NC}"
    echo -e "${BOLD}║${NC}  ${GREEN}Unleash Flags${NC}     →  http://localhost:4242                   ${BOLD}║${NC}"
    echo -e "${BOLD}╠══════════════════════════════════════════════════════════════╣${NC}"
    echo -e "${BOLD}║${NC}  Grafana login: admin / (see GRAFANA_PASSWORD in .env)         ${BOLD}║${NC}"
    echo -e "${BOLD}║${NC}  Logs: docker compose logs -f [service-name]                   ${BOLD}║${NC}"
    echo -e "${BOLD}║${NC}  Stop: docker compose down                                     ${BOLD}║${NC}"
    echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

# ── Install backup cron ────────────────────────────────────
install_cron() {
    if [[ -f "$TANK_DIR/backup-sync.sh" ]]; then
        local cron_entry="0,30 * * * * bash $TANK_DIR/backup-sync.sh >> /var/log/tank-backup.log 2>&1"
        ( crontab -l 2>/dev/null | grep -v "backup-sync.sh"; echo "$cron_entry" ) | crontab - \
            && success "Hourly backup cron installed" \
            || warn "Could not install cron. Run manually: crontab -e"
    fi
}

# ── Main ───────────────────────────────────────────────────
main() {
    mkdir -p "$(dirname "$LOG_FILE")"
    check_prereqs
    clone_repo
    setup_env
    create_volumes
    compose_up
    wait_all_healthy
    install_cron
    print_urls
}

main "$@"
