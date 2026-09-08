#!/usr/bin/env python3
"""Monitor de solo lectura; Telegram únicamente para cambios de estado."""
import argparse
import concurrent.futures
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

NODES = {"node-0": "http://127.0.0.1:8000", "node-NT": "http://127.0.0.1:8001",
         "node-3": "http://5.78.209.5:8003"}
SERVICES = ("metriplex", "metriplex-nt", "metriplex-relayer")
BLOCK_SECONDS = 60
STATE_DIR = Path("/var/lib/metriplex-monitor")


def fetch(url):
    try:
        with urllib.request.urlopen(url, timeout=6) as response:
            return json.load(response)
    except (OSError, ValueError):
        return None


def command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=12)
        return result.returncode, result.stdout
    except (OSError, subprocess.TimeoutExpired):
        return -1, ""


def collect():
    urls = {name: url + "/info" for name, url in NODES.items()}
    urls.update(validators=NODES["node-0"] + "/validators",
                network=NODES["node-0"] + "/network",
                block=NODES["node-0"] + "/blocks?limit=1",
                vault=NODES["node-0"] + "/balance/f695d4a5")
    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as pool:
        results = dict(zip(urls, pool.map(fetch, urls.values())))
    results["services"] = {s: command(["systemctl", "is-active", s + ".service"])[1].strip()
                           for s in SERVICES}
    # Solo el proceso vigente: un error anterior al reinicio no debe mantener una alerta.
    _, pid = command(["systemctl", "show", "metriplex.service", "-p", "MainPID", "--value"])
    results["journal_rc"], results["journal"] = command([
        "journalctl", "-u", "metriplex.service", "_PID=" + pid.strip(),
        "--since", "75 minutes ago", "-o", "short-unix", "--no-pager"])
    results["now"] = time.time()
    return results


def analyze(data, previous):
    issues = {}
    def issue(key, detail, confirmations=1):
        issues[key] = {"detail": detail, "confirmations": confirmations}
    infos = {}
    for name in NODES:
        info = data.get(name)
        if (not isinstance(info, dict) or not isinstance(info.get("chain_length"), int)
                or info["chain_length"] < 1 or not isinstance(info.get("latest_block_hash"), str)
                or len(info["latest_block_hash"]) != 64):
            issue("api:" + name, name + ": API sin respuesta válida", 2)
        else:
            infos[name] = info
    for service, status in data["services"].items():
        if status != "active":
            issue("service:" + service, service + ": servicio " + (status or "desconocido"))
    if len(infos) >= 2:
        max_length = max(i["chain_length"] for i in infos.values())
        for name, info in infos.items():
            lag = max_length - info["chain_length"]
            if lag:
                issue("lag:" + name, f"{name}: {lag} bloques de retraso", 2)
        names = sorted(infos)
        for i, name in enumerate(names):
            for other in names[i+1:]:
                a, b = infos[name], infos[other]
                if a["chain_length"] == b["chain_length"] and a["latest_block_hash"] != b["latest_block_hash"]:
                    issue("fork:" + name + ":" + other,
                          f"{name} y {other}: hashes distintos a altura {a['chain_length']-1}", 2)
    validators = data.get("validators")
    count = validators.get("count") if isinstance(validators, dict) else None
    if not isinstance(count, int) or count < 1:
        issue("check:validators", "No se pudo consultar el registro de validadores", 2)
        count = 4
    # Cinco rondas nominales de N slots de 60s; no se altera el consenso.
    max_age = max(600, min(BLOCK_SECONDS * count * 5, 1800))
    blocks = data.get("block")
    age = None
    if (isinstance(blocks, list) and blocks and isinstance(blocks[0], dict)
            and isinstance(blocks[0].get("timestamp"), (int, float))):
        age = int(data["now"] - blocks[0]["timestamp"])
        if age > max_age:
            issue("chain:stalled", f"Cadena sin bloque nuevo hace {age}s (umbral {max_age}s)")
        elif age < -60:
            issue("chain:clock", "Timestamp del último bloque adelantado respecto al monitor")
    else:
        issue("check:block", "No se pudo verificar la antigüedad del último bloque", 2)
    network = data.get("network")
    nodes = network.get("nodes") if isinstance(network, dict) else None
    online = []
    if isinstance(nodes, dict):
        online = [name for name, info in nodes.items()
                  if name != "local" and isinstance(info, dict) and info.get("online") is True]
        if not online:
            issue("peers:isolated", "Nodo principal aislado: 0 peers accesibles", 2)
    else:
        issue("check:peers", "No se pudo consultar la conectividad de peers", 2)
    journal = data.get("journal", "")
    if data.get("journal_rc") != 0:
        issue("check:journal", "No se pudieron consultar los registros GEO y de forks", 2)
    else:
        geo_success, geo_error, auth = 0, 0, {}
        forks = 0
        for line in journal.splitlines():
            match = re.match(r"^(\d+(?:\.\d+)?)\s", line)
            if not match:
                continue
            stamp = float(match.group(1))
            if "[GEO] Proof precomputado" in line:
                geo_success = stamp
            if "[GEO] Error computando proof" in line:
                geo_error = stamp
            if "[GEO] Peer autenticado (validador): " in line:
                auth[line.rsplit(": ", 1)[-1].strip()] = stamp
            if stamp >= data["now"] - 300 and re.search(
                    r"bifurcación detectad[ao]|Fork detectado", line, re.I):
                forks += 1
        if geo_error > geo_success or not geo_success:
            issue("geo:local", "GEO local: falta una prueba vigente generada correctamente", 2)
        if isinstance(validators, dict):
            for entry in validators.get("validators", []):
                endpoint = entry.get("endpoint")
                if endpoint in online and data["now"] - auth.get(endpoint, 0) > 300:
                    issue("geo:" + endpoint, f"GEO: peer {endpoint} accesible pero sin autenticación reciente", 2)
        if forks > 3:
            issue("forks:frequent", f"{forks} avisos de fork en los últimos 5 minutos")
    vault = data.get("vault")
    vault = vault.get("balance_caf") if isinstance(vault, dict) else None
    if not isinstance(vault, (int, float)):
        issue("check:vault", "No se pudo consultar el saldo del vault", 2)
        vault = previous.get("vault")
    reference = previous.get("vault_drop_reference")
    if isinstance(vault, (int, float)):
        if reference is None and previous.get("vault") is not None and previous["vault"] - vault > 10000:
            reference = previous["vault"]
        if reference is not None:
            if vault < reference:
                issue("vault:drop", f"Vault bajó de {reference} a {vault} MPX")
            else:
                reference = None
    return issues, {"vault": vault, "vault_drop_reference": reference}, {"nodes": infos, "block_age_seconds": age,
                                      "max_block_age_seconds": max_age, "online_peers": online}


