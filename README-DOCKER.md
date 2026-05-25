# Metriplex Node — Docker Setup

## Quick Start (Observer Node)

```bash
docker run -d \
  --name metriplex-node \
  -p 8000:8000 \
  -p 65432:65432 \
  -e NO_MINER=1 \
  -e PEER=157.180.113.24:65432 \
  -v metriplex-data:/data \
  ntellezm/metriplex:latest
```

## Validator Node

```bash
# 1. Generate your keystore
docker run --rm -v metriplex-data:/data ntellezm/metriplex:latest \
  python3 wallet_cli.py generate --output /data/keystore.json

# 2. Run validator
docker run -d \
  --name metriplex-validator \
  -p 8000:8000 \
  -p 65432:65432 \
  -e MINER_WALLET=keystore.json \
  -e MINER_PASSWORD=your_password \
  -e PEER=157.180.113.24:65432 \
  -v metriplex-data:/data \
  ntellezm/metriplex:latest
```

## Docker Compose

```bash
# Observer
NO_MINER=1 docker-compose up -d

# Validator
MINER_WALLET=keystore.json MINER_PASSWORD=your_password docker-compose up -d
```

## Check Status

```bash
curl http://localhost:8000/info
curl http://localhost:8000/validators
```

## Update

```bash
docker-compose pull && docker-compose up -d
```

## Ports

| Port  | Protocol | Description        |
|-------|----------|--------------------|
| 8000  | TCP/HTTP | REST API           |
| 65432 | TCP      | P2P gossip network |

## Network

- Genesis node: `157.180.113.24:65432`
- Explorer: https://metriplexmpx.xyz/nodes.html
- Contract: `0x22D3f414438556d1B071cCfE52513d4d829400fd`
