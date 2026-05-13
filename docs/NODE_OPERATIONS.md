# Metriplex — Genesis Node Operation Guide
## How to start and expose the node publicly

---

## Prerequisites

- Ubuntu 24.04 (Lenovo Y520)
- Python 3.12
- ngrok installed and authenticated
- Metriplex repo at `~/Proyectos/metriplex`

---

## Step 1 — Kill any existing processes on the ports

```bash
sudo fuser -k 8000/tcp
sudo fuser -k 65432/tcp
sleep 2
```

---

## Step 2 — Start the genesis node (Terminal 1)

```bash
cd ~/Proyectos/metriplex
source venv/bin/activate
python3 main.py --api-port 8000 --p2p-port 65432
```

Expected output:
```
==================================================
 NODO CAF | API: 8000 | P2P: 65432 | ROL: VALIDADOR (Minero)
==================================================
[✓] Cadena cargada (N bloques en disco).
[✓] Mempool inicializado.
[Consenso] Motor de Elección de Líder iniciado.
[Red] Nodo P2P escuchando en 0.0.0.0:65432
```

---

## Step 3 — Open the public tunnel (Terminal 2)

```bash
ngrok http 8000
```

---

## Step 4 — Get the public URL (Terminal 3)

```bash
curl -s http://localhost:4040/api/tunnels | python3 -c \
  "import sys,json; print(json.load(sys.stdin)['tunnels'][0]['public_url'])"
```

---

## Step 5 — Verify the node is reachable

```bash
curl -s https://YOUR-NGROK-URL.ngrok-free.app/info
```

Expected response:
```json
{
  "chain_length": 1,
  "mempool_size": 0,
  "latest_block_hash": "0000...0000"
}
```

---

## Step 6 — Update nodes.html if the ngrok URL changed

```bash
cd ~/Proyectos/metriplex
sed -i "s|var NODE_URL = '.*'|var NODE_URL = 'https://YOUR-NEW-URL.ngrok-free.app'|" nodes.html
git add nodes.html
git commit -m "fix: update ngrok URL for genesis node"
git push origin main
```

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/info` | GET | Chain height, mempool, latest hash |
| `/blocks` | GET | Full chain |
| `/balance/{tensor_hash}` | GET | Account balance |
| `/transaction` | POST | Submit signed TX |
| `/peers` | GET | Connected P2P peers |
| `/mine` | POST | Force block production |

---

## Quick test — mine a block manually

```bash
curl -s -X POST https://YOUR-NGROK-URL.ngrok-free.app/mine
```

---

## Node status page

```
https://metriplexmpx.xyz/nodes.html
```

Live chain stats update every 30 seconds from the genesis node API.

---

## Current network state

```
Phase:        1 — Single validator
Chain height: 1 (genesis block)
Validators:   1 (node-0, genesis)
Pending:      @zicheng588 (awaiting testnet)
P2P port:     65432
API port:     8000
Consensus:    Slot-based PoS
Block time:   10 seconds
```

---

## Next milestone — Multi-node testnet (Phase 2)

When @zicheng588 connects their node:

1. Share the genesis node P2P address: `YOUR-NGROK-URL.ngrok-free.app:65432`
2. They start their node with: `python3 main.py --peer YOUR-IP:65432`
3. Both nodes sync the chain
4. First multi-node block is produced

This will be the first time two independent Metriplex nodes communicate.

---

## Long-term — VPS setup (recommended)

For 24/7 uptime without depending on the laptop:

```
Provider:  Hetzner CX22 (~$4/month)
OS:        Ubuntu 24.04
Steps:
1. apt install python3 python3-venv git
2. git clone https://github.com/NTellezM/Metriplex
3. python3 -m venv venv && source venv/bin/activate
4. pip install -r requirements.txt
5. python3 main.py --api-port 8000 --p2p-port 65432 &
6. Point nodes.html to the VPS IP
```

No ngrok needed — the VPS has a fixed public IP.

---

*Metriplex · Order from chaos · metriplexmpx.xyz*