def transition(issues, previous, now):
    streaks = {key: previous.get("streaks", {}).get(key, 0) + 1 for key in issues}
    active = previous.get("active", {})
    current = {key: value["detail"] for key, value in issues.items()
               if key in active or streaks[key] >= value["confirmations"]}
    opened = {k: v for k, v in current.items() if k not in active}
    # Una consulta fallida no prueba que la sincronización o GEO se recuperaron.
    blind = any(k.startswith(("api:", "check:")) for k in issues)
    if blind:
        for key, detail in active.items():
            if key not in current and not key.startswith(("api:", "check:", "service:")):
                current[key] = detail
    resolved = {k: v for k, v in active.items() if k not in current}
    lines = []
    if opened:
        lines.append("⚠️ Problemas detectados:")
        lines.extend("• " + v for v in opened.values())
    if resolved:
        lines.append("✅ Condiciones resueltas:")
        lines.extend("• " + k for k in resolved)
    return {"streaks": streaks, "active": current, "checked_at": now}, "\n".join(lines)


def send_alert(message):
    token, chat = os.environ.get("BOT_TOKEN"), os.environ.get("CHAT_ID")
    if not token or not chat:
        print("Telegram: faltan credenciales; estado pendiente de notificar", file=sys.stderr)
        return False
    request = urllib.request.Request("https://api.telegram.org/bot" + token + "/sendMessage",
        data=urllib.parse.urlencode({"chat_id": chat, "text": message}).encode(), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            result = json.load(response)
        if result.get("ok") is True:
            return True
        print("Telegram: respuesta sin confirmación ok; se reintentará", file=sys.stderr)
    except urllib.error.HTTPError as error:
        print(f"Telegram: HTTP {error.code}; se reintentará", file=sys.stderr)
    except (OSError, ValueError):
        print("Telegram: fallo de conexión o respuesta; se reintentará", file=sys.stderr)
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="No enviar ni escribir estado")
    args = parser.parse_args()
    if not args.dry_run:
        STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock = (STATE_DIR / "lock").open("a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
    state_file = STATE_DIR / "state.json"
    try:
        previous = json.loads(state_file.read_text())
        if not isinstance(previous, dict):
            raise ValueError("invalid state")
    except FileNotFoundError:
        previous = {}
    except (OSError, ValueError):
        print("Estado del monitor ilegible; no se sobrescribe", file=sys.stderr)
        return 1
    data = collect()
    issues, baseline, summary = analyze(data, previous)
    state, message = transition(issues, previous, data["now"])
    state.update(baseline)
    if args.dry_run:
        print(json.dumps({"summary": summary, "issues": issues, "would_send": message}, ensure_ascii=False, indent=2))
        return 0
    if message:
        message = "METRIPLEX — " + time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()) + "\n\n" + message
        if not send_alert(message):
            # Conservar pendientes y baseline (incluidas caídas puntuales de saldo).
            return 1
    temporary = state_file.with_suffix(".tmp")
    with temporary.open("w") as output:
        os.chmod(temporary, 0o600)
        json.dump(state, output)
    temporary.replace(state_file)
    print(f"Monitor OK: {len(state['active'])} alertas activas; Telegram: {'cambio notificado' if message else 'sin cambios'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
