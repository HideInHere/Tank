#!/bin/bash
# Creates all Tank databases on first postgres startup, then runs service init scripts
set -euo pipefail

DATABASES="research decision executor tournament ledger banks memory unleash n8n"

echo "[init-dbs] Creating databases..."
for db in $DATABASES; do
    echo "[init-dbs] Creating database: $db"
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
        SELECT 'CREATE DATABASE "$db"'
        WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$db')\gexec
        GRANT ALL PRIVILEGES ON DATABASE "$db" TO "$POSTGRES_USER";
EOSQL
done

echo "[init-dbs] All databases created."

# Run individual service init scripts if they exist
INIT_DIR="/docker-entrypoint-initdb.d/init-scripts"
if [ -d "$INIT_DIR" ]; then
    echo "[init-dbs] Running service schema init scripts..."
    for sql_file in "$INIT_DIR"/*.sql; do
        [ -f "$sql_file" ] || continue
        echo "[init-dbs] Running: $(basename $sql_file)"
        psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -f "$sql_file" || echo "[init-dbs] Warning: $sql_file had errors (may be expected)"
    done
fi

echo "[init-dbs] All schema initialization complete."
