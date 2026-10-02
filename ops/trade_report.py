#!/usr/bin/env python3
"""Notifica Telegram sui trade di ry-hl e ry-bybit (Claude RyLoS Bot).

Nato come hl_report.py per il solo ry-hl; rinominato trade_report.py il
2026-09-15 quando ormai serviva entrambe le istanze.

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
from datetime import datetime, timedelta, timezone
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

# Istanza dal primo argomento (`trade_report.py bybit`); default "hl" per non
# toccare il cron storico. Stato separato per istanza.
PROFILES = {
    "hl": dict(name="ry-hl", logdir="/opt/passivbot-hl/logs", config="config_hl_4rsi.json", fills="/opt/passivbot-hl/caches/fill_events/hyperliquid/hyperliquid_vault", monitor="/opt/passivbot-hl/monitor/hyperliquid/hyperliquid_vault", state="trades_state.json", ccy="USDC", extra_creds=["telegram_rylos_group.json"]),
    "bybit": dict(name="ry-bybit", logdir="/opt/passivbot-bybit/logs", config="config_bybit_4rsi.json", fills="/opt/passivbot-bybit/caches/fill_events/bybit/bybit_02", monitor="/opt/passivbot-bybit/monitor/bybit/bybit_02", state="trades_state_bybit.json", ccy="USDT", extra_creds=[]),
}
INSTANCE = sys.argv[1] if len(sys.argv) > 1 else "hl"
P = PROFILES[INSTANCE]
NAME = P["name"]
CCY = P["ccy"]
# Coin letto dalla config live (approved_coins.long[0]): cambiare coin sul bot
# (es. HYPE -> POPCAT del 25/09) non richiede di toccare questo script.
try:
    COIN = json.load(open(Path(P["logdir"]).parent / "configs/live" / P["config"]))["live"]["approved_coins"]["long"][0]
except Exception:
    COIN = "HYPE"


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

# Il wallet si legge dallo stato che il bot riscrive ogni minuto
# (`monitor/.../state.latest.json`, account.balance_raw): dal merge upstream
# del 30/09 le righe [health] bal= e [balance] equity= non ci sono piu'. Alla
# chiusura vale solo uno stato scritto DOPO il fill, altrimenti e' il saldo
# PRE-chiusura (28/08: 12290.05 contro 12521.68 reali) e si riprova al giro dopo.
ROCKET_PCT = 0.005
# Oltre questo numero di eventi in un log nuovo non si rigioca (raffica).
MAX_REPLAY = 10


def _tg(creds: dict, method: str, params: dict) -> dict:
    data = urllib.parse.urlencode({"chat_id": creds["chat_id"], **params}).encode()
    url = "https://api.telegram.org/bot" + creds["token"] + "/" + method
    with urllib.request.urlopen(url, data=data, timeout=30) as r:
        return json.loads(r.read() or b"{}")


def _targets() -> list:
    # Destinatario principale (Claude RyLoS Bot -> Marco) + eventuali extra del
    # profilo (per hl: @freqtradehl_bot -> gruppo RyLoS-Trading, richiesto da
    # Marco il 2026-09-10). Un errore su un destinatario non blocca gli altri.
    return [CREDS] + [BASE / f for f in P.get("extra_creds", [])]


def send(text: str) -> list:
    """Manda a tutti i destinatari; ritorna [[file credenziali, message_id]]."""
    sent = []
    for path in _targets():
        try:
            res = _tg(json.loads(path.read_text()), "sendMessage", {"text": text, "parse_mode": "HTML"})
            mid = (res.get("result") or {}).get("message_id")
            if mid is not None:
                sent.append([path.name, mid])
        except Exception as e:  # noqa: BLE001
            print(f"send fallito su {path.name}: {e}", file=sys.stderr)
    return sent


def edit(msgs: list, text: str) -> None:
    """Riscrive i messaggi gia' mandati (avanzamento del fill di un ordine)."""
    for name, mid in msgs or []:
        try:
            _tg(json.loads((BASE / name).read_text()), "editMessageText",
                {"message_id": mid, "text": text, "parse_mode": "HTML"})
        except Exception as e:  # noqa: BLE001
            if "not modified" not in str(e):
                print(f"edit fallito su {name}: {e}", file=sys.stderr)


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


