#!/bin/bash
# Metriplex Bootstrap — descarga snapshot para sync rápido
# Uso: bash bootstrap.sh [DB_TARGET_PATH]
# Ejemplo: bash bootstrap.sh node_data_8002.db

SNAPSHOT_URL="https://metriplexmpx.xyz/snapshot/metriplex_snapshot.db.gz"
SHA256_URL="https://metriplexmpx.xyz/snapshot/metriplex_snapshot.sha256"
META_URL="https://metriplexmpx.xyz/snapshot/metriplex_snapshot.json"
DB_TARGET="${1:-node_data_8000.db}"
TMP_GZ="/tmp/metriplex_snapshot.db.gz"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  METRIPLEX BOOTSTRAP"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 1. Mostrar metadata del snapshot
echo "[Bootstrap] Consultando snapshot disponible..."
META=$(curl -sf --max-time 10 "$META_URL")
if [ -z "$META" ]; then
    echo "[Bootstrap] ❌ No se pudo obtener metadata del snapshot — abortando"
    exit 1
fi
CHAIN_LEN=$(echo "$META" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['chain_length'])")
SNAP_SIZE=$(echo "$META" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['snapshot_size_bytes'])")
EXPORTED=$(echo "$META" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['exported_at'])")
echo "[Bootstrap] Snapshot disponible:"
echo "  Bloques:   ${CHAIN_LEN}"
echo "  Tamaño:    $(python3 -c "print(f'{${SNAP_SIZE}/1024/1024:.1f} MB')")"
echo "  Exportado: ${EXPORTED}"

# 2. Confirmar si ya existe DB
if [ -f "$DB_TARGET" ]; then
    LOCAL_BLOCKS=$(sqlite3 "$DB_TARGET" "SELECT count(*) FROM blocks;" 2>/dev/null || echo 0)
    echo "[Bootstrap] DB local encontrada: ${LOCAL_BLOCKS} bloques"
    echo "[Bootstrap] ¿Reemplazar con snapshot? (s/N)"
    read -r CONFIRM
    if [ "$CONFIRM" != "s" ] && [ "$CONFIRM" != "S" ]; then
        echo "[Bootstrap] Abortado por usuario."
        exit 0
    fi
fi

# 3. Descargar snapshot
echo "[Bootstrap] Descargando snapshot..."
curl -f --progress-bar "$SNAPSHOT_URL" -o "$TMP_GZ"
if [ $? -ne 0 ]; then
    echo "[Bootstrap] ❌ Error en descarga"
    exit 1
fi

# 4. Verificar SHA256
echo "[Bootstrap] Verificando integridad..."
EXPECTED_SHA=$(curl -sf --max-time 5 "$SHA256_URL")
ACTUAL_SHA=$(sha256sum "$TMP_GZ" | awk '{print $1}')
if [ "$EXPECTED_SHA" != "$ACTUAL_SHA" ]; then
    echo "[Bootstrap] ❌ SHA256 no coincide — snapshot corrupto"
    echo "  Esperado: $EXPECTED_SHA"
    echo "  Obtenido: $ACTUAL_SHA"
    rm -f "$TMP_GZ"
    exit 1
fi
echo "[Bootstrap] ✓ Integridad verificada"

# 5. Descomprimir a destino
echo "[Bootstrap] Instalando DB en ${DB_TARGET}..."
gunzip -c "$TMP_GZ" > "$DB_TARGET"
rm -f "$TMP_GZ"

# 6. Verificar integridad de la DB
if ! sqlite3 "$DB_TARGET" "PRAGMA integrity_check;" | grep -q "ok"; then
    echo "[Bootstrap] ❌ DB falló verificación de integridad"
    exit 1
fi

FINAL_BLOCKS=$(sqlite3 "$DB_TARGET" "SELECT count(*) FROM blocks;")
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "[Bootstrap] ✓ Completado — ${FINAL_BLOCKS} bloques instalados"
echo "[Bootstrap] El nodo sincronizará los bloques nuevos al arrancar."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
