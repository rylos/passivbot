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


def _raw_after_size(fl: dict) -> float | None:
    """HL: posizione dopo il fill dai dati dell'exchange (startPosition + sz),
    esatta anche quando la psize della cache non e' ancora ricalcolata."""
    for raw in fl.get("raw") or []:
        info = ((raw or {}).get("data") or {}).get("info") or {}
        if "startPosition" in info and "sz" in info and info.get("side") in ("A", "B"):
            try:
                start, sz = float(info["startPosition"]), float(info["sz"])
            except (TypeError, ValueError):
                return None
            return abs(start + (sz if info["side"] == "B" else -sz))
    return None


EXIT_STALL_MIN = 10


def _order_cancelled_log(lines: list, pb_type: str, price: float, after: str) -> bool:
    """True se dopo `after` il bot ha cancellato l'ordine (stesso tipo e prezzo)."""
    for ln in lines:
        if ln[:19] <= after or "[order] cancel" not in ln or pb_type not in ln:
            continue
        for m in POST_RE.finditer(ln):
            if m.group(5) == pb_type and abs(float(m.group(4)) - price) <= 1e-9 * max(price, 1.0):
                return True
    return False


def _order_qty_log(lines: list, pb_type: str, price: float, ts: str, since: str = "") -> float | None:
    """Quantita' dall'ultima riga "post" con stesso tipo e prezzo fra `since`
    (chiusura precedente: un ordine di ingresso non puo' essere piu' vecchio)
    e il fill."""
    qty = None
    for ln in lines:
        if ln[:19] > ts:
            break
        if ln[:19] < since:
            continue
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
        raw_size = _raw_after_size(fl)
        if raw_size is not None:
            psize = raw_size
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
                "value": abs(qty) * float(fl["price"]),
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

    # Ordini eseguiti a pezzi (fill parziali, es. Bybit 02/10 17:25: 0,78 +
    # 7,29 dello stesso entry_initial). Ogni ordine di ingresso e' UN avviso
    # (apertura o gradino) che parte al primo pezzo con la % eseguita e viene
    # modificato a ogni pezzo successivo fino al 100%, anche se i pezzi di
    # ordini diversi si alternano o arrivano in giri diversi (Marco, 02/10).
    # I pezzi consecutivi dello stesso ordine nello stesso giro si uniscono.
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
        elif (
            prev is not None
            and ev["kind"] in ("reduced", "closed")
            and prev["kind"] == "reduced"
        ):
            # pezzi di uscita consecutivi nello stesso giro: un solo evento
            prev.update(key=ev["key"], ts=ev["ts"], day=ev["day"], time=ev["time"],
                        size=ev["size"], kind=ev["kind"],
                        value=prev["value"] + ev["value"],
                        filled=prev["filled"] + ev["filled"])
        else:
            merged.append(dict(ev))
    fresh = merged
    # Ingresso con la posizione ancora a zero nella cache (psize non ancora
    # ricalcolata dal bot): si riprende al giro dopo, al massimo per 10 min.
    for i, ev in enumerate(fresh):
        if ev["kind"] in ("new", "added") and ev["size"] <= 0.0:
            age = (datetime.now(timezone.utc).replace(tzinfo=None)
                   - datetime.strptime(ev["ts"], "%Y-%m-%dT%H:%M:%S")).total_seconds()
            if age < 600:
                fresh = fresh[:i]
                break
    for ev in fresh:
        if ev["kind"] in ("new", "added") and ev["order_qty"] is None:
            since = max((e["ts"] for e in events if e["kind"] == "closed" and e["ts"] <= ev["ts"]), default="")
            ev["order_qty"] = _order_qty_log(lines, ev["pb_type"], ev["fill_price"], ev["ts"], since)
    # ordini di ingresso della posizione aperta: {client_order_id: avviso}
    orders = state.get("orders") or {}
    # uscita in corso (Marco, 02/10: come per gli ingressi, un avviso al primo
    # pezzo con la % venduta, modificato a ogni pezzo e, a posizione chiusa,
    # trasformato nel messaggio finale col PnL)
    exit_ = state.get("exit") or {}

    def exit_text(x: dict, ev: dict) -> str:
        x["snap"] = {k: ev[k] for k in ("size", "day", "time")}
        x["last_ts"] = ev.get("ts", x.get("last_ts", ""))
        pct = min(x["sold"] / x["start"], 1.0) * 100 if x["start"] > 0 else 0.0
        avg = x["value"] / x["sold"] if x["sold"] > 0 else 0.0
        if x.get("ended"):
            head = f"📉 <b>{NAME} uscita parziale</b> (finita, poi nuovo ingresso)"
        elif x.get("stalled"):
            head = f"📉 <b>{NAME} uscita parziale</b> (ferma da {EXIT_STALL_MIN} min)"
        else:
            head = f"📉 <b>{NAME} in uscita</b>"
        return (
            f"{head} · venduti {x['sold']:.2f}/{x['start']:.2f} {COIN}"
            f" @ {avg:.5g} · fill {pct:.0f}% · resta {ev['size']:.2f}"
            f" · {rome(ev['day'], ev['time'])}"
        )

    def inc_text(o: dict, ev: dict) -> str:
        o["snap"] = {k: ev[k] for k in ("size", "price", "day", "time")}
        o["last_ts"] = ev.get("ts", o.get("last_ts", ""))
        if o.get("order_qty") and o["filled"] > o["order_qty"] * 1.0001:
            o["order_qty"] = None  # riga "post" di un altro ordine: niente %
        pct = ""
        if o.get("order_qty"):
            pct = f" · fill {min(o['filled'] / o['order_qty'], 1.0) * 100:.0f}%"
            if o.get("done") and o["filled"] < o["order_qty"] * 0.9999:
                # ordine tolto dal bot prima del 100%: la % resta quella vera
                pct += f" (ordine {o['done']})"
        if o["label"] == "aperta":
            head = f"📈 <b>{NAME} aperta</b> · "
        else:
            head = f"➕ <b>{NAME} {o['label']}</b> · pos "
        return (
            f"{head}{ev['size']:.2f} {COIN} @ {ev['price']:.5g}"
            f" · {ev['size'] * ev['price']:,.0f} {CCY}{pct}{o.get('bal', '')}"
            f" · {rome(ev['day'], ev['time'])}"
        )

    steps = state.get("steps", 0)
    wallet_now, wallet_at = current_wallet()

    opened_at = state.get("opened_at")

    deferred = False
    for ev in fresh:
        if ev["kind"] in ("new", "added") and ev["order"] and ev["order"] in orders:
            # altro pezzo di un ordine gia' notificato: stesso avviso, aggiornato
            o = orders[ev["order"]]
            o["filled"] = o.get("filled", 0.0) + ev["filled"]
            o["order_qty"] = o.get("order_qty") or ev["order_qty"]
            if o["order_qty"] and o["filled"] > o["order_qty"] * 1.0001:
                o["order_qty"] = None  # riga "post" di un altro ordine: niente %
            edit(o.get("msgs"), inc_text(o, ev))
            continue
        if ev["kind"] in ("new", "added"):
            if exit_.get("msgs"):
                # uscita rimasta parziale: il messaggio lo dice, poi si azzera
                exit_["ended"] = True
                edit(exit_["msgs"], exit_text(exit_, exit_["snap"]))
            exit_ = {}  # un ingresso chiude l'episodio di uscita parziale
        if ev["kind"] == "new":
            steps = 1
            opened_at = ev["ts"]
            orders = {}
            # All'apertura il saldo realizzato non cambia: vale l'ultima riga
            # [health]/[balance] prima del fill.
            bal = f" · wallet {wallet_now:.2f}" if wallet_now else ""
            o = {"filled": ev["filled"], "order_qty": ev["order_qty"], "label": "aperta", "bal": bal,
                 "pb_type": ev["pb_type"], "fill_price": ev["fill_price"]}
            o["msgs"] = send(inc_text(o, ev))
            if ev["order"]:
                orders[ev["order"]] = o
        elif ev["kind"] == "added":
            # Richiesto da Marco il 10/09: un avviso a ogni gradino in piu',
            # con la posizione aggregata.
            steps += 1
            o = {"filled": ev["filled"], "order_qty": ev["order_qty"], "label": f"gradino {steps}", "bal": "",
                 "pb_type": ev["pb_type"], "fill_price": ev["fill_price"]}
            o["msgs"] = send(inc_text(o, ev))
            if ev["order"]:
                orders[ev["order"]] = o
        elif ev["kind"] == "reduced":
            if not exit_:
                exit_ = {"start": ev["size"] + ev["filled"], "sold": ev["filled"],
                         "value": ev["value"], "msgs": []}
                exit_["msgs"] = send(exit_text(exit_, ev))
            else:
                exit_["sold"] += ev["filled"]
                exit_["value"] += ev["value"]
                exit_.pop("stalled", None)
                edit(exit_["msgs"], exit_text(exit_, ev))
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
            sold = exit_.get("sold", 0.0) + ev["filled"]
            value = exit_.get("value", 0.0) + ev["value"]
            avg = f" · uscita @ {value / sold:.5g}" if sold > 0 else ""
            final = (
                f"{icon} <b>{NAME} chiusa</b>{manual} · <b>{pnl:+.2f}</b> {CCY}{grad}{avg}"
                f" · fill 100%{bal} · {rome(ev['day'], ev['time'])}"
            )
            if exit_.get("msgs"):
                edit(exit_["msgs"], final)
            else:
                send(final)
            # ingressi rimasti a meta' (es. gradino eseguito in parte e
            # cancellato alla chiusura): il loro messaggio resta con la % vera
            for o in orders.values():
                if o.get("order_qty") and o["filled"] < o["order_qty"] * 0.9999 and not o.get("done"):
                    o["done"] = "chiuso"
                    edit(o.get("msgs"), inc_text(o, o["snap"]))
            steps = 0
            orders = {}
            exit_ = {}

    # Ingressi eseguiti in parte e poi tolti dal bot (es. entry_initial
    # ritirato a fine segnale, gradino riprezzato): la riga "[order] cancel"
    # con stesso tipo e prezzo dopo l'ultimo pezzo chiude l'avviso a quella %.
    for o in orders.values():
        if (not o.get("done") and o.get("order_qty") and o.get("snap")
                and o["filled"] < o["order_qty"] * 0.9999
                and _order_cancelled_log(lines, o.get("pb_type", ""), o.get("fill_price", 0.0), o.get("last_ts", ""))):
            o["done"] = "cancellato"
            edit(o.get("msgs"), inc_text(o, o["snap"]))
    # Uscita ferma a meta' (nessun pezzo da EXIT_STALL_MIN minuti e posizione
    # ancora aperta): il messaggio lo dice; se riprende, torna "in uscita".
    if exit_.get("msgs") and not exit_.get("stalled") and exit_.get("last_ts"):
        idle = datetime.now(timezone.utc).replace(tzinfo=None) - datetime.strptime(exit_["last_ts"], "%Y-%m-%dT%H:%M:%S")
        if idle >= timedelta(minutes=EXIT_STALL_MIN):
            exit_["stalled"] = True
            edit(exit_["msgs"], exit_text(exit_, exit_["snap"]))

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
    state["orders"] = orders
    state["exit"] = exit_
    state.pop("last_inc_order", None)
    state.pop("inc", None)
    STATE.write_text(json.dumps(state))

    if not bot_alive():
        send(f"🔴 <b>{NAME}: processo assente</b> — se ne occupa il watchdog, ma tienilo d'occhio.")


if __name__ == "__main__":
    main()
