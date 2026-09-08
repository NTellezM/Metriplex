#!/bin/bash
set -euo pipefail
# Credenciales privadas, fuera del repositorio y sin imprimirlas.
if [ -r /var/lib/metriplex-monitor/telegram.env ]; then
    set -a
    source /var/lib/metriplex-monitor/telegram.env
    set +a
fi
if [[ " ${*} " == *" --dry-run "* ]]; then
    exec /usr/bin/python3 /opt/Metriplex/scripts/metriplex_monitor.py "$@"
fi
exec /usr/bin/systemd-cat --identifier=metriplex-monitor /usr/bin/python3 /opt/Metriplex/scripts/metriplex_monitor.py "$@"