def current_wallet() -> tuple:
    """(saldo, istante UTC naive della scrittura) dallo stato del bot."""
    try:
        path = Path(P["monitor"]) / "state.latest.json"
        bal = float(json.loads(path.read_text())["account"]["balance_raw"])
        at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(tzinfo=None)
        return bal, at
    except Exception:  # noqa: BLE001
        return None, None


def load_fills(days: int = 3) -> list:
    """Fill degli ultimi `days` giorni UTC dalla cache del bot, in ordine."""
    out = []
    today = datetime.now(timezone.utc).date()
    for i in range(days - 1, -1, -1):
        path = Path(P["fills"]) / f"{today - timedelta(days=i)}.json"
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        out += [fl for fl in data if str(fl.get("symbol", "")).startswith(COIN + "/")
                and str(fl.get("position_side", "long")) == "long"]
    return sorted(out, key=lambda fl: (fl["datetime"], str(fl["id"])))


# Un ordine di ingresso puo' essere eseguito a piu' pezzi (fill parziali).
# L'avviso parte al primo pezzo con la % eseguita dell'ordine e lo stesso
# messaggio viene modificato a ogni pezzo successivo fino al 100% (Marco,
# 02/10). Quantita' dell'ordine: Bybit la scrive nel fill (orderQty); per HL
# si prende dall'ultima riga "[order] post" del log con stesso tipo e prezzo.
POST_RE = re.compile(r"(buy|sell) (long|short) ([\d.]+)@([\d.]+) (\S+)")


def _order_qty_raw(fl: dict) -> float | None:
    for raw in fl.get("raw") or []:
        info = ((raw or {}).get("data") or {}).get("info") or {}
        if "orderQty" in info:
            try:
                return float(info["orderQty"])
            except (TypeError, ValueError):
                return None
    return None


