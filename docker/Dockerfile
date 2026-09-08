FROM python:3.11-slim

LABEL maintainer="NTellezM <metriplexmpx@gmail.com>"
LABEL description="Metriplex Protocol — Layer 1 blockchain with fractal identity"

# Dependencias del sistema
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalar dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código
COPY . .

# Crear directorio para datos persistentes
RUN mkdir -p /data

# Variables de entorno por defecto
ENV API_PORT=8000
ENV P2P_PORT=65432
ENV PEER=157.180.113.24:65432
ENV MINER_PASSWORD=""
ENV NODE_DATA_DIR=/data

# Exponer puertos
EXPOSE 8000 65432

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -sf http://localhost:${API_PORT}/info || exit 1

# Entrypoint
CMD python3 main.py \
    --api-port ${API_PORT} \
    --p2p-port ${P2P_PORT} \
    --peer ${PEER} \
    ${MINER_WALLET:+--miner-wallet /data/${MINER_WALLET}} \
    ${NO_MINER:+--no-miner}
