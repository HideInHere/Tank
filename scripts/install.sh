#!/usr/bin/env bash
# ============================================================
# Tank Trading System — macOS One-Liner Installer
# curl -sSL https://raw.githubusercontent.com/HideInHere/Tank/main/scripts/install.sh | bash
# ============================================================
set -euo pipefail

TANK_DIR="${TANK_DIR:-$HOME/tank}"
TANK_REPO="https://github.com/HideInHere/Tank"
MIN_DOCKER_VERSION="24.0"
LOG="/tmp/tank-install.log"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'; BOLD='\033[1m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*" | tee -a "$LOG"; }
success() { echo -e "${GREEN}[ OK ]${NC}  $*" | tee -a "$LOG"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*" | tee -a "$LOG"; }
error()   { echo -e "${RED}[ERR ]${NC}  $*" | tee -a "$LOG"; exit 1; }

banner() {
    echo -e "${BOLD}"
    echo "╔══════════════════════════════════════════════════════╗"
    echo "║   Tank Trading System — macOS Installer              ║"
    echo "╚══════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

# ── OS check ───────────────────────────────────────────────
check_os() {
    [[ "$(uname -s)" == "Darwin" ]] || error "This installer is for macOS. Use install-linux.sh on Linux."
    info "macOS $(sw_vers -productVersion) detected"
}

# ── Install Homebrew ───────────────────────────────────────
install_homebrew() {
    if command -v brew >/dev/null 2>&1; then
        info "Homebrew already installed"
        return
    fi
    info "Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
        || error "Homebrew installation failed"
    # Add to PATH for Apple Silicon
    if [[ -f /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
    success "Homebrew installed"
}

# ── Install Docker Desktop ─────────────────────────────────
install_docker() {
    if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
        success "Docker already running"
        return
    fi

    if command -v docker >/dev/null 2>&1; then
        info "Docker installed but daemon not running — starting..."
        open -a Docker 2>/dev/null || true
        wait_docker
        return
    fi

    info "Installing Docker Desktop via Homebrew..."
    brew install --cask docker || error "Docker Desktop install failed"

    info "Starting Docker Desktop..."
    open -a Docker
    wait_docker
}

wait_docker() {
    info "Waiting for Docker daemon (up to 90s)..."
    local i=0
    until docker info >/dev/null 2>&1; do
        (( i++ ))
        (( i > 30 )) && error "Docker daemon did not start. Launch Docker Desktop manually then re-run."
        sleep 3; echo -n "."
    done
    echo ""
    success "Docker daemon ready"
}

# ── Install git ────────────────────────────────────────────
install_git() {
    command -v git >/dev/null 2>&1 && { info "git already installed"; return; }
    info "Installing git via Homebrew..."
    brew install git || error "git install failed"
    success "git installed"
}

# ── Clone repo ─────────────────────────────────────────────
clone_repo() {
    if [[ -d "$TANK_DIR/.git" ]]; then
        info "Repo exists — pulling latest..."
        git -C "$TANK_DIR" pull --ff-only 2>>"$LOG" || warn "Could not pull (local changes?)"
    else
        info "Cloning $TANK_REPO → $TANK_DIR"
        if [[ -n "${GIT_TOKEN:-}" ]]; then
            local url="${TANK_REPO/https:\/\//https://${GIT_TOKEN}@}"
            git clone "$url" "$TANK_DIR" 2>>"$LOG" || error "Clone failed — check GIT_TOKEN"
        else
            git clone "$TANK_REPO" "$TANK_DIR" 2>>"$LOG" \
                || error "Clone failed. Set GIT_TOKEN env var for private repo access."
        fi
    fi
    success "Repo ready at $TANK_DIR"
}

# ── Fill .env ──────────────────────────────────────────────
setup_env() {
    local env_file="$TANK_DIR/.env"
    if [[ -f "$env_file" ]]; then
        warn ".env already exists — keeping current values"
        return
    fi

    cp "$TANK_DIR/.env.example" "$env_file"

    auto_fill() {
        local k="$1" v="${2:-}"
        [[ -n "$v" ]] && sed -i '' "s|^${k}=.*|${k}=${v}|" "$env_file"
    }

    auto_fill POSTGRES_PASSWORD "${POSTGRES_PASSWORD:-$(openssl rand -hex 16)}"
    auto_fill REDIS_PASSWORD    "${REDIS_PASSWORD:-$(openssl rand -hex 16)}"
    auto_fill OPENCLAW_SECRET   "${OPENCLAW_SECRET:-$(openssl rand -hex 32)}"
    auto_fill GRAFANA_PASSWORD  "${GRAFANA_PASSWORD:-$(openssl rand -hex 12)}"
    auto_fill UNLEASH_SECRET    "${UNLEASH_SECRET:-$(openssl rand -hex 16)}"
    auto_fill GIT_TOKEN         "${GIT_TOKEN:-}"
    auto_fill ANTHROPIC_API_KEY "${ANTHROPIC_API_KEY:-}"
    auto_fill BINANCE_API_KEY   "${BINANCE_API_KEY:-}"
    auto_fill BINANCE_API_SECRET "${BINANCE_API_SECRET:-}"

    success ".env created at $env_file"
    warn "Edit $env_file to add exchange API keys before live trading"
}

# ── Docker compose up ──────────────────────────────────────
compose_up() {
    info "Starting all containers..."
    cd "$TANK_DIR"
    docker compose --env-file .env pull --ignore-pull-failures 2>>"$LOG" || true
    docker compose --env-file .env up -d --build 2>>"$LOG" \
        || error "docker compose up failed — check: docker compose logs"
    success "Containers started"
}

# ── Wait for gateway ───────────────────────────────────────
wait_ready() {
    info "Waiting for openclaw gateway (up to 3 minutes)..."
    local i=0
    until curl -sf http://localhost:18789/health >/dev/null 2>&1; do
        (( i++ ))
        (( i > 60 )) && { warn "Gateway not responding — check: docker compose logs openclaw-gateway"; break; }
        sleep 3; echo -n "."
    done
    echo ""
}

# ── Install cron ───────────────────────────────────────────
install_cron() {
    local entry="0 * * * * bash $TANK_DIR/backup-sync.sh >> /tmp/tank-backup.log 2>&1"
    ( crontab -l 2>/dev/null | grep -v "backup-sync.sh"; echo "$entry" ) | crontab - \
        && success "Hourly backup cron installed" \
        || warn "Cron install skipped"
}

# ── Print result ───────────────────────────────────────────
print_done() {
    echo ""
    echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${GREEN}║         Tank Trading System — Ready!             ║${NC}"
    echo -e "${BOLD}${GREEN}╠══════════════════════════════════════════════════╣${NC}"
    echo -e "${BOLD}${GREEN}║${NC}  Ready at ${BOLD}http://localhost:18789${NC}                 ${BOLD}${GREEN}║${NC}"
    echo -e "${BOLD}${GREEN}║${NC}  Grafana  → http://localhost:3000              ${BOLD}${GREEN}║${NC}"
    echo -e "${BOLD}${GREEN}║${NC}  Unleash  → http://localhost:4242              ${BOLD}${GREEN}║${NC}"
    echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════════╝${NC}"
    echo ""
    echo "  Manage: cd $TANK_DIR && docker compose [up|down|logs|ps]"
    echo "  Logs:   $LOG"
    echo ""
}

# ── Main ───────────────────────────────────────────────────
main() {
    banner
    check_os
    install_homebrew
    install_git
    install_docker
    clone_repo
    setup_env
    compose_up
    wait_ready
    install_cron
    print_done
}

main "$@"
