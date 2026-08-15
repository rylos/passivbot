#!/usr/bin/env python3
"""Report periodico del bot live ry-hl su Telegram (Claude RyLoS Bot).

Complementare al watchdog: quello avvisa quando qualcosa ROMPE (via
healthchecks.io), questo dice periodicamente "sto vivo e sto facendo questo".
Nato per il periodo di ferie di Marco (15-27 agosto 2026), quando nessuno
guarda i log e il silenzio di healthchecks non e' distinguibile da un
watchdog morto senza aprire il telefono.

Sola lettura: non riavvia e non tocca il bot. Cron 2 volte al giorno.
"""
from __future__ import annotations

import calendar
import glob
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path.home() / "watchdog"
CREDS = BASE / "telegram.json"
LOGDIR = Path("/opt/passivbot-hl/logs")
LOG_GLOB = str(LOGDIR / "*config_hl_4rsi.json.log")

TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z")
HEALTH_RE = re.compile(
    r"\[health\] up=(\S+) loop=(\S+) pos=(\S+) bal=([\d.]+) \S+ ord=(\S+) fills=(\d+) err=(\d+)/(\d+)"
)


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send(text: str) -> None:
    creds = json.loads(CREDS.read_text())
    data = urllib.parse.urlencode(
        {"chat_id": creds["chat_id"], "text": text, "parse_mode": "HTML"}
    ).encode()
    url = "https://api.telegram.org/bot" + creds["token"] + "/sendMessage"
    with urllib.request.urlopen(url, data=data, timeout=30) as r:
        r.read()


def bot_pid() -> str | None:
    r = subprocess.run(
        ["pgrep", "-f", r"python src/main\.py configs/live/config_hl_4rsi\.json"],
        capture_output=True,
        text=True,
    )
    pids = [p for p in r.stdout.split() if p.strip()]
    return pids[0] if pids else None


def current_log() -> str | None:
    files = glob.glob(LOG_GLOB)
    return max(files, key=os.path.getmtime) if files else None


def ts_of(line: str) -> float | None:
    m = TS_RE.match(line)
    return calendar.timegm(time.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S")) if m else None


def main() -> None:
    pid = bot_pid()
    path = current_log()
    if path is None:
        send("🔴 <b>ry-hl</b>: nessun log trovato in /opt/passivbot-hl/logs.")
        return

    # Ultime 24h di log: bastano gli ultimi MB, il log cresce ~300 KB/giorno.
    with open(path, "rb") as f:
        f.seek(max(0, os.path.getsize(path) - 3_000_000))
        lines = f.read().decode(errors="replace").splitlines()

    cutoff = time.time() - 24 * 3600
    recent = [l for l in lines if (t := ts_of(l)) is not None and t >= cutoff]

    health = None
    for l in reversed(lines):
        m = HEALTH_RE.search(l)
        if m:
            health = m
            break

    # Gli stessi filtri del watchdog: il ciclo degraded e il backoff sono
    # rumore previsto, non guasti.
    errs = [
        l
        for l in recent
        if (" ERROR " in l or " CRITICAL " in l or "Traceback (most recent" in l)
        and "[cycle] degraded" not in l
        and "action=record_error_restart_backoff" not in l
    ]
    restarts = [l for l in recent if "restarting bot..." in l]
    fills = [l for l in recent if "[fill]" in l or " filled " in l.lower()]

    last_ts = next((t for l in reversed(lines) if (t := ts_of(l)) is not None), None)
    age_min = (time.time() - last_ts) / 60 if last_ts else None

    # Il giallo deve significare "guarda ADESSO", non "9 ore fa l'API di
    # Hyperliquid e' stata giu' e il bot si e' ripreso da solo". Quindi pesano
    # solo gli errori delle ultime 2h; quelli delle 24h restano come contatore
    # informativo. Idem per i riavvii interni: qualcuno e' fisiologico, una
    # raffica no.
    recent_cut = time.time() - 2 * 3600
    errs_2h = [l for l in errs if (t := ts_of(l)) is not None and t >= recent_cut]
    ok = (
        pid is not None
        and not errs_2h
        and len(restarts) < 5
        and (age_min is not None and age_min < 35)
    )
    head = "🟢 <b>ry-hl OK</b>" if ok else "🟠 <b>ry-hl da guardare</b>"

    rows = [head]
    rows.append(f"pid: {pid or '<b>ASSENTE</b>'}")
    if health:
        rows.append(
            f"up={health.group(1)} pos={health.group(3)} bal={health.group(4)} USDC "
            f"ord={health.group(5)} err={health.group(7)}/{health.group(8)}"
        )
    if age_min is not None:
        rows.append(f"ultima riga di log: {age_min:.0f} min fa")
    rows.append(
        f"24h: {len(errs)} errori ({len(errs_2h)} nelle ultime 2h), "
        f"{len(restarts)} riavvii interni, {len(fills)} fill"
    )
    if errs_2h:
        rows.append("<code>" + esc(errs_2h[-1][:200]) + "</code>")

    send("\n".join(rows))


if __name__ == "__main__":
    main()
