#!/usr/bin/env python3
"""Notifica Telegram sui trade di ry-hl (Claude RyLoS Bot).

Nato come report a orari fissi per le ferie (15-27 agosto 2026); dal 27/08 e'
event-driven, perche' due messaggi al giorno che dicono sempre la stessa cosa
si smettono di leggere. Ora parla solo quando **cambia lo stato della
posizione**: apertura e chiusura. I gradini intermedi della griglia non
generano messaggi — finirebbero per essere il grosso del traffico — ma vengono
contati e riassunti alla chiusura.

Sola lettura: non riavvia e non tocca il bot. Il guasto resta compito del
watchdog (`watchdog.py`, cron ogni 10 min, con healthchecks come dead man
switch); questo file si occupa solo di raccontare i trade.
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

# Istanza dal primo argomento (`hl_report.py bybit`); default "hl" per non
# toccare il cron storico. Stato separato per istanza.
PROFILES = {
    "hl": dict(name="ry-hl", logdir="/opt/passivbot-hl/logs", config="config_hl_4rsi.json", state="trades_state.json", ccy="USDC", extra_creds=["telegram_rylos_group.json"]),
    "bybit": dict(name="ry-bybit", logdir="/opt/passivbot-bybit/logs", config="config_bybit_4rsi.json", state="trades_state_bybit.json", ccy="USDT", extra_creds=[]),
}
INSTANCE = sys.argv[1] if len(sys.argv) > 1 else "hl"
P = PROFILES[INSTANCE]
NAME = P["name"]
CCY = P["ccy"]


def rome(day: str, hhmm: str) -> str:
    """Il log e' in UTC; Marco legge in Europe/Rome (07/09: il messaggio
    diceva 23:15 per un fill delle 01:15)."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    dt = datetime.strptime(f"{day}T{hhmm}", "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo("Europe/Rome")).strftime("%H:%M")

BASE = Path.home() / "watchdog"
CREDS = BASE / "telegram.json"
STATE = BASE / P["state"]
LOGDIR = Path(P["logdir"])
LOG_GLOB = str(LOGDIR / f"*{P['config']}.log")

POS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}):\d{2}Z.*\[pos\]\s+(new|added|reduced|closed)\s+HYPE\s+"
    r"long\s+[\d.]+ @ [\d.]+\s+-> ([\d.]+) @ ([\d.]+)"
)
FILL_RE = re.compile(r"\[fill\].*HYPE long (\S+) ([+\-\d.]+) @ ([\d.]+)(?:, pnl=([+\-\d.]+))?")
# Il wallet va letto dalla riga piu' recente fra due sorgenti: [health] esce
# ogni ~15 minuti, quindi alla chiusura di un trade e' quasi sempre vecchia e
# riporta il saldo PRE-chiusura (visto il 28/08: messaggio con 12290.05 quando
# il wallet reale era gia' 12521.68). [balance] invece viene emessa nello
# stesso secondo del fill che muove il saldo: e' quella che vale.
BAL_RE = re.compile(r"\[health\].*bal=([\d.]+)|\[balance\].*equity=([\d.]+)")


def _send_one(creds: dict, text: str) -> None:
    data = urllib.parse.urlencode(
        {"chat_id": creds["chat_id"], "text": text, "parse_mode": "HTML"}
    ).encode()
    url = "https://api.telegram.org/bot" + creds["token"] + "/sendMessage"
    with urllib.request.urlopen(url, data=data, timeout=30) as r:
        r.read()


def send(text: str) -> None:
    # Destinatario principale (Claude RyLoS Bot -> Marco) + eventuali extra del
    # profilo (per hl: @freqtradehl_bot -> gruppo RyLoS-Trading, richiesto da
    # Marco il 2026-09-10). Un errore su un destinatario non blocca gli altri.
    targets = [CREDS] + [BASE / f for f in P.get("extra_creds", [])]
    for path in targets:
        try:
            _send_one(json.loads(path.read_text()), text)
        except Exception as e:  # noqa: BLE001
            print(f"send fallito su {path.name}: {e}", file=sys.stderr)


def bot_alive() -> bool:
    r = subprocess.run(
        ["pgrep", "-f", r"python src/main\.py configs/live/" + re.escape(P["config"])],
        capture_output=True,
        text=True,
    )
    return bool(r.stdout.strip())


def current_log() -> str | None:
    files = glob.glob(LOG_GLOB)
    return max(files, key=os.path.getmtime) if files else None


def load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text())
        except json.JSONDecodeError:
            pass
    return {}


