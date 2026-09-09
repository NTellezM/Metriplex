#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Metriplex — whitelist-node.sh
#  Autoriza a un nodo nuevo (por IP) a conectarse a este host: abre en ufw los
#  puertos P2P + API sólo desde esa IP. Necesario en el modelo permisionado
#  (el firewall restringe P2P/API a nodos conocidos).
#
#    sudo bash whitelist-node.sh 203.0.113.9              # puertos por defecto
#    sudo bash whitelist-node.sh 203.0.113.9 65432 8000   # puertos explícitos
#
#  Para revocar:  sudo bash whitelist-node.sh --remove 203.0.113.9
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ok()  { printf "\033[1;32m  ✓ %s\033[0m\n" "$*"; }
die() { printf "\033[1;31m  ✗ %s\033[0m\n" "$*" >&2; exit 1; }

REMOVE=0
if [ "${1:-}" = "--remove" ]; then REMOVE=1; shift; fi
IP="${1:-}"; shift || true

[ "$(id -u)" -eq 0 ] || die "Ejecuta como root (ufw requiere privilegios)."
command -v ufw >/dev/null || die "ufw no está instalado."
[ -n "$IP" ] || die "Uso: whitelist-node.sh [--remove] <IP> [puerto...]"

# Validar IPv4
echo "$IP" | grep -qE '^([0-9]{1,3}\.){3}[0-9]{1,3}$' || die "IP inválida: $IP"
for o in ${IP//./ }; do [ "$o" -le 255 ] || die "IP inválida: $IP"; done

# Puertos: los pasados como argumento, o el conjunto por defecto (P2P + API).
if [ "$#" -gt 0 ]; then PORTS=("$@"); else PORTS=(65432 65433 8000); fi

if [ "$REMOVE" -eq 1 ]; then
  echo "▸ Revocando acceso de $IP en: ${PORTS[*]}"
  for p in "${PORTS[@]}"; do
    ufw delete allow from "$IP" to any port "$p" proto tcp >/dev/null 2>&1 \
      && ok "cerrado $p desde $IP" || echo "  (no había regla para $p desde $IP)"
  done
else
  echo "▸ Autorizando a $IP en: ${PORTS[*]}"
  for p in "${PORTS[@]}"; do
    # ufw es idempotente: si la regla ya existe, la salta.
    out=$(ufw allow from "$IP" to any port "$p" proto tcp comment "nodo $IP" 2>&1)
    case "$out" in
      *"Skipping"*) ok "puerto $p ya estaba abierto para $IP" ;;
      *) ok "abierto $p desde $IP" ;;
    esac
  done
fi

echo
echo "Reglas para $IP:"
ufw status | grep -F "$IP" || echo "  (ninguna)"
