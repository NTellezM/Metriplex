#!/bin/bash

# Configuración de rutas
BASE_DIR="/opt/Metriplex"
BACKUP_DIR="${BASE_DIR}/backups"
DB_FILE="${BASE_DIR}/node_data_8000.db"
TIMESTAMP=$(date +"%Y%m%d_%H%M")
BACKUP_FILE="${BACKUP_DIR}/node_data_8000_${TIMESTAMP}.db"
LOG_FILE="${BACKUP_DIR}/backup_cron.log"

# Asegurar que el directorio existe
mkdir -p "$BACKUP_DIR"

# 1. Respaldo seguro usando la API de SQLite (Evita corrupción por WAL/SHM)
sqlite3 "$DB_FILE" ".backup '${BACKUP_FILE}'"

# 2. Verificación de integridad del respaldo
if sqlite3 "$BACKUP_FILE" "PRAGMA integrity_check;" | grep -q "ok"; then
    echo "[$(date)] Backup exitoso y verificado: node_data_8000_${TIMESTAMP}.db" >> "$LOG_FILE"
else
    echo "[$(date)] ❌ ERROR: El backup falló la prueba de integridad." >> "$LOG_FILE"
    # Notificar al bot de Telegram sobre el fallo crítico
    curl -s -X POST "https://api.telegram.org/bot<TU_BOT_TOKEN>/sendMessage" \
        -d chat_id="1165791849" \
        -d text="⚠️ ALERTA VPS: Fallo de integridad en backup DB a las ${TIMESTAMP}." > /dev/null
    rm -f "$BACKUP_FILE"
    exit 1
fi

# 3. Retención de 24 horas: eliminar archivos más antiguos
# Lista por fecha (más nuevos primero), ignora los primeros 24, borra el resto
ls -t ${BACKUP_DIR}/node_data_8000_*.db | tail -n +25 | xargs -r rm --

# 4. (Opcional pero recomendado) Respaldar también el keystore activo
cp "${BASE_DIR}/keystore_node0.json" "${BACKUP_DIR}/keystore_node0_backup.json"

