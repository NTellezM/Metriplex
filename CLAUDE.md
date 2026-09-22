# Metriplex — guía operativa

Blockchain en Python. Identidad = atractor fractal; firma = prueba ZK sobre ese
atractor; líder del slot = distancia de Lyapunov. Dos validadores en producción,
un bloque cada 60 s.

Diagramas y contexto: `Documentos/Obsidian Vault/Proyectos/Metriplex — Mapa del proyecto.md`.

## Producción

| | nodo1 (Hetzner) | nodo3 (Falkenstein) |
|---|---|---|
| acceso | `ssh root@157.180.113.24` | `ssh -i ~/.ssh/metriplex_node3 root@5.78.209.5` |
| servicios | `metriplex` (8000/65432, mina), `metriplex-nt` (8001/65433, `--no-miner`), `metriplex-relayer` | `metriplex-node3` (8003/65436, mina) |
| código | `/opt/Metriplex` (venv en `venv/`) | igual |
| BD | `node_data_8000.db`, `node_data_8001.db` | `node_data_8003.db` |
| identidad | `bdb8c1f4a4a0…` | `203a4d51213f…` |
| recursos | holgados | **2 GB RAM + 4 GB swap** — vigilar memoria |

Web: nginx en nodo1 sirve `/var/www/metriplexmpx.xyz`; `/node/` → 8000, `/node2/` → 8001.

Estado de un nodo: `curl -s localhost:8000/info` (`chain_length`, `latest_block_hash`).
Endpoints reales: `/info`, `/blocks`, `/validators`, `/balance/{hash}`, `/peers`, `/network`.
**No existe `/status`.**

## Reglas que no se negocian

1. **Rust es obligatorio.** El tensor M3 se calcula en `metriplex_core` (`rust_core/`).
   El respaldo en Python da otro resultado; un nodo sin Rust queda fuera de consenso
   y un keystore creado sin él nace con el saldo inmovilizado. `require_rust()` aborta
   el arranque a propósito — no relajarlo.
2. **Los cambios de consenso entran por altura**, en `blockchain/rules.py`, y **los dos
   nodos se despliegan antes de esa altura**. Nunca dependen del momento del reinicio.
3. **Todo arreglo lleva un test de regresión que se comprueba fallando contra el código
   de producción** antes de darlo por bueno. Si el test pasa sin el arreglo, no prueba nada.
4. **Nunca reescribir bloques conservados desde RAM.** `VENTANA_PRUEBAS` suelta `x_final`
   de los bloques viejos en memoria; persistirlos corrompe el disco (incidente 21-09).
   `rollback_to` usa `storage.truncate_blocks_above`.
5. **Los keystores no se imprimen ni se copian entre máquinas.** Para medir algo de una
   clave, calcular en el propio servidor y mostrar solo el resultado.

## Alturas de activación

| altura | constante | qué cambia |
|---|---|---|
| 107342 | `PROTOCOL_SIG_ACTIVATION` | firma ZK en operaciones de protocolo |
| 109000 | `TX_V2_ACTIVATION` | sobre firmado con `chain_id` y nonce |
| 111900 | `ZK_TOLERANCE_ACTIVATION` | margen relativo 1 %: ata la prueba a la clave |
| 123000 | `DUAL_TENSOR_ACTIVATION` | acepta el tensor de Rust **o** el de Python |

## Constantes con historia

`N_PROOF = 2000` (`crypto/zkp.py`) — `x_final` es el atractor completo, error 0. Subirlo
desde 400 cerró la falsificación y quintuplicó el peso del bloque (~98 KB): de ahí salieron
el OOM de nodo3, la cascada de rollbacks y los `FULL_CHAIN` que no cabían.

`MAX_REORG_DEPTH = 200` · `MAX_ROLLBACKS_SEGURIDAD = 10` (10 × 20 = 200, el freno) ·
`max_message = 32 MiB` · `FULL_CHAIN_PAGINA_BYTES = 8 MiB` · `VENTANA_PRUEBAS = 260` ·
`BLOCK_TIME_SECONDS = 60`.

## Tests

```bash
/home/nt/.cache/metriplex-testenv/bin/python -m pytest tests/ -q
```

Ese entorno tiene `metriplex_core` compilado; el `python3` del sistema no.
Tests en español, un archivo por incidente, con el porqué en el docstring.

## Despliegue

Rama → PR → merge. En cada nodo:

```bash
cd /opt/Metriplex && git pull && systemctl restart <servicio>
journalctl -u <servicio> -n 50 --no-pager
```

Tras reiniciar, comprobar que ambos convergen (`chain_length` y `latest_block_hash` iguales).
Un fork breve al reiniciar es normal: se resuelve por `FULL_CHAIN` paginado.

## Límites del entorno de Claude Code

El clasificador de seguridad bloquea escrituras remotas por SSH, `git reset --hard`,
el uso de credenciales y algunos comandos que relajan verificaciones. Cuando ocurra:
**dar los comandos al usuario para que los ejecute él**, no buscar rodeos.

## Convenciones

- Idioma: **español**, en el código, los commits y la conversación.
- Comentarios y docstrings **sin tildes** (ASCII); el texto de usuario sí las lleva.
- Commits: `tipo(ambito): descripción` — `fix(p2p): subir el tope de mensaje`.
- Los comentarios explican **por qué**, con el incidente y la fecha cuando aplique.

## Pendientes

- Memoria definitiva: acotar la cadena en RAM a ~200 bloques (hoy crece ~10 MB/día).
- `fix/identidad-tensor-python`: rama lista y probada, sin desplegar. Desbloquea los
  ~5.313 MPX de nodo3 en la altura 123000.
- Poda en disco: exige sacar `signature_data` del hash del bloque.
- Conexiones sin cerrar en los `return` tempranos de `handle_client`.
- `verify_proof` sin `block_index` (votos de gobernanza, handshake P2P) sigue usando la
  tolerancia antigua, muy amplia.
- Respaldos de la reparación por limpiar: `/root/node_data_8003_ANTES_REPARAR_*.db` (nodo3),
  `/root/node_data_8000_SANA_20260921.db` y `/root/reparacion_export.json.gz` (nodo1).
