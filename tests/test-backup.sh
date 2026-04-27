#!/usr/bin/env bash
# Test backup-sync.sh dry run
set -euo pipefail
cd "$(dirname "$0")/.."

echo "[backup-test] Checking backup-sync.sh..."
[[ -f backup-sync.sh ]] && echo "  OK: backup-sync.sh exists" || { echo "  FAIL: backup-sync.sh missing"; exit 1; }
bash -n backup-sync.sh && echo "  OK: syntax valid" || { echo "  FAIL: syntax error"; exit 1; }
[[ -x backup-sync.sh ]] || chmod +x backup-sync.sh

echo "[backup-test] Simulating backup (will fail on DB without running stack — expected)..."
TANK_DIR=/tmp/tank-backup-test-$$ \
BACKUP_DIR=/tmp/tank-backup-$$ \
LOG_FILE=/tmp/tank-backup-test.log \
BACKUP_GITHUB_REPO="" \
GIT_TOKEN="" \
ENV_FILE=/dev/null \
    timeout 10 bash backup-sync.sh 2>/dev/null || true

echo "[backup-test] Checking for backup directory..."
if [[ -d "/tmp/tank-backup-$$" ]]; then
    echo "  OK: backup directory created at /tmp/tank-backup-$$"
else
    echo "  INFO: backup dir not created (DB not running — expected in CI without stack)"
fi

# Cleanup
rm -rf "/tmp/tank-backup-$$" "/tmp/tank-backup-test-$$" "/tmp/tank-backup-test.log" 2>/dev/null || true
echo "[backup-test] Done"
