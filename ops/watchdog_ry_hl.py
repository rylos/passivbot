#!/usr/bin/env python3
"""Watchdog del bot live ry-hl (Hyperliquid) su amazon.

Legge il log corrente, rileva anomalie e avvisa su due canali:
  - Telegram (Claude RyLoS Bot), con cooldown per categoria
  - healthchecks.io, check "passivbot (hl)": ping di successo col riepilogo nel
    body, /fail con la diagnosi. Se il cron o la macchina muoiono il check scade
    da solo: e' il dead man switch che Telegram da solo non da'.

RIAVVIO AUTOMATICO, solo se il processo e' ASSENTE (crash/OOM/kill). Un bot vivo
ma bloccato NON viene toccato: e' il caso dell'incidente del 28/07 (trailing
bloccato 27 ore), dove serviva capire prima di agire.
Freni: al massimo MAX_RESTARTS tentativi in RESTART_WINDOW_MIN minuti e nessun
riavvio se esiste il file di manutenzione.
"""
from __future__ import annotations

import calendar
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path.home() / "watchdog"
LOG = Path("/opt/passivbot-hl/logs/hyperliquid_vault.log")
STATE = BASE / "state.json"
CREDS = BASE / "telegram.json"
ENV = BASE / "healthchecks.env"
# Se questo file esiste il watchdog non riavvia nulla: interruttore per le fermate
# volute (deploy, ricompilazione Rust, manutenzione).
MAINTENANCE = BASE / "hl_maintenance"

BOT_DIR = Path("/opt/passivbot-hl")
TMUX_SESSION = "ry-hl"
# ⚠️ Python del PROPRIO venv, esplicito: `python` generico e' l'origine della
# trappola del 2026-07-29 (il venv copiato puntava a /opt/passivbot).
BOT_CMD = f"cd {BOT_DIR} && venv/bin/python src/main.py configs/live/config_hl_4rsi.json"

# Un bot che non riparte da solo ha un problema che il riavvio non risolve.
MAX_RESTARTS = 2
RESTART_WINDOW_MIN = 60
RESTART_WAIT_S = 90

# Quanto silenzio sul log prima di gridare (minuti).
# Misurato sui log reali (3 giorni, 6000 righe): la riga [health] esce ogni ~15 min,
# gap p99 = 12 min, gap massimo osservato 15.5 min, nessun gap sopra i 20 min.
# 35 min = oltre due cicli [health] persi, quindi anomalia vera e non cadenza normale.
STALE_MIN = 35
# Il warning di trailing warmup dura ~5 min dopo un fill/restart: serve persistenza.
BLOCK_PERSIST_MIN = 20
# Soglia del contatore errori nella riga [health] (il limite del bot è 10).
ERR_COUNTER_MIN = 3
# Canale unico: healthchecks.io (che notifica su Telegram RyLoS e via email) —
# cosi' non arrivano due messaggi per lo stesso evento da due bot diversi, e il
# caso "watchdog/macchina morti" e' coperto, cosa che l'invio diretto non fa.
# Gli invii diretti restano nel codice: basta rimettere True per riaccenderli.
TELEGRAM_ENABLED = False
# secondi di cooldown per categoria, per non spammare
COOLDOWN = {
    "process_down": 900,
    "log_stale": 1800,
    "errors": 1800,
    "trailing_blocked": 3600,
    "err_counter": 3600,
    "restart": 0,
}
BLOCK_PATTERNS = (
    "position_fill_confirmation_pending",
    "trailing state unavailable",
    "fill_after_state_mismatch",
    "nontradable",
    "tradable=false",
)
TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z")
HEALTH_RE = re.compile(r"\[health\].*?err=(\d+)/(\d+)")


def hc_url() -> str | None:
    """URL di ping: in un file separato perche' e' una credenziale (chi ce l'ha
    puo' segnare 'up' un bot morto)."""
    if not ENV.exists():
        return None
    for line in ENV.read_text().splitlines():
        line = line.strip()
        if line.startswith("HC_PASSIVBOT="):
            return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    return None


def hc_ping(ok: bool, body: str) -> None:
    url = hc_url()
    if not url:
        return
    if not ok:
        url = url.rstrip("/") + "/fail"
    try:
        req = urllib.request.Request(url, data=body.encode()[:9000])
        with urllib.request.urlopen(req, timeout=20) as r:
            r.read()
    except Exception:  # il ping non deve mai far fallire il controllo
        pass


def tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", *args], capture_output=True, text=True)


