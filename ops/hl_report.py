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
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path.home() / "watchdog"
CREDS = BASE / "telegram.json"
STATE = BASE / "trades_state.json"
LOGDIR = Path("/opt/passivbot-hl/logs")
LOG_GLOB = str(LOGDIR / "*config_hl_4rsi.json.log")

POS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}):\d{2}Z.*\[pos\]\s+(new|added|reduced|closed)\s+HYPE\s+"
    r"long\s+[\d.]+ @ [\d.]+\s+-> ([\d.]+) @ ([\d.]+)"
)
FILL_RE = re.compile(r"\[fill\].*HYPE long (\S+) ([+\-\d.]+) @ ([\d.]+)(?:, pnl=([+\-\d.]+))?")
BAL_RE = re.compile(r"\[health\].*bal=([\d.]+)")


def send(text: str) -> None:
    creds = json.loads(CREDS.read_text())
    data = urllib.parse.urlencode(
        {"chat_id": creds["chat_id"], "text": text, "parse_mode": "HTML"}
    ).encode()
    url = "https://api.telegram.org/bot" + creds["token"] + "/sendMessage"
    with urllib.request.urlopen(url, data=data, timeout=30) as r:
        r.read()


def bot_alive() -> bool:
    r = subprocess.run(
        ["pgrep", "-f", r"python src/main\.py configs/live/config_hl_4rsi\.json"],
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
    balance = None
    for line in reversed(lines):
        b = BAL_RE.search(line)
        if b:
            balance = b.group(1)
            break

    for ev in fresh:
        if ev["kind"] == "new":
            steps = 1
            send(
                f"📈 <b>ry-hl aperta</b> · {ev['size']:.2f} HYPE @ {ev['price']:.3f}"
                f" · {ev['time']}"
            )
        elif ev["kind"] in ("added", "reduced"):
            steps += 1  # niente messaggio: si riassume alla chiusura
        elif ev["kind"] == "closed":
            # Sommo solo i fill di QUESTA chiusura. Una chiusura puo' essere
            # spezzata su piu' fill e scavallare il minuto (visto il 20/08:
            # 02:30 e 02:31), quindi prendo una finestra di 3 minuti che
            # finisce sull'evento. Scorrere all'indietro "fino a un timestamp
            # minore" sommava anche le chiusure precedenti dello stesso
            # giorno: +44,13 dove il fill vero era +25,78.
            end_min = int(ev["time"][:2]) * 60 + int(ev["time"][3:])
            pnl = 0.0
            for line in lines:
                if not line.startswith(ev["day"]) or "[fill]" not in line:
                    continue
                if "close" not in line:
                    continue
                hhmm = line.split("T")[1][:5]
                fill_min = int(hhmm[:2]) * 60 + int(hhmm[3:])
                if not (end_min - 3 <= fill_min <= end_min):
                    continue
                m = FILL_RE.search(line)
                if m and m.group(4):
                    pnl += float(m.group(4))
            grad = f" · {steps} gradini" if steps > 1 else ""
            bal = f" · cassa {balance}" if balance else ""
            send(
                f"✅ <b>ry-hl chiusa</b> · <b>{pnl:+.2f}</b> USDT{grad}{bal}"
                f" · {ev['time']}"
            )
            steps = 0

    if fresh:
        state["last_key"] = fresh[-1]["key"]
    state["steps"] = steps
    STATE.write_text(json.dumps(state))

    if not bot_alive():
        send("🔴 <b>ry-hl: processo assente</b> — se ne occupa il watchdog, ma tienilo d'occhio.")


if __name__ == "__main__":
    main()
