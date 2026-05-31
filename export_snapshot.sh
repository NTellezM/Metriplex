#!/bin/bash
# Metriplex Snapshot Exporter
# Exporta la DB del nodo genesis para bootstrap rápido de nuevos nodos

BASE_DIR="/opt/Metriplex"
DB_FILE="${BASE_DIR}/node_data_8000.db"
SNAPSHOT_DIR="/var/www/metriplexmpx.xyz/snapshot"
SNAPSHOT_DB="${SNAPSHOT_DIR}/metriplex_snapshot.db"
SNAPSHOT_GZ="${SNAPSHOT_DIR}/metriplex_snapshot.db.gz"
SNAPSHOT_SHA="${SNAPSHOT_DIR}/metriplex_snapshot.sha256"
SNAPSHOT_META="${SNAPSHOT_DIR}/metriplex_snapshot.json"
LOG_FILE="${BASE_DIR}/backups/snapshot_export.log"

mkdir -p "$SNAPSHOT_DIR"

# 1. Backup seguro via SQLite API (evita corrupción WAL)
sqlite3 "$DB_FILE" ".backup '${SNAPSHOT_DB}'"

# Verificar integridad
if ! sqlite3 "$SNAPSHOT_DB" "PRAGMA integrity_check;" | grep -q "ok"; then
    echo "[$(date)] ❌ Snapshot falló integridad — abortando" >> "$LOG_FILE"
    rm -f "$SNAPSHOT_DB"
    exit 1
fi

# 2. Comprimir
gzip -f "$SNAPSHOT_DB"

# 3. SHA256
sha256sum "$SNAPSHOT_GZ" | awk '{print $1}' > "$SNAPSHOT_SHA"

# 4. Metadata — altura y hash del último bloque
CHAIN_LENGTH=$(sqlite3 "$DB_FILE" "SELECT count(*) FROM blocks;")
LAST_BLOCK=$(sqlite3 "$DB_FILE" "SELECT block_index, hash FROM blocks ORDER BY block_index DESC LIMIT 1;")
LAST_IDX=$(echo "$LAST_BLOCK" | cut -d'|' -f1)
LAST_HASH=$(echo "$LAST_BLOCK" | cut -d'|' -f2)
SNAPSHOT_SIZE=$(stat -c%s "$SNAPSHOT_GZ")

cat > "$SNAPSHOT_META" << METAJSON
{
    "chain_length": ${CHAIN_LENGTH},
    "last_block_index": ${LAST_IDX},
    "last_block_hash": "${LAST_HASH}",
    "snapshot_size_bytes": ${SNAPSHOT_SIZE},
    "exported_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
    "node": "node-0",
    "download_url": "https://metriplexmpx.xyz/snapshot/metriplex_snapshot.db.gz",
    "sha256_url": "https://metriplexmpx.xyz/snapshot/metriplex_snapshot.sha256"
}
METAJSON

echo "[$(date)] ✓ Snapshot exportado — bloque ${LAST_IDX} | ${SNAPSHOT_SIZE} bytes" >> "$LOG_FILE"