def try_restart(state: dict) -> list[str]:
    """Rilancia ry-hl nel suo tmux. Ritorna le righe di esito per il body del ping."""
    if MAINTENANCE.exists():
        return [f"riavvio NON tentato: manutenzione attiva ({MAINTENANCE})"]

    now = time.time()
    recent = [t for t in state.get("restarts", []) if now - t < RESTART_WINDOW_MIN * 60]
    if len(recent) >= MAX_RESTARTS:
        state["restarts"] = recent
        return [
            f"riavvio NON tentato: gia' {len(recent)} tentativi in {RESTART_WINDOW_MIN} min, "
            "serve un intervento a mano"
        ]

    out = []
    if tmux("has-session", "-t", TMUX_SESSION).returncode != 0:
        r = tmux("new-session", "-d", "-s", TMUX_SESSION, "-c", str(BOT_DIR))
        if r.returncode != 0:
            return [f"riavvio FALLITO: sessione tmux non creabile ({r.stderr.strip()})"]
        out.append(f"sessione tmux '{TMUX_SESSION}' ricreata (non esisteva)")

    r = tmux("send-keys", "-t", TMUX_SESSION, BOT_CMD, "Enter")
    if r.returncode != 0:
        return out + [f"riavvio FALLITO: send-keys ({r.stderr.strip()})"]

    recent.append(now)
    state["restarts"] = recent

    deadline = now + RESTART_WAIT_S
    while time.time() < deadline:
        time.sleep(5)
        pid = bot_pid()
        if pid:
            out.append(f"RIAVVIATO: nuovo pid {pid} dopo {time.time() - now:.0f}s")
            # Il banner [runtime] dice quale commit sta girando davvero: dopo il
            # 2026-07-29 e' la verifica obbligatoria di ogni ripartenza.
            out.append("verificare il banner [runtime] python=<hash> nel log")
            return out
    return out + [f"riavvio FALLITO: nessun processo dopo {RESTART_WAIT_S}s"]


def send(text: str) -> None:
    if not TELEGRAM_ENABLED:
        return
    creds = json.loads(CREDS.read_text())
    data = urllib.parse.urlencode(
        {"chat_id": creds["chat_id"], "text": text, "parse_mode": "HTML"}
    ).encode()
    url = "https://api.telegram.org/bot" + creds["token"] + "/sendMessage"
    with urllib.request.urlopen(url, data=data, timeout=30) as r:
        r.read()


def load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text())
        except json.JSONDecodeError:
            pass
    return {"offset": 0, "target": "", "last_alert": {}}


# Diagnosi del giro corrente: finisce nel body del ping (e quindi nella notifica).
PROBLEMS: list[str] = []


def alert(state: dict, kind: str, text: str) -> None:
    plain = re.sub(r"<[^>]+>", "", text).replace("\n", " | ")
    if kind != "restart":  # il riavvio del bot e' informativo, non un guasto
        PROBLEMS.append(plain)
    now = time.time()
    last = state["last_alert"].get(kind, 0)
    if now - last < COOLDOWN.get(kind, 1800):
        return
    send(text)
    state["last_alert"][kind] = now


def bot_pid() -> str | None:
    r = subprocess.run(
        # Il pattern deve reggere sia "python src/main.py" sia
        # "venv/bin/python src/main.py" (BOT_CMD usa il python del venv):
        # un pattern ancorato a ^python non vedeva il bot avviato dal venv e
        # il watchdog lo avrebbe considerato assente, avviandone un secondo.
        ["pgrep", "-f", r"python src/main\.py configs/live/config_hl_4rsi\.json"],
        capture_output=True,
        text=True,
    )
    pids = [p for p in r.stdout.split() if p.strip()]
    return pids[0] if pids else None


def tail_new(state: dict) -> list[str]:
    """Righe nuove dall'ultimo giro; gestisce rotazione/restart del log."""
    target = os.path.realpath(LOG)
    if target != state.get("target"):
        state["target"] = target
        state["offset"] = 0
        state["rotated"] = True
    else:
        state["rotated"] = False
    size = os.path.getsize(target)
    if size < state["offset"]:  # troncato
        state["offset"] = 0
    with open(target, "r", errors="replace") as f:
        f.seek(state["offset"])
        lines = f.read().splitlines()
        state["offset"] = f.tell()
    return lines


