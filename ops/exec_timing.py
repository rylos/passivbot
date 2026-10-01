#!/usr/bin/env python3
"""Tempi di esecuzione degli ordini maker 4RSI su ry-hl / ry-bybit.

Per ogni episodio (ingresso iniziale `entry_initial` o uscita 4RSI
`close_panic`) misura, dalla chiusura della candela 5m del segnale:
quando parte il primo ordine, quando arriva il fill completo, quanti
riprezzamenti/amend/rifiuti post-only ci sono stati, lo scarto fra il prezzo
del primo ordine e il prezzo medio del fill, e la fee (maker o no).

Fonti: cache dei fill del bot (orari dell'exchange, psize dopo il fill, fee)
e log del bot (post, amend, rifiuti). Sola lettura.

Uso: exec_timing.py hl|bybit [all|last] [giorni]
  all  -> tutti gli episodi degli ultimi `giorni` (default 3)
  last -> solo l'ultimo episodio completo, preceduto da "chiave|" (per il monitor)
"""
import glob
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

PROFILES = {
    "hl": ("/opt/passivbot-hl/logs/*config_hl_4rsi.json.log",
           "/opt/passivbot-hl/caches/fill_events/hyperliquid/hyperliquid_vault", 0.00015),
    "bybit": ("/opt/passivbot-bybit/logs/*config_bybit_4rsi.json.log",
              "/opt/passivbot-bybit/caches/fill_events/bybit/bybit_02", 0.0002),
}
KINDS = {"entry_initial_normal_long": "entrata", "close_panic_long": "uscita 4RSI"}
POST_RE = re.compile(r"\[order\]\s+post \S+ \| (?:buy|sell) long [\d.]+@([\d.]+) (entry_initial_normal_long|close_panic_long)")
REJ_RE = re.compile(r"post-only (entry_initial_normal_long|close_panic_long) rejected")
AMEND_RE = re.compile(r"maker exit amend ")
AMEND_FAIL_RE = re.compile(r"maker exit amend failed")
ROME = ZoneInfo("Europe/Rome")
MAX_GAP = timedelta(minutes=6)  # fra un ordine e il successivo dello stesso episodio
MAX_REST = timedelta(minutes=60)  # ordine rimasto fermo sul book fino al fill


def utc(s):
    return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")


def rome(dt, fmt="%H:%M:%S"):
    return dt.replace(tzinfo=timezone.utc).astimezone(ROME).strftime(fmt)


def dur(td):
    s = int(round(td.total_seconds()))
    return f"{s // 60}m{s % 60:02d}s" if s >= 60 else f"{s}s"


def load_fills(fdir, days):
    out = []
    today = datetime.now(timezone.utc).date()
    for i in range(days, -1, -1):
        try:
            out += json.load(open(os.path.join(fdir, f"{today - timedelta(days=i)}.json")))
        except (OSError, ValueError):
            pass
    return sorted(out, key=lambda f: f["datetime"])


def load_log(pattern, since):
    lines = []
    for path in sorted(glob.glob(pattern), key=os.path.getmtime):
        if datetime.fromtimestamp(os.path.getmtime(path), timezone.utc).replace(tzinfo=None) < since:
            continue
        with open(path, errors="replace") as fh:
            lines += [ln for ln in fh if ln[:4] == "2026" or ln[:2] == "20"]
    return lines


def episodes(fills):
    """Gruppi di fill dello stesso tipo che completano l'ordine (entrata: fino
    al primo fill; uscita: fino a posizione zero)."""
    eps, cur = [], []
    for f in fills:
        t = f.get("pb_order_type")
        if t not in KINDS:
            if t:  # griglia, trailing, unstuck...: solo maker sì/no
                eps.append([f])
            continue
        if cur and (cur[-1]["pb_order_type"] != t or utc(f["datetime"]) - utc(cur[-1]["datetime"]) > timedelta(minutes=10)):
            eps.append(cur)
            cur = []
        cur.append(f)
        done = abs(float(f.get("psize") or 0)) < 1e-9 if t == "close_panic_long" else True
        if done and t == "close_panic_long":
            eps.append(cur)
            cur = []
    if cur and cur[-1]["pb_order_type"] == "entry_initial_normal_long":
        eps.append(cur)
    return eps


