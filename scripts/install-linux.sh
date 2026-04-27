#!/usr/bin/env bash
# ============================================================
# Tank Trading System — Linux One-Liner Installer
# curl -sSL https://raw.githubusercontent.com/HideInHere/Tank/main/scripts/install-linux.sh | bash
# Supports: Ubuntu 20.04+, Debian 11+, RHEL/CentOS 8+, Fedora 38+, Arch
# ============================================================
set -euo pipefail

TANK_DIR="${TANK_DIR:-$HOME/tank}"
TANK_REPO="https://github.com/HideInHere/Tank"
LOG="/tmp/tank-install.log"
DOCKER_GPG="/etc/apt/keyrings/docker.gpg"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'; BOLD='\033[1m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*" | tee -a "$LOG"; }
success() { echo -e "${GREEN}[ OK ]${NC}  $*" | tee -a "$LOG"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*" | tee -a "$LOG"; }
error()   { echo -e "${RED}[ERR ]${NC}  $*" | tee -a "$LOG"; exit 1; }

SUDO=""
[[ $EUID -ne 0 ]] && SUDO="sudo"

banner() {
    echo -e "${BOLD}"
    echo "╔══════════════════════════════════════════════════════╗"
    echo "║   Tank Trading System — Linux Installer              ║"
    echo "╚══════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

# ── Detect distro ──────────────────────────────────────────
detect_distro() {
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        DISTRO="${ID:-unknown}"
        DISTRO_LIKE="${ID_LIKE:-}"
        VERSION_ID="${VERSION_ID:-0}"
    else
        DISTRO="unknown"
    fi
    info "Detected: ${PRETTY_NAME:-$DISTRO}"
}

# ── Install Docker (distro-aware) ──────────────────────────
install_docker() {
    if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
        success "Docker already running"
        return
    fi

    info "Installing Docker Engine..."

    case "$DISTRO" in
        ubuntu|debian|raspbian)
            install_docker_apt ;;
        rhel|centos|rocky|almalinux|ol)
            install_docker_rpm ;;
        fedora)
            install_docker_fedora ;;
        arch|manjaro)
            install_docker_arch ;;
        *)
            if [[ "$DISTRO_LIKE" == *"debian"* ]] || [[ "$DISTRO_LIKE" == *"ubuntu"* ]]; then
                install_docker_apt
            elif [[ "$DISTRO_LIKE" == *"rhel"* ]] || [[ "$DISTRO_LIKE" == *"fedora"* ]]; then
                install_docker_rpm
            else
                warn "Unknown distro $DISTRO — attempting generic install via get.docker.com"
                curl -fsSL https://get.docker.com | $SUDO sh
            fi ;;
    esac

    # Add user to docker group
    if id -nG "$USER" 2>/dev/null | grep -qw docker; then
        info "User already in docker group"
    else
        $SUDO usermod -aG docker "$USER" 2>>"$LOG" || warn "Could not add $USER to docker group"
        warn "You may need to log out and back in for group change to take effect"
    fi

    $SUDO systemctl enable --now docker 2>>"$LOG" || warn "systemctl not available — starting docker manually"
    docker info >/dev/null 2>&1 || $SUDO docker info >/dev/null 2>&1 || error "Docker failed to start"
    success "Docker installed and running"
}

install_docker_apt() {
    $SUDO apt-get update -qq
    $SUDO apt-get install -y -qq ca-certificates curl gnupg lsb-release git

    $SUDO install -m 0755 -d /etc/apt/keyrings
    curl -fsSL "https://download.docker.com/linux/${DISTRO}/gpg" | \
        $SUDO gpg --dearmor --yes -o "$DOCKER_GPG"
    $SUDO chmod a+r "$DOCKER_GPG"

    echo "deb [arch=$(dpkg --print-architecture) signed-by=${DOCKER_GPG}] \
https://download.docker.com/linux/${DISTRO} $(lsb_release -cs) stable" | \
        $SUDO tee /etc/apt/sources.list.d/docker.list > /dev/null

    $SUDO apt-get update -qq
    $SUDO apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
}