def last_ts(target: str) -> float | None:
    """Timestamp dell'ultima riga con data valida."""
    try:
        with open(target, "rb") as f:
            f.seek(max(0, os.path.getsize(target) - 65536))
            chunk = f.read().decode(errors="replace")
    except OSError:
        return None
    for line in reversed(chunk.splitlines()):
        m = TS_RE.match(line)
        if m:  # i log del bot sono in UTC
            return calendar.timegm(time.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S"))
    return None


def last_line(target: str) -> str:
    try:
        with open(target, "rb") as f:
            f.seek(max(0, os.path.getsize(target) - 8192))
            lines = f.read().decode(errors="replace").splitlines()
        return lines[-1] if lines else ""
    except OSError:
        return ""


def main() -> None:
    state = load_state()
    pid = bot_pid()

    if not LOG.exists():
        alert(state, "log_stale", "⚠️ <b>ry-hl</b>: log non trovato su amazon.")
        STATE.write_text(json.dumps(state))
        return

    lines = tail_new(state)
    target = state["target"]

    if state.get("rotated") and state["last_alert"]:
        alert(
            state,
            "restart",
            "ℹ️ <b>ry-hl riavviato</b>\nnuovo log: <code>"
            + os.path.basename(target)
            + "</code>\npid: "
            + (pid or "assente"),
        )

    if pid is None:
        alert(
            state,
            "process_down",
            "🔴 <b>ry-hl NON in esecuzione</b> su amazon.\n"
            "Nessun processo <code>python src/main.py</code>. Il bot non sta gestendo la posizione.",
        )
        PROBLEMS.extend(try_restart(state))
        STATE.write_text(json.dumps(state))
        return

    # log fermo?
    lt = last_ts(target)
    if lt is not None:
        age_min = (time.time() - lt) / 60
        if age_min > STALE_MIN:
            tail = last_line(target)
            alert(
                state,
                "log_stale",
                f"🟠 <b>ry-hl: log fermo da {age_min:.0f} min</b> (pid {pid} vivo, "
                f"normale è &lt;16 min).\nPossibile loop bloccato o connettività persa.\n"
                f"Ultima riga:\n<code>{esc(tail[:220])}</code>",
            )

    # Un ciclo "degraded" isolato è il fail-closed previsto del bot (es. EMA close non
    # ancora disponibile): il ciclo viene abbandonato e ritentato, e il bot stesso lo
    # conta nel suo error budget (limite 10/h). Non allarmo sul singolo evento: se il
    # problema persiste lo intercetta la regola err=N/10 con N>=3.
    errs = [
        l
        for l in lines
        if (" ERROR " in l or " CRITICAL " in l or "Traceback (most recent" in l)
        and "[cycle] degraded" not in l
        and "action=record_error_restart_backoff" not in l
    ]
    if errs:
        sample = "\n".join(l[:220] for l in errs[:3])
        alert(
            state,
            "errors",
            f"🔴 <b>ry-hl: {len(errs)} righe ERROR/CRITICAL</b>\n<code>{esc(sample)}</code>",
        )

    # Il warning di trailing warmup è normale per qualche minuto dopo un fill o un
    # restart: allarme solo se il blocco PERSISTE (l'incidente vero del 28/07 è durato
    # 27 ore). Serve quindi che il pattern sia presente da almeno BLOCK_PERSIST_MIN.
    blocked = [l for l in lines if any(p in l for p in BLOCK_PATTERNS)]
    if blocked:
        first = state.get("block_first_ts")
        if not first:
            state["block_first_ts"] = first = time.time()
        span_min = (time.time() - first) / 60
        if span_min >= BLOCK_PERSIST_MIN:
            sample = "\n".join(l[:220] for l in blocked[:2])
            alert(
                state,
                "trailing_blocked",
                f"🟠 <b>ry-hl: trading bloccato da {span_min:.0f} min</b> "
                f"({len(blocked)} righe in questo giro)\n<code>{esc(sample)}</code>\n"
                "È la firma del bug fill same-ms / trailing bloccato.",
            )
    else:
        state["block_first_ts"] = None

    # err=N/10 è un contatore su una soglia di 10: 1-2 errori transitori sono rumore.
    for l in reversed(lines):
        m = HEALTH_RE.search(l)
        if m:
            if int(m.group(1)) >= ERR_COUNTER_MIN:
                alert(
                    state,
                    "err_counter",
                    f"🟠 <b>ry-hl: contatore errori a {m.group(1)}/{m.group(2)}</b>\n"
                    f"<code>{esc(l[:220])}</code>",
                )
            break

    STATE.write_text(json.dumps(state))


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def summary() -> str:
    """Riga di stato per il body del ping quando va tutto bene."""
    try:
        with open(os.path.realpath(LOG), "rb") as f:
            f.seek(max(0, os.path.getsize(os.path.realpath(LOG)) - 65536))
            chunk = f.read().decode(errors="replace")
        for line in reversed(chunk.splitlines()):
            if "[health]" in line:
                return line[-200:]
    except OSError:
        pass
    return "nessuna riga [health] recente nel log"


if __name__ == "__main__":
    main()
    ok = not PROBLEMS
    head = "passivbot ry-hl (amazon) — " + ("OK" if ok else "ANOMALIA")
    body = "\n".join([head, *(f"[!] {p}" for p in PROBLEMS), summary()])
    hc_ping(ok, body)
