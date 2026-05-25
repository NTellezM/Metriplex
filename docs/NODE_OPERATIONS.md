# Metriplex — Node Operations Guide

Reference for running and maintaining Metriplex nodes.

---

## Current Network (May 2026)
node-0:    157.180.113.24:65432   VPS Hetzner Germany   validator+miner   systemd
NT-vps:    157.180.113.24:65433   VPS Hetzner Germany   observer          systemd
node-2:    190.82.149.108:65434   Chile                 validator+miner   systemd
NT-laptop: 190.82.149.108:65435   Chile                 validator+miner   systemd
Chain: ~7,500+ blocks · block time 60s · FVR active · 3 validators

---

## VPS (node-0) — Systemd Services

```bash
# Status
systemctl status metriplex.service metriplex-relayer.service

# Restart
systemctl restart metriplex.service

# Logs
journalctl -u metriplex.service -f --no-pager
journalctl -u metriplex-relayer.service -f --no-pager

# Health check
bash /opt/Metriplex/metriplex_health.sh
```

---

## Chile Nodes — Systemd Services

```bash
# Status
sudo systemctl status metriplex-node2.service
sudo systemctl status metriplex-ntlap.service

# Restart
sudo systemctl restart metriplex-node2.service
sudo systemctl restart metriplex-ntlap.service

# Logs
sudo journalctl -u metriplex-node2.service -f --no-pager
sudo journalctl -u metriplex-ntlap.service -f --no-pager
```

---

## Manual Start (Chile)

```bash
# node-2
export MINER_PASSWORD=123
cd ~/Metriplex && source venv/bin/activate
python3 main.py --api-port 8002 --p2p-port 65434 --miner-wallet keystore_node2.json

# NT-laptop
export MINER_PASSWORD=123
cd ~/Proyectos/Metriplex && source venv/bin/activate
python3 main.py --api-port 8003 --p2p-port 65435 --miner-wallet keystore_nt_laptop.json
```

---

## Resync a Node

```bash
# Stop, delete DB, restart
systemctl stop metriplex.service
rm /opt/Metriplex/node_data_8000.db
systemctl start metriplex.service

# Chile
sudo systemctl stop metriplex-node2.service
rm ~/Metriplex/node_data_8002.db
sudo systemctl start metriplex-node2.service
```

---

## Balances

```bash
# node-0 wallet
curl -s http://localhost:8000/balance/44225e0c | python3 -m json.tool

# Vault
curl -s http://localhost:8000/balance/f695d4a5 | python3 -m json.tool

# All balances
python3 -c "
import sqlite3
conn = sqlite3.connect('/opt/Metriplex/node_data_8000.db')
rows = conn.execute('SELECT tensor_hash, balance FROM balances ORDER BY balance DESC').fetchall()
for r in rows: print(r[0][:16], r[1]/1073741824, 'MPX')
"
```

---

## FVR Validators

```bash
curl -s http://localhost:8000/validators | python3 -m json.tool
```

Current validators:
44225e0c  node-0     157.180.113.24:65432   registered block 451
3542268a  node-2     190.82.149.108:65434   registered block 491
ee481176  NT-laptop  190.82.149.108:65435   registered block 713

---

## Bridge Relayer

```bash
# Status
systemctl status metriplex-relayer.service

# Logs
journalctl -u metriplex-relayer.service -f --no-pager

# Vault balance
curl -s http://localhost:8000/balance/f695d4a5 | python3 -m json.tool
```

---

## Update Nodes

```bash
# VPS
cd /opt/Metriplex && git pull
systemctl restart metriplex.service

# Chile (with systemd)
cd ~/Metriplex && git pull
sudo systemctl restart metriplex-node2.service

cd ~/Proyectos/Metriplex && git pull
sudo systemctl restart metriplex-ntlap.service
```

---

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/info` | GET | Chain height, mempool, latest hash |
| `/blocks` | GET | Last 10 blocks |
| `/validators` | GET | FVR validator set |
| `/balance/{hash8}` | GET | Account balance |
| `/transaction` | POST | Submit signed TX |
| `/mine` | POST | Force block production |

---

## Network Parameters

| Parameter | Value |
|-----------|-------|
| Block time | 60 seconds |
| Block reward | 50 MPX |
| Max reorg depth | 200 blocks |
| Snapshot interval | every 1,000 blocks |
| TX TTL | 10 minutes |
| P2P port | 65432 (default) |
| API port | 8000 (default) |

---

## Monitoring (Telegram)

Automatic alerts every 5 minutes via `@MPXAlertBot`:
- Relayer down
- Chain stopped
- Node isolated
- Fork detected
- Vault balance drop

Manual check:
```bash
bash /opt/Metriplex/metriplex_health.sh
```

---

*Metriplex — Order from chaos · [metriplexmpx.xyz](https://metriplexmpx.xyz)*