install_docker_rpm() {
    $SUDO yum install -y yum-utils git
    $SUDO yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
    $SUDO yum install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
}

install_docker_fedora() {
    $SUDO dnf -y install dnf-plugins-core git
    $SUDO dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo
    $SUDO dnf -y install docker-ce docker-ce-cli containerd.io docker-compose-plugin
}

install_docker_arch() {
    $SUDO pacman -Sy --noconfirm docker docker-compose git
}

# ── Install git (if missing) ───────────────────────────────
install_git() {
    command -v git >/dev/null 2>&1 && { info "git already installed"; return; }
    case "$DISTRO" in
        ubuntu|debian) $SUDO apt-get install -y -qq git ;;
        rhel|centos|rocky|almalinux|fedora|ol) $SUDO yum install -y git ;;
        arch|manjaro) $SUDO pacman -S --noconfirm git ;;
        *) warn "Cannot auto-install git on $DISTRO — install manually" ;;
    esac
    success "git installed"
}

# ── Clone repo ─────────────────────────────────────────────
clone_repo() {
    if [[ -d "$TANK_DIR/.git" ]]; then
        info "Repo exists — pulling latest..."
        git -C "$TANK_DIR" pull --ff-only 2>>"$LOG" || warn "Could not pull"
    else
        info "Cloning $TANK_REPO → $TANK_DIR"
        if [[ -n "${GIT_TOKEN:-}" ]]; then
            local url="${TANK_REPO/https:\/\//https://${GIT_TOKEN}@}"
            git clone "$url" "$TANK_DIR" 2>>"$LOG" || error "Clone failed — check GIT_TOKEN"
        else
            git clone "$TANK_REPO" "$TANK_DIR" 2>>"$LOG" \
                || error "Clone failed. Set GIT_TOKEN env var for private repo."
        fi
    fi
    success "Repo ready at $TANK_DIR"
}

# ── Fill .env ──────────────────────────────────────────────
setup_env() {
    local env_file="$TANK_DIR/.env"
    [[ -f "$env_file" ]] && { warn ".env already exists — keeping"; return; }

    cp "$TANK_DIR/.env.example" "$env_file"

    auto_fill() {
        local k="$1" v="${2:-}"
        [[ -n "$v" ]] && sed -i "s|^${k}=.*|${k}=${v}|" "$env_file"
    }

    auto_fill POSTGRES_PASSWORD  "${POSTGRES_PASSWORD:-$(openssl rand -hex 16)}"
    auto_fill REDIS_PASSWORD     "${REDIS_PASSWORD:-$(openssl rand -hex 16)}"
    auto_fill OPENCLAW_SECRET    "${OPENCLAW_SECRET:-$(openssl rand -hex 32)}"
    auto_fill GRAFANA_PASSWORD   "${GRAFANA_PASSWORD:-$(openssl rand -hex 12)}"
    auto_fill UNLEASH_SECRET     "${UNLEASH_SECRET:-$(openssl rand -hex 16)}"
    auto_fill GIT_TOKEN          "${GIT_TOKEN:-}"
    auto_fill ANTHROPIC_API_KEY  "${ANTHROPIC_API_KEY:-}"
    auto_fill BINANCE_API_KEY    "${BINANCE_API_KEY:-}"
    auto_fill BINANCE_API_SECRET "${BINANCE_API_SECRET:-}"

    success ".env created"
}

# ── Compose up ─────────────────────────────────────────────
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
    info "Waiting for openclaw gateway..."
    local i=0
    until curl -sf http://localhost:18789/health >/dev/null 2>&1; do
        (( i++ )); (( i > 60 )) && { warn "Gateway not responding"; break; }
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
    echo ""
}

main() {
    banner
    detect_distro
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
