#!/bin/bash
# ═══════════════════════════════════════════════════════════════
#  Metriplex Node Installer
#  Order from chaos — https://github.com/NTellezM/Metriplex
# ═══════════════════════════════════════════════════════════════

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

REPO="https://github.com/NTellezM/Metriplex"
REQUIRED_PYTHON="3.10"
NODE_DIR="$HOME/metriplex-node"

print_banner() {
    echo ""
    echo -e "${CYAN}${BOLD}"
    echo "  ███╗   ███╗███████╗████████╗██████╗ ██╗██████╗ ██╗     ███████╗██╗  ██╗"
    echo "  ████╗ ████║██╔════╝╚══██╔══╝██╔══██╗██║██╔══██╗██║     ██╔════╝╚██╗██╔╝"
    echo "  ██╔████╔██║█████╗     ██║   ██████╔╝██║██████╔╝██║     █████╗   ╚███╔╝ "
    echo "  ██║╚██╔╝██║██╔══╝     ██║   ██╔══██╗██║██╔═══╝ ██║     ██╔══╝   ██╔██╗ "
    echo "  ██║ ╚═╝ ██║███████╗   ██║   ██║  ██║██║██║     ███████╗███████╗██╔╝ ██╗"
    echo "  ╚═╝     ╚═╝╚══════╝   ╚═╝   ╚═╝  ╚═╝╚═╝╚═╝     ╚══════╝╚══════╝╚═╝  ╚═╝"
    echo -e "${NC}"
    echo -e "${BOLD}  Order from chaos — The first blockchain with fractal identity${NC}"
    echo -e "  ${BLUE}${REPO}${NC}"
    echo ""
}

print_step() {
    echo -e "\n${BLUE}${BOLD}[${1}/${TOTAL_STEPS}]${NC} ${BOLD}${2}${NC}"
}

print_ok() {
    echo -e "  ${GREEN}✓${NC} ${1}"
}

print_warn() {
    echo -e "  ${YELLOW}!${NC} ${1}"
}

print_error() {
    echo -e "  ${RED}✗${NC} ${1}"
}

check_command() {
    command -v "$1" >/dev/null 2>&1
}

TOTAL_STEPS=6

print_banner

# ── PASO 1: Sistema operativo ─────────────────────────────────
print_step 1 "Verificando sistema"

OS=$(uname -s)
case "$OS" in
    Linux*)   print_ok "Linux detectado" ;;
    Darwin*)  print_ok "macOS detectado" ;;
    *)        print_error "Sistema no soportado: $OS"; exit 1 ;;
esac

# ── PASO 2: Python ────────────────────────────────────────────
print_step 2 "Verificando Python $REQUIRED_PYTHON+"

if check_command python3; then
    PYTHON_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    PYTHON_OK=$(python3 -c "import sys; print(1 if sys.version_info >= (3,10) else 0)")
    if [ "$PYTHON_OK" = "1" ]; then
        print_ok "Python $PYTHON_VER encontrado"
    else
        print_error "Python $PYTHON_VER es muy antiguo. Necesitas Python 3.10+"
        echo ""
        echo "  Instalar en Ubuntu/Debian:"
        echo "    sudo apt install python3.12 python3.12-venv"
        echo "  Instalar en macOS:"
        echo "    brew install python@3.12"
        exit 1
    fi
else
    print_error "Python3 no encontrado"
    echo ""
    echo "  Instalar en Ubuntu/Debian:  sudo apt install python3 python3-venv"
    echo "  Instalar en macOS:          brew install python@3.12"
    exit 1
fi

# ── PASO 3: Git ───────────────────────────────────────────────
print_step 3 "Verificando Git"

if check_command git; then
    print_ok "Git $(git --version | cut -d' ' -f3) encontrado"
else
    print_error "Git no encontrado"
    echo "  sudo apt install git"
    exit 1
fi

# ── PASO 4: Clonar repositorio ───────────────────────────────
print_step 4 "Descargando Metriplex"

if [ -d "$NODE_DIR" ]; then
    print_warn "Directorio $NODE_DIR ya existe"
    echo -n "  ¿Actualizar la instalación existente? [s/N]: "
    read -r ANSWER
    if [[ "$ANSWER" =~ ^[sS]$ ]]; then
        cd "$NODE_DIR"
        git pull origin main
        print_ok "Repositorio actualizado"
    else
        print_ok "Usando instalación existente"
        cd "$NODE_DIR"
    fi
else
    git clone "$REPO" "$NODE_DIR"
    cd "$NODE_DIR"
    print_ok "Repositorio clonado en $NODE_DIR"
fi

# ── PASO 5: Entorno virtual y dependencias ───────────────────
print_step 5 "Instalando dependencias"

if [ ! -d "venv" ]; then
    python3 -m venv venv
    print_ok "Entorno virtual creado"
fi

source venv/bin/activate

pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

print_ok "Dependencias instaladas"
print_ok "  fastapi, uvicorn, cryptography, web3, numpy"

# ── PASO 6: Configuración inicial ────────────────────────────
print_step 6 "Configurando el nodo"

if [ ! -f ".env" ]; then
    cp .env.example .env
    print_ok "Archivo .env creado desde .env.example"
    print_warn "Edita .env si quieres configurar el relayer del puente"
fi

# ═══════════════════════════════════════════════════════════════
#  INSTALACIÓN COMPLETA
# ═══════════════════════════════════════════════════════════════

echo ""
echo -e "${GREEN}${BOLD}═══════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  ✓ Metriplex instalado correctamente      ${NC}"
echo -e "${GREEN}${BOLD}═══════════════════════════════════════════${NC}"
echo ""
echo -e "${BOLD}Directorio:${NC} $NODE_DIR"
echo ""
echo -e "${BOLD}Comandos disponibles:${NC}"
echo ""
echo -e "  ${CYAN}Arrancar un nodo validador:${NC}"
echo -e "  ${YELLOW}cd $NODE_DIR && source venv/bin/activate${NC}"
echo -e "  ${YELLOW}python main.py --miner-wallet pub_destino.json${NC}"
echo ""
echo -e "  ${CYAN}Arrancar como observador (sin minería):${NC}"
echo -e "  ${YELLOW}python main.py --no-miner${NC}"
echo ""
echo -e "  ${CYAN}Conectar a otro nodo de la red:${NC}"
echo -e "  ${YELLOW}python main.py --peer IP_DEL_NODO:65432${NC}"
echo ""
echo -e "  ${CYAN}Abrir la wallet:${NC}"
echo -e "  ${YELLOW}python wallet_cli.py${NC}"
echo ""
echo -e "  ${CYAN}API del nodo:${NC}"
echo -e "  ${YELLOW}http://localhost:8000/info${NC}"
echo ""
echo -e "${BOLD}Documentación:${NC}"
echo -e "  ${BLUE}${REPO}${NC}"
echo -e "  ${BLUE}${REPO}/blob/main/docs/DEPLOY.md${NC}"
echo ""
echo -e "${CYAN}${BOLD}  Order from chaos.${NC}"
echo ""