def _order_qty_log(lines: list, pb_type: str, price: float, ts: str) -> float | None:
    qty = None
    for ln in lines:
        if ln[:19] > ts:
            break
        if "[order]" not in ln or " post " not in ln or pb_type not in ln:
            continue
        for m in POST_RE.finditer(ln):
            if m.group(5) == pb_type and abs(float(m.group(4)) - price) <= 1e-9 * max(price, 1.0):
                qty = float(m.group(3))
    return qty


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

    # Eventi dalla cache dei fill del bot (`caches/fill_events/...`): ogni
    # fill porta la posizione DOPO il fill (psize/pprice), pnl e fee. Fino al
    # 30/09 si leggevano le righe "[pos] new/added/reduced/closed" del log, che
    # il merge upstream di quel giorno (84cae05ab) ha tolto: da allora nessun
    # messaggio partiva (aperture e chiusure del 30/09 e del 01/10 perse).
    fills = load_fills()
    events = []
    for fl in fills:
        qty, psize = float(fl["qty"]), float(fl.get("psize") or 0.0)
        if qty > 0:
            kind = "new" if abs(psize - qty) < 1e-9 else "added"
        else:
            kind = "closed" if abs(psize) < 1e-9 else "reduced"
        ts = fl["datetime"][:19]
        events.append(
            {
                "key": f"{ts}|{fl['id']}",
                "ts": ts,
                "day": ts[:10],
                "time": ts[11:16],
                "kind": kind,
                "size": psize,
                "price": float(fl.get("pprice") or fl["price"]),
                "order": str(fl.get("client_order_id") or ""),
                "filled": abs(qty),
                "fill_price": float(fl["price"]),
                "pb_type": str(fl.get("pb_order_type") or ""),
                "order_qty": _order_qty_raw(fl),
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
    elif (
        events[0]["key"].split("|")[0] > last_key.split("|")[0]
        and len(events) <= MAX_REPLAY
    ):
        # Log nuovo dopo un riavvio del bot: last_key sta nel file vecchio e
        # tutti gli eventi qui sono successivi. Il silenzio perdeva il primo
        # trade dopo ogni riavvio (15/09: aperture delle 00:35 mai notificate
        # su entrambi i bot). Pochi eventi, tutti nuovi: si mandano.
        fresh = events
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

    # Un ordine eseguito a pezzi (fill parziali, es. Bybit 02/10 17:25: 0,78 +
    # 7,29 dello stesso entry_initial) e' un solo gradino: i pezzi consecutivi
    # dello stesso ordine diventano un evento con la posizione dopo l'ultimo,
    # e un pezzo arrivato in un giro successivo non conta come gradino nuovo.
    merged = []
    for ev in fresh:
        prev = merged[-1] if merged else None
        if (
            prev is not None
            and ev["order"]
            and ev["order"] == prev["order"]
            and ev["kind"] in ("new", "added")
            and prev["kind"] in ("new", "added")
        ):
            prev.update(key=ev["key"], ts=ev["ts"], day=ev["day"], time=ev["time"],
                        size=ev["size"], price=ev["price"],
                        filled=prev["filled"] + ev["filled"],
                        order_qty=prev["order_qty"] or ev["order_qty"])
        else:
            merged.append(dict(ev))
    fresh = merged
    for ev in fresh:
        if ev["kind"] in ("new", "added") and ev["order_qty"] is None:
            ev["order_qty"] = _order_qty_log(lines, ev["pb_type"], ev["fill_price"], ev["ts"])
    inc = state.get("inc") or {}

    def inc_text(label: str, ev: dict, filled: float, order_qty, bal: str) -> str:
        pct = ""
        if order_qty:
            pct = f" · fill {min(filled / order_qty, 1.0) * 100:.0f}%"
        head = f"📈 <b>{NAME} aperta</b> · " if label == "aperta" else f"➕ <b>{NAME} {label}</b> · pos "
        return (
            f"{head}{ev['size']:.2f} {COIN} @ {ev['price']:.5g}"
            f" · {ev['size'] * ev['price']:,.0f} {CCY}{pct}{bal}"
            f" · {rome(ev['day'], ev['time'])}"
        )

    steps = state.get("steps", 0)
    wallet_now, wallet_at = current_wallet()

    opened_at = state.get("opened_at")

    pending_step = None
    deferred = False
    for ev in fresh:
        if ev["kind"] == "added" and ev["order"] and ev["order"] == inc.get("order"):
            # altro pezzo di un ordine gia' notificato: stesso gradino, si
            # modifica il messaggio con la posizione e la % eseguita
            inc["filled"] = inc.get("filled", 0.0) + ev["filled"]
            inc["order_qty"] = inc.get("order_qty") or ev["order_qty"]
            edit(inc.get("msgs"), inc_text(inc["label"], ev, inc["filled"], inc["order_qty"], inc.get("bal", "")))
            continue
        if ev["kind"] == "new":
            pending_step = None
            steps = 1
            opened_at = ev["ts"]
            # All'apertura il saldo realizzato non cambia: vale l'ultima riga
            # [health]/[balance] prima del fill.
            bal = f" · wallet {wallet_now:.2f}" if wallet_now else ""
            msgs = send(inc_text("aperta", ev, ev["filled"], ev["order_qty"], bal))
            inc = {"order": ev["order"], "filled": ev["filled"], "order_qty": ev["order_qty"],
                   "label": "aperta", "bal": bal, "msgs": msgs}
        elif ev["kind"] == "added":
            steps += 1
            # Richiesto da Marco il 10/09: un avviso a ogni gradino in piu',
            # con la posizione aggregata. Se in un giro (5 min) arrivano piu'
            # gradini, vale solo l'ultimo: si manda dopo il ciclo.
            pending_step = ev
        elif ev["kind"] == "reduced":
            pass  # uscita parziale: non e' un gradino, si riassume alla chiusura
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
            # Finestra della posizione: dall'apertura (stato, o l'ultimo "new"
            # nella cache se lo stato non c'e') alla chiusura, al secondo.
            # PnL e fee dalla cache: esatti, senza aspettare la riga [fill].
            end = ev["ts"]
            start = opened_at or next(
                (e["ts"] for e in reversed(events) if e["kind"] == "new" and e["ts"] <= end), end
            )
            pnl = 0.0
            n_fills = 0
            n_manual = 0
            for fl in fills:
                ts = fl["datetime"][:19]
                if not (start <= ts <= end):
                    continue
                pnl += float(fl.get("fee_paid") or 0.0)  # fee con segno, ingressi compresi
                # anche i fill "unknown": una chiusura fatta a mano sull'exchange
                # (29/09); per un long ogni riduzione ha qty negativa
                if float(fl["qty"]) < 0:
                    pnl += float(fl.get("pnl") or 0.0)
                    n_fills += 1
                    if not str(fl.get("pb_order_type") or "").startswith("close"):
                        n_manual += 1
            opened_at = None
            grad = f" · {steps} gradini" if steps > 1 else ""
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            close_at = datetime.strptime(end, "%Y-%m-%dT%H:%M:%S")
            if (wallet_at is None or wallet_at <= close_at) and now <= close_at + timedelta(minutes=5):
                # stato non ancora riscritto dopo il fill: riprovo al giro dopo
                deferred = True
                break
            wallet = wallet_now if wallet_at and wallet_at > close_at else None
            bal = f" · wallet {wallet:.2f}" if wallet else ""
            # Missile sopra ROCKET_PCT del wallet (0.5%, scelto da Marco il
            # 2026-09-15 sui cicli reali: ~1 su 8). Soglia relativa, non in
            # valuta, cosi' vale per entrambi i bot e segue il wallet.
            # Richiesto da Marco il 29/09: le chiusure fatte a mano si distinguono
            # (fuori dal confronto live/backtest)
            if n_manual and n_manual == n_fills:
                manual = " <b>a mano</b>"
            elif n_manual:
                manual = " (in parte <b>a mano</b>)"
            else:
                manual = ""
            if pnl < 0:
                icon = "❌"
            elif wallet and pnl >= wallet * ROCKET_PCT:
                icon = "🚀"
            else:
                icon = "✅"
            send(
                f"{icon} <b>{NAME} chiusa</b>{manual} · <b>{pnl:+.2f}</b> {CCY}{grad}{bal}"
                f" · {rome(ev['day'], ev['time'])}"
            )
            steps = 0
            pending_step = None
            inc = {}

    if pending_step is not None:
        ev = pending_step
        label = f"gradino {steps}"
        msgs = send(inc_text(label, ev, ev["filled"], ev["order_qty"], ""))
        inc = {"order": ev["order"], "filled": ev["filled"], "order_qty": ev["order_qty"],
               "label": label, "bal": "", "msgs": msgs}

    if deferred:
        # l'evento "closed" non e' stato processato: il prossimo giro riparte
        # dall'evento precedente (o resta fermo se era il primo)
        i = next(i for i, e in enumerate(fresh) if e["kind"] == "closed" and e["key"] > (state.get("last_key") or ""))
        if i > 0:
            state["last_key"] = fresh[i - 1]["key"]
    elif fresh:
        state["last_key"] = fresh[-1]["key"]
    state["steps"] = steps
    state["opened_at"] = opened_at
    state["inc"] = inc
    state.pop("last_inc_order", None)
    STATE.write_text(json.dumps(state))

    if not bot_alive():
        send(f"🔴 <b>{NAME}: processo assente</b> — se ne occupa il watchdog, ma tienilo d'occhio.")


if __name__ == "__main__":
    main()
