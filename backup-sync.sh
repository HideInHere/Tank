#!/usr/bin/env bash
# ============================================================
# Tank Trading System — Hourly Postgres Backup + Git Push
# Install: crontab -e → 0,30 * * * * bash /path/to/backup-sync.sh
# ============================================================
set -euo pipefail

TANK_DIR="${TANK_DIR:-$HOME/tank}"
ENV_FILE="${TANK_DIR}/.env"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/tank}"
LOG_FILE="${BACKUP_LOG:-/var/log/tank-backup.log}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DATE_LABEL=$(date +%Y-%m-%d)
BACKUP_RUN_DIR="${BACKUP_DIR}/${TIMESTAMP}"

# ── Helpers ────────────────────────────────────────────────
log()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }
die()  { log "ERROR: $*"; exit 1; }

# ── Load .env ──────────────────────────────────────────────
load_env() {
    [[ -f "$ENV_FILE" ]] || die ".env not found at $ENV_FILE"
    # Export non-comment, non-empty lines
    set -a
    # shellcheck disable=SC1090
    source <(grep -E '^[A-Z_]+=.+' "$ENV_FILE" | sed 's/#.*//')
    set +a
}

# ── Lock (prevent overlapping runs) ───────────────────────
LOCKFILE="/tmp/tank-backup.lock"
cleanup() { rm -f "$LOCKFILE"; }
trap cleanup EXIT

if [[ -e "$LOCKFILE" ]]; then
    lock_pid=$(cat "$LOCKFILE" 2>/dev/null || echo "unknown")
    if kill -0 "$lock_pid" 2>/dev/null; then
        log "Another backup (PID $lock_pid) is running — skipping this run"
        exit 0
    fi
    log "Stale lock found — removing"
    rm -f "$LOCKFILE"
fi
echo $$ > "$LOCKFILE"

# ── Main ───────────────────────────────────────────────────
main() {
    log "=== Tank backup starting (run: $TIMESTAMP) ==="

    load_env

    # Defaults if not in .env
    POSTGRES_USER="${POSTGRES_USER:-tank}"
    POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-}"
    POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
    POSTGRES_PORT="${POSTGRES_PORT:-5432}"
    GIT_TOKEN="${GIT_TOKEN:-}"
    BACKUP_GITHUB_REPO="${BACKUP_GITHUB_REPO:-}"
    BACKUP_BRANCH="${BACKUP_BRANCH:-backups}"

    mkdir -p "$BACKUP_RUN_DIR"

    # ── Dump each database ─────────────────────────────────
    DATABASES="tank research decision executor tournament ledger banks memory unleash n8n"
    DUMP_OK=0
    DUMP_FAIL=0

    for db in $DATABASES; do
        local_dump="${BACKUP_RUN_DIR}/${db}.sql.gz"
        log "Dumping database: $db → $local_dump"

        if PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
            -h "$POSTGRES_HOST" \
            -p "$POSTGRES_PORT" \
            -U "$POSTGRES_USER" \
            -d "$db" \
            --no-password \
            --format=plain \
            --clean \
            --if-exists \
            2>>"$LOG_FILE" | gzip > "$local_dump"; then
            log "  ✓ $db ($(du -sh "$local_dump" | cut -f1))"
            ((DUMP_OK++))
        else
            log "  ✗ $db — dump failed (check pg_dump logs above)"
            ((DUMP_FAIL++))
        fi
    done

    log "Dumps complete: ${DUMP_OK} OK, ${DUMP_FAIL} failed"

    # ── Create manifest ────────────────────────────────────
    cat > "${BACKUP_RUN_DIR}/manifest.json" <<EOF
{
  "timestamp": "${TIMESTAMP}",
  "date": "${DATE_LABEL}",
  "databases": $(echo "$DATABASES" | tr ' ' '\n' | jq -R . | jq -s .),
  "dumps_ok": ${DUMP_OK},
  "dumps_failed": ${DUMP_FAIL},
  "host": "$(hostname -f 2>/dev/null || hostname)"
}
EOF

    # ── Push to GitHub ─────────────────────────────────────
    if [[ -n "$BACKUP_GITHUB_REPO" && -n "$GIT_TOKEN" ]]; then
        push_to_github
    else
        log "GitHub push skipped (BACKUP_GITHUB_REPO or GIT_TOKEN not set)"
    fi

    # ── Prune old local backups ────────────────────────────
    log "Pruning backups older than ${RETENTION_DAYS} days..."
    find "$BACKUP_DIR" -maxdepth 1 -mindepth 1 -type d \
        -mtime "+${RETENTION_DAYS}" -exec rm -rf {} \; \
        2>>"$LOG_FILE" && log "Prune complete"

    log "=== Backup run complete ==="
}

push_to_github() {
    local repo_dir="/tmp/tank-backup-repo"
    local repo_url="${BACKUP_GITHUB_REPO/https:\/\//https://${GIT_TOKEN}@}"

    log "Pushing to GitHub: $BACKUP_GITHUB_REPO (branch: $BACKUP_BRANCH)"

    # Clone or reset backup repo
    if [[ -d "$repo_dir/.git" ]]; then
        git -C "$repo_dir" fetch origin "$BACKUP_BRANCH" 2>>"$LOG_FILE" || true
        git -C "$repo_dir" checkout "$BACKUP_BRANCH" 2>>"$LOG_FILE" || \
            git -C "$repo_dir" checkout -b "$BACKUP_BRANCH" 2>>"$LOG_FILE"
        git -C "$repo_dir" reset --hard "origin/$BACKUP_BRANCH" 2>>"$LOG_FILE" || true
    else
        rm -rf "$repo_dir"
        git clone --branch "$BACKUP_BRANCH" --single-branch \
            "$repo_url" "$repo_dir" 2>>"$LOG_FILE" \
            || git clone "$repo_url" "$repo_dir" 2>>"$LOG_FILE" \
            && git -C "$repo_dir" checkout -b "$BACKUP_BRANCH" 2>>"$LOG_FILE" || true
    fi

    # Copy this run's dumps
    local dest="${repo_dir}/${DATE_LABEL}/${TIMESTAMP}"
    mkdir -p "$dest"
    cp -r "${BACKUP_RUN_DIR}/." "$dest/"

    # Update latest symlink
    ln -sfn "${DATE_LABEL}/${TIMESTAMP}" "${repo_dir}/latest"

    # Git commit & push
    git -C "$repo_dir" config user.email "${GIT_EMAIL:-tank-backup@localhost}"
    git -C "$repo_dir" config user.name  "Tank Backup Bot"
    git -C "$repo_dir" add -A
    git -C "$repo_dir" commit -m "backup: ${TIMESTAMP} — ${DUMP_OK}/${#DATABASES[@]} dbs" \
        2>>"$LOG_FILE" || { log "Nothing to commit"; return; }
    git -C "$repo_dir" push origin "$BACKUP_BRANCH" 2>>"$LOG_FILE" \
        && log "Backup pushed to GitHub" \
        || log "WARNING: Git push failed — local backup still exists at $BACKUP_RUN_DIR"
}

main "$@"