def analyse(ep, lines, maker_fee):
    kind = ep[0]["pb_order_type"]
    if kind not in KINDS:
        f = ep[0]
        fr = round(abs(float(f.get("fee_ratio") or 0)), 6)
        maker = fr <= maker_fee * 1.05
        key = f"{kind}|{f['datetime'][:19]}"
        text = (
            f"{kind} {rome(utc(f['datetime']), '%d/%m %H:%M:%S')} | {f['side']} {abs(float(f['qty'])):g} @ {float(f['price']):g}"
            f" | fee {fr*100:.3f}% {'maker' if maker else 'NON maker'}"
        )
        return key, text
    end = utc(ep[-1]["datetime"])
    first_fill = utc(ep[0]["datetime"])
    posts = []
    for ln in lines:
        m = POST_RE.search(ln)
        if m and m.group(2) == kind:
            t = utc(ln)
            if t <= first_fill + timedelta(seconds=5):
                posts.append((t, float(m.group(1))))
    # risale finché gli ordini sono vicini fra loro: l'inizio dell'episodio
    chain = []
    for t, p in reversed(posts):
        if chain and chain[-1][0] - t > MAX_GAP:
            break
        if not chain and first_fill - t > MAX_REST:
            break
        chain.append((t, p))
    if not chain:
        return None
    chain.reverse()
    first_t, first_p = chain[0]
    signal = first_t.replace(second=0) - timedelta(minutes=first_t.minute % 5)
    win = [ln for ln in lines if signal <= utc(ln) <= end + timedelta(seconds=5)]
    n_rej = sum(1 for ln in win if (m := REJ_RE.search(ln)) and m.group(1) == kind)
    n_amend = sum(1 for ln in win if AMEND_RE.search(ln) and not AMEND_FAIL_RE.search(ln))
    n_amend_fail = sum(1 for ln in win if AMEND_FAIL_RE.search(ln))
    qty = sum(abs(float(f["qty"])) for f in ep)
    vwap = sum(abs(float(f["qty"])) * float(f["price"]) for f in ep) / qty
    side = 1 if kind == "close_panic_long" else -1  # + = a favore
    slip = side * (vwap - first_p) / first_p * 100 + 0.0  # niente -0.000
    if abs(slip) < 0.0005:
        slip = 0.0
    fees = sorted({round(abs(float(f.get("fee_ratio") or 0)), 6) for f in ep})
    maker = all(fr <= maker_fee * 1.05 for fr in fees)
    key = f"{kind}|{ep[-1]['datetime'][:19]}"
    text = (
        f"{KINDS[kind]} {rome(end, '%d/%m')} | segnale {rome(signal, '%H:%M')}"
        f" → 1° ordine +{dur(first_t - signal)} → fill +{dur(end - signal)}"
        f" ({len(ep)} fill) | {len(chain)} ordini, {n_amend} amend"
        f"{f' ({n_amend_fail} falliti)' if n_amend_fail else ''}, {n_rej} rifiuti post-only"
        f" | 1° prezzo {first_p:g} → fill {vwap:.5g} ({slip:+.3f}% a favore)"
        f" | fee {', '.join(f'{x*100:.3f}%' for x in fees)} {'maker' if maker else 'NON maker'}"
    )
    return key, text


def main():
    inst = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "all"
    days = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    log_glob, fdir, maker_fee = PROFILES[inst]
    fills = load_fills(fdir, days)
    eps = sorted(episodes(fills), key=lambda ep: ep[-1]["datetime"])
    if mode == "last":
        eps = eps[-1:]
    if not eps:
        return
    since = utc(eps[0][0]["datetime"]) - timedelta(hours=1)
    lines = load_log(log_glob, since)
    for ep in eps:
        res = analyse(ep, lines, maker_fee)
        if res is None:
            continue
        key, text = res
        print(f"{key}|{text}" if mode == "last" else text)


if __name__ == "__main__":
    main()