def main() -> None:
    path = current_log()
    if path is None:
        return
    state = load_state()

    # Bastano gli ultimi MB: il log cresce ~300 KB/giorno e qui interessa
    # solo cosa e' successo dall'ultimo giro.
    with open(path, "rb") as f:
        f.seek(max(0, os.path.getsize(path) - 2_000_000))
        lines = f.read().decode(errors="replace").splitlines()

    events = []
    for line in lines:
        m = POS_RE.match(line)
        if m:
            events.append(
                {
                    "key": f"{m.group(1)}T{m.group(2)}|{m.group(3)}|{m.group(4)}",
                    "day": m.group(1),
                    "time": m.group(2),
                    "kind": m.group(3),
                    "size": float(m.group(4)),
                    "price": float(m.group(5)),
                }
            )
    if not events:
        return

    last_key = state.get("last_key")
    # Primo giro dopo l'installazione: registra il presente senza inondare
    # la chat con lo storico.
    if last_key is None:
        state["last_key"] = events[-1]["key"]
        state["steps"] = 0
        STATE.write_text(json.dumps(state))
        return

    known = {e["key"] for e in events}
    if last_key in known:
        idx = next(i for i, e in enumerate(events) if e["key"] == last_key)
        fresh = events[idx + 1 :]
    else:
        # last_key fuori dal buffer (log ruotato, o script fermo abbastanza a
        # lungo da farlo scorrere via). Rigiocare tutto manderebbe una raffica
        # di messaggi su trade vecchi: mi risincronizzo in silenzio, che e' il
        # comportamento sicuro. Il rischio e' perdere la notifica di un trade,
        # non inondare la chat — e i trade restano nel log.
        state["last_key"] = events[-1]["key"]
        state["steps"] = 0
        STATE.write_text(json.dumps(state))
        return

    steps = state.get("steps", 0)
    # (stamp, saldo) di ogni riga [health]/[balance]: alla chiusura serve la
    # prima riga DOPO il fill, non l'ultima del log (07/09: wallet 12700.81
    # da un [health] di 16 secondi prima del fill, reale 12713.84).
    bal_lines = []
    for line in lines:
        b = BAL_RE.search(line)
        if b:
            bal_lines.append((line[:16], float(b.group(1) or b.group(2))))

    opened_at = state.get("opened_at")

    for ev in fresh:
        if ev["kind"] == "new":
            steps = 1
            opened_at = f"{ev['day']}T{ev['time']}"
            send(
                f"📈 <b>{NAME} aperta</b> · {ev['size']:.2f} HYPE @ {ev['price']:.3f}"
                f" · {rome(ev['day'], ev['time'])}"
            )
        elif ev["kind"] in ("added", "reduced"):
            steps += 1  # niente messaggio: si riassume alla chiusura
        elif ev["kind"] == "closed":
            # Il PnL della posizione e' la somma dei fill di chiusura da
            # quando e' stata aperta a quando si e' chiusa. Due errori gia'
            # pagati su questa riga:
            #  - scorrere all'indietro "fino a un timestamp minore" sommava
            #    anche le chiusure PRECEDENTI dello stesso giorno: +44,13
            #    dove il fill vero era +25,78 (20/08);
            #  - la finestra di 3 minuti che chiudeva il buco sopra escludeva
            #    pero' le riduzioni intermedie della griglia di chiusura:
            #    +237,81 dove la posizione aveva reso +246,57 (28/08).
            # L'istante di apertura e' in stato, quindi la finestra e' esatta.
            # Senza (risincronizzazione) resto sui 3 minuti prudenziali.
            start = opened_at or f"{ev['day']}T{ev['time']}"
            end = f"{ev['day']}T{ev['time']}"
            if opened_at is None:
                end_min = int(ev["time"][:2]) * 60 + int(ev["time"][3:])
                start = f"{ev['day']}T{(end_min - 3) // 60:02d}:{(end_min - 3) % 60:02d}"
            pnl = 0.0
            for line in lines:
                if "[fill]" not in line or "close" not in line:
                    continue
                stamp = line[:16]  # YYYY-MM-DDTHH:MM
                if not (start <= stamp <= end):
                    continue
                m = FILL_RE.search(line)
                if m and m.group(4):
                    pnl += float(m.group(4))
            opened_at = None
            grad = f" · {steps} gradini" if steps > 1 else ""
            after = [v for st, v in bal_lines if st >= end]
            before = [v for st, v in bal_lines if st < end]
            if after:
                bal = f" · wallet {after[0]:.2f}"
            elif before:
                bal = f" · wallet ≈{before[-1] + pnl:.2f}"
            else:
                bal = ""
            send(
                f"✅ <b>{NAME} chiusa</b> · <b>{pnl:+.2f}</b> {CCY}{grad}{bal}"
                f" · {rome(ev['day'], ev['time'])}"
            )
            steps = 0

    if fresh:
        state["last_key"] = fresh[-1]["key"]
    state["steps"] = steps
    state["opened_at"] = opened_at
    STATE.write_text(json.dumps(state))

    if not bot_alive():
        send(f"🔴 <b>{NAME}: processo assente</b> — se ne occupa il watchdog, ma tienilo d'occhio.")


if __name__ == "__main__":
    main()
