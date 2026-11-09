#!/usr/bin/env python3
"""Statistiche ry-hl e ry-bybit: copia i fill da amazon in un SQLite letto da Metabase.

Gira sul server docker (cron orario). Sola lettura verso amazon: nessuna chiamata
agli exchange con le chiavi dei bot, nessun effetto sui bot. Hyperliquid viene
interrogato solo sugli endpoint pubblici (funding e movimenti del vault).

  collect_stats.py collect   aggiorna il database
  collect_stats.py summary   manda il riepilogo di ieri su Telegram

I messaggi escono da amazon con ~/watchdog/telegram.json: il token resta li'.
Config in BASE/config.json: {"hl_address": "0x..."} (fuori dal repo).
"""
import argparse
import base64
import glob
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROME = ZoneInfo("Europe/Rome")
AMAZON = "admin@amazon.ziliani.net"
BASE = Path(os.environ.get("STATS_BASE", "/opt/passivbot-stats"))
DB_PATH = Path(os.environ.get("STATS_DB", "/docker/passivbot-stats/stats.db"))
METABASE_UID = 2000

# Le statistiche partono da qui; la lettura parte qualche giorno prima per non
# spezzare il ciclo gia' aperto a cavallo della data.
START = datetime(2026, 8, 1, tzinfo=ROME)
READ_FROM = START - timedelta(days=14)
FLAT = 1e-6
SCHEMA_VERSION = 2
LEDGER_FROM = datetime(2026, 7, 1, tzinfo=ROME)
HOUR_MS = 3600 * 1000

BOTS = {
    "ry-hl": {"remote": "/opt/passivbot-hl", "cache": "hyperliquid/hyperliquid_vault", "state": "hyperliquid/hyperliquid_vault", "ccy": "USDC"},
    "ry-bybit": {"remote": "/opt/passivbot-bybit", "cache": "bybit/bybit_02", "state": "bybit/bybit_02", "ccy": "USDT"},
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS fills (
  bot TEXT NOT NULL, id TEXT NOT NULL, ts_ms INTEGER NOT NULL, ts_rome TEXT NOT NULL,
  day TEXT NOT NULL, month TEXT NOT NULL, year TEXT NOT NULL,
  symbol TEXT, side TEXT, qty REAL, price REAL, notional REAL,
  pnl REAL, fee REAL, net REAL, order_type TEXT, order_id TEXT, psize REAL, pprice REAL,
  PRIMARY KEY (bot, id));
CREATE INDEX IF NOT EXISTS idx_fills_day ON fills (bot, day);
CREATE TABLE IF NOT EXISTS trades (
  bot TEXT NOT NULL, open_ts_ms INTEGER NOT NULL, close_ts_ms INTEGER NOT NULL,
  open_rome TEXT NOT NULL, close_rome TEXT NOT NULL,
  day TEXT NOT NULL, month TEXT NOT NULL, year TEXT NOT NULL,
  duration_min REAL, fills INTEGER, grid_steps INTEGER, max_qty REAL, avg_entry REAL, avg_exit REAL,
  pnl REAL, fees REAL, net REAL, win INTEGER, exit_type TEXT,
  PRIMARY KEY (bot, open_ts_ms));
CREATE TABLE IF NOT EXISTS equity (
  bot TEXT NOT NULL, ts_ms INTEGER NOT NULL, ts_rome TEXT NOT NULL, day TEXT NOT NULL,
  balance REAL, equity REAL, PRIMARY KEY (bot, ts_ms));
CREATE TABLE IF NOT EXISTS funding (
  bot TEXT NOT NULL, ts_ms INTEGER NOT NULL, ts_rome TEXT NOT NULL,
  day TEXT NOT NULL, month TEXT NOT NULL, year TEXT NOT NULL,
  coin TEXT, amount REAL, rate REAL, PRIMARY KEY (bot, ts_ms, coin));
CREATE TABLE IF NOT EXISTS cashflows (
  bot TEXT NOT NULL, ts_ms INTEGER NOT NULL, ts_rome TEXT NOT NULL, day TEXT NOT NULL,
  type TEXT, amount REAL, raw TEXT, key TEXT NOT NULL, PRIMARY KEY (bot, key));
CREATE TABLE IF NOT EXISTS bybit_ledger (
  id TEXT PRIMARY KEY, ts_ms INTEGER NOT NULL, ts_rome TEXT NOT NULL, type TEXT, symbol TEXT,
  change REAL, cash_balance REAL);
CREATE INDEX IF NOT EXISTS idx_bybit_ledger_ts ON bybit_ledger (ts_ms);
CREATE TABLE IF NOT EXISTS hl_points (ts_ms INTEGER PRIMARY KEY, ts_rome TEXT NOT NULL, value REAL NOT NULL);
CREATE TABLE IF NOT EXISTS month_base (
  bot TEXT NOT NULL, month TEXT NOT NULL, base_rome TEXT NOT NULL, base REAL NOT NULL, source TEXT NOT NULL,
  PRIMARY KEY (bot, month));
CREATE TABLE IF NOT EXISTS vault_shares (titolare TEXT PRIMARY KEY, valore REAL NOT NULL, pct REAL NOT NULL, aggiornato TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS meta (name TEXT PRIMARY KEY, value TEXT);
"""


def rome_parts(ts_ms):
    dt = datetime.fromtimestamp(ts_ms / 1000, ROME)
    return dt.strftime("%Y-%m-%d %H:%M:%S"), dt.strftime("%Y-%m-%d"), dt.strftime("%Y-%m"), dt.strftime("%Y")


def run(cmd, **kw):
    # stdin chiuso: ssh altrimenti consuma lo stdin del chiamante.
    return subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL, **kw).stdout


def sync_raw():
    for bot, cfg in BOTS.items():
        dest = BASE / "raw" / bot
        dest.mkdir(parents=True, exist_ok=True)
        src = f"{AMAZON}:{cfg['remote']}/caches/fill_events/{cfg['cache']}/"
        run(["rsync", "-a", "--delete", "--include=20*.json", "--exclude=*", src, f"{dest}/"])


def load_fills(bot):
    """Fill di un bot dal READ_FROM in poi, in ordine di esecuzione."""
    since = READ_FROM.timestamp() * 1000
    rows = {}
    for path in sorted(glob.glob(str(BASE / "raw" / bot / "20*.json"))):
        for rec in json.loads(Path(path).read_text()):
            if rec["timestamp"] >= since:
                rows[rec["id"]] = rec
    # Fill spezzati nello stesso millisecondo: psize e' la posizione DOPO il fill,
    # quindi cresce sugli acquisti e cala sulle vendite.
    return sorted(rows.values(), key=lambda r: (r["timestamp"], -r["psize"] if r["side"] == "sell" else r["psize"]))


def build_trades(fills):
    """Cicli flat -> posizione -> flat. Il primo ciclo incompleto viene scartato."""
    trades, cur = [], None
    for rec in fills:
        entering = rec["side"] == "buy"
        if cur is None:
            if not (entering and abs(rec["psize"] - abs(rec["qty"])) < FLAT):
                continue  # siamo a meta' di un ciclo iniziato prima della lettura
            cur = []
        cur.append(rec)
        if abs(rec["psize"]) < FLAT:
            trades.append(cur)
            cur = None
    return trades


def trade_row(bot, cycle):
    entries = [r for r in cycle if r["side"] == "buy"]
    exits = [r for r in cycle if r["side"] == "sell"]
    qty_in = sum(abs(r["qty"]) for r in entries)
    qty_out = sum(abs(r["qty"]) for r in exits)
    open_ms, close_ms = cycle[0]["timestamp"], cycle[-1]["timestamp"]
    pnl = sum(r["pnl"] for r in cycle)
    fees = sum(r["fee_paid"] for r in cycle)
    grid = {r["client_order_id"] for r in entries if r["pb_order_type"].startswith("entry_grid")}
    open_rome = rome_parts(open_ms)[0]
    close_rome, day, month, year = rome_parts(close_ms)
    return (
        bot, open_ms, close_ms, open_rome, close_rome, day, month, year,
        round((close_ms - open_ms) / 60000, 2), len(cycle), len(grid),
        max(r["psize"] for r in cycle),
        sum(abs(r["qty"]) * r["price"] for r in entries) / qty_in,
        sum(abs(r["qty"]) * r["price"] for r in exits) / qty_out,
        pnl, fees, pnl + fees, int(pnl + fees > 0), cycle[-1]["pb_order_type"],
    )


def store_fills(db, bot, fills):
    since = START.timestamp() * 1000
    rows = []
    for r in fills:
        if r["timestamp"] < since:
            continue
        ts_rome, day, month, year = rome_parts(r["timestamp"])
        qty = abs(r["qty"])
        rows.append((bot, r["id"], r["timestamp"], ts_rome, day, month, year, r["symbol"], r["side"], qty, r["price"],
                     qty * r["price"], r["pnl"], r["fee_paid"], r["pnl"] + r["fee_paid"], r["pb_order_type"],
                     r["client_order_id"], r["psize"], r["pprice"]))
    db.executemany("INSERT OR REPLACE INTO fills VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    trades = [trade_row(bot, c) for c in build_trades(fills) if c[-1]["timestamp"] >= since]
    db.execute("DELETE FROM trades WHERE bot = ?", (bot,))
    db.executemany("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", trades)
    return len(rows), len(trades)


def store_equity(db):
    paths = " ".join(f"{c['remote']}/monitor/{c['state']}/state.latest.json" for c in BOTS.values())
    # Una riga per bot, per non dipendere dalla dimensione dei json.
    prog = ("python3 -c 'import json,sys\nfor p in sys.argv[1:]:\n  a=json.load(open(p))[\"account\"];"
            "print(a[\"balance_raw\"],a[\"equity\"])' " + paths)
    lines = run(["ssh", "-o", "BatchMode=yes", AMAZON, prog]).split("\n")
    now = int(time.time() * 1000)
    ts_rome, day, _, _ = rome_parts(now)
    for bot, line in zip(BOTS, lines):
        balance, equity = map(float, line.split())
        db.execute("INSERT OR REPLACE INTO equity VALUES (?,?,?,?,?,?)", (bot, now, ts_rome, day, balance, equity))


def hl_info(payload):
    req = urllib.request.Request("https://api.hyperliquid.xyz/info", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def hl_paged(kind, address, start_ms):
    """Endpoint a pagine da 500 righe, in ordine di tempo."""
    rows = []
    while True:
        page = hl_info({"type": kind, "user": address, "startTime": start_ms})
        rows += page
        if len(page) < 500:
            return rows
        start_ms = page[-1]["time"] + 1
        time.sleep(1)


def store_hl_flows(db, address):
    start = int(START.timestamp() * 1000)
    last = db.execute("SELECT MAX(ts_ms) FROM funding WHERE bot = 'ry-hl'").fetchone()[0]
    funding = 0
    for row in hl_paged("userFunding", address, (last + 1) if last else start):
        delta = row["delta"]
        ts_rome, day, month, year = rome_parts(row["time"])
        db.execute("INSERT OR REPLACE INTO funding VALUES (?,?,?,?,?,?,?,?,?)",
                   ("ry-hl", row["time"], ts_rome, day, month, year, delta["coin"], float(delta["usdc"]), float(delta["fundingRate"])))
        funding += 1
    flows = 0
    for row in hl_paged("userNonFundingLedgerUpdates", address, start):
        delta = row["delta"]
        amount = next((float(delta[k]) for k in ("usdc", "amount", "requestedUsd", "usdcValue") if k in delta), None)
        raw = json.dumps(row, sort_keys=True)
        ts_rome, day, _, _ = rome_parts(row["time"])
        db.execute("INSERT OR REPLACE INTO cashflows VALUES (?,?,?,?,?,?,?,?)",
                   ("ry-hl", row["time"], ts_rome, day, delta.get("type"), amount, raw, hashlib.sha256(raw.encode()).hexdigest()))
        flows += 1
    return funding, flows


def store_hl_points(db, address):
    """Conserva i saldi pubblicati da Hyperliquid: la serie mensile scorre e li perde."""
    series = dict(hl_info({"type": "portfolio", "user": address}))
    since = LEDGER_FROM.timestamp() * 1000
    for name in ("allTime", "month"):
        for ts_ms, value in series[name]["accountValueHistory"]:
            if ts_ms >= since:
                db.execute("INSERT OR IGNORE INTO hl_points VALUES (?,?,?)", (ts_ms, rome_parts(ts_ms)[0], float(value)))


def store_vault_shares(db, address, owners):
    """Quote attuali del vault: i titolari noti stanno in config.json, gli altri in un'unica fetta."""
    followers = hl_info({"type": "vaultDetails", "vaultAddress": address})["followers"]
    total = sum(float(f["vaultEquity"]) for f in followers)
    named = {}
    for follower in followers:
        user = follower["user"]
        match = [o["name"] for o in owners if user.startswith(o["prefix"]) and user.endswith(o["suffix"])]
        name = match[0] if match else "Altri"
        named[name] = named.get(name, 0.0) + float(follower["vaultEquity"])
    now = rome_parts(int(time.time() * 1000))[0]
    db.execute("DELETE FROM vault_shares")
    for name, value in named.items():
        db.execute("INSERT INTO vault_shares VALUES (?,?,?,?)", (name, round(value, 2), round(100 * value / total, 2), now))


def store_bybit_ledger(db):
    last = db.execute("SELECT MAX(ts_ms) FROM bybit_ledger").fetchone()[0]
    start = last - HOUR_MS if last else int(LEDGER_FROM.timestamp() * 1000)
    rows = json.loads(run(["ssh", "-o", "BatchMode=yes", AMAZON, "python3", "~/watchdog/bybit_ledger.py", str(start)]))
    since = START.timestamp() * 1000
    for row in rows:
        ts_ms = int(row["transactionTime"])
        ts_rome, day, month, year = rome_parts(ts_ms)
        change = float(row["change"])
        db.execute("INSERT OR REPLACE INTO bybit_ledger VALUES (?,?,?,?,?,?,?)",
                   (row["id"], ts_ms, ts_rome, row["type"], row["symbol"], change, float(row["cashBalance"])))
        if ts_ms < since:
            continue
        if row["type"] == "SETTLEMENT":
            db.execute("INSERT OR REPLACE INTO funding VALUES (?,?,?,?,?,?,?,?,?)",
                       ("ry-bybit", ts_ms, ts_rome, day, month, year, row["symbol"], change, None))
        elif row["type"].startswith("TRANSFER"):
            db.execute("INSERT OR REPLACE INTO cashflows VALUES (?,?,?,?,?,?,?,?)",
                       ("ry-bybit", ts_ms, ts_rome, day, row["type"], change, json.dumps(row, sort_keys=True), row["id"]))
    return len(rows)


def month_starts():
    current = START
    now = datetime.now(ROME)
    while current <= now:
        yield current
        current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)


def build_month_base(db):
    """Saldo reale a inizio mese. Mai ricostruito: se manca il mese resta senza %."""
    db.execute("DELETE FROM month_base")
    for start in month_starts():
        month = start.strftime("%Y-%m")
        ms = int(start.timestamp() * 1000)
        # I punti Hyperliquid cadono ogni poche ore: vale l'ultimo entro un'ora dall'inizio del mese.
        row = db.execute("SELECT ts_rome, value FROM hl_points WHERE ts_ms <= ? ORDER BY ts_ms DESC LIMIT 1", (ms + HOUR_MS,)).fetchone()
        if row:
            db.execute("INSERT INTO month_base VALUES ('ry-hl',?,?,?,?)", (month, row[0], row[1], "Hyperliquid portfolio"))
        row = db.execute("SELECT ts_rome, cash_balance FROM bybit_ledger WHERE ts_ms < ? ORDER BY ts_ms DESC LIMIT 1", (ms,)).fetchone()
        if row:
            db.execute("INSERT INTO month_base VALUES ('ry-bybit',?,?,?,?)", (month, row[0], row[1], "Bybit transaction log"))


def create_views(db):
    if db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION:
        return
    for name, col in (("daily_stats", "day"), ("monthly_stats", "month"), ("yearly_stats", "year")):
        db.executescript(f"""
DROP VIEW IF EXISTS {name};
CREATE VIEW {name} AS
WITH f AS (SELECT bot, {col} AS period, COUNT(*) AS fills, SUM(notional) AS volume, SUM(pnl) AS pnl,
                  SUM(fee) AS fees, SUM(net) AS net FROM fills GROUP BY 1, 2),
     t AS (SELECT bot, {col} AS period, COUNT(*) AS trades, SUM(win) AS wins, AVG(duration_min) AS avg_duration_min,
                  MAX(grid_steps) AS max_grid_steps, MAX(net) AS best_trade, MIN(net) AS worst_trade FROM trades GROUP BY 1, 2),
     u AS (SELECT bot, {col} AS period, SUM(amount) AS funding FROM funding GROUP BY 1, 2),
     p AS (SELECT bot, period FROM f UNION SELECT bot, period FROM u)
SELECT p.bot, p.period, COALESCE(f.fills, 0) AS fills, ROUND(COALESCE(f.volume, 0), 2) AS volume,
       ROUND(COALESCE(f.pnl, 0), 2) AS pnl_lordo, ROUND(COALESCE(f.fees, 0), 2) AS fee,
       ROUND(COALESCE(f.net, 0), 2) AS pnl_netto, ROUND(u.funding, 2) AS funding,
       COALESCE(t.trades, 0) AS trade_chiusi, COALESCE(t.wins, 0) AS vinti,
       ROUND(100.0 * t.wins / t.trades, 1) AS win_rate, ROUND(t.avg_duration_min, 1) AS durata_media_min,
       t.max_grid_steps AS gradini_max, ROUND(t.best_trade, 2) AS trade_migliore, ROUND(t.worst_trade, 2) AS trade_peggiore
FROM p LEFT JOIN f USING (bot, period) LEFT JOIN t USING (bot, period) LEFT JOIN u USING (bot, period);
""")
    db.executescript("""
DROP VIEW IF EXISTS monthly_return;
CREATE VIEW monthly_return AS
SELECT b.bot, b.month AS mese, ROUND(b.base, 2) AS saldo_base, b.base_rome AS data_saldo, b.source AS fonte,
       m.pnl_netto, COALESCE(m.funding, 0) AS funding,
       ROUND(m.pnl_netto + COALESCE(m.funding, 0), 2) AS guadagno,
       ROUND(100.0 * (m.pnl_netto + COALESCE(m.funding, 0)) / b.base, 2) AS pct
FROM month_base b JOIN monthly_stats m ON m.bot = b.bot AND m.period = b.month;
DROP VIEW IF EXISTS apr_stats;
CREATE VIEW apr_stats AS
WITH r AS (SELECT bot, substr(mese, 1, 4) AS anno, SUM(pct) AS pct_totale FROM monthly_return GROUP BY 1, 2),
     d AS (SELECT bot, substr(day, 1, 4) AS anno, MIN(julianday('now'), julianday(substr(day, 1, 4) || '-12-31') + 1) - julianday(MIN(day)) AS giorni
           FROM fills GROUP BY 1, 2)
SELECT r.bot, r.anno, ROUND(r.pct_totale, 2) AS pct_totale, ROUND(d.giorni, 1) AS giorni,
       ROUND(r.pct_totale / d.giorni * 365, 1) AS apr_pct
FROM r JOIN d USING (bot, anno);
""")
    db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def collect():
    config = json.loads((BASE / "config.json").read_text())
    sync_raw()
    fills_by_bot = {bot: load_fills(bot) for bot in BOTS}
    db = sqlite3.connect(DB_PATH, timeout=30)
    try:
        with db:
            db.executescript(SCHEMA)
            create_views(db)
            since = int(START.timestamp() * 1000)
            for table in ("fills", "funding", "cashflows", "equity"):
                db.execute(f"DELETE FROM {table} WHERE ts_ms < ?", (since,))
            for bot, fills in fills_by_bot.items():
                print(bot, "fill/trade", *store_fills(db, bot, fills))
            store_equity(db)
            print("ry-hl funding/movimenti", *store_hl_flows(db, config["hl_address"]))
            store_hl_points(db, config["hl_address"])
            store_vault_shares(db, config["hl_address"], config["vault_owners"])
            print("ry-bybit registro", store_bybit_ledger(db))
            build_month_base(db)
            db.execute("INSERT OR REPLACE INTO meta VALUES ('last_ok', ?)", (rome_parts(int(time.time() * 1000))[0],))
    finally:
        db.close()
    os.chown(DB_PATH, METABASE_UID, METABASE_UID)
    os.chmod(DB_PATH, 0o660)


def send_telegram(text):
    b64 = base64.b64encode(text.encode()).decode()
    prog = f"""
import base64, json, urllib.parse, urllib.request
c = json.load(open("/home/admin/watchdog/telegram.json"))
data = urllib.parse.urlencode({{"chat_id": c["chat_id"], "text": base64.b64decode("{b64}").decode()}}).encode()
urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % c["token"], data, timeout=20)
"""
    subprocess.run(["ssh", "-o", "BatchMode=yes", AMAZON, "python3", "-"], input=prog, check=True, text=True, timeout=60)


def summary(dry_run):
    db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=30)
    now = datetime.now(ROME)
    yesterday = now - timedelta(days=1)
    day, month, year = yesterday.strftime("%Y-%m-%d"), yesterday.strftime("%Y-%m"), yesterday.strftime("%Y")
    last_ok = db.execute("SELECT value FROM meta WHERE name = 'last_ok'").fetchone()[0]
    lines = [f"📊 Statistiche {yesterday.strftime('%d/%m')} · PnL netto fee"]
    for bot, cfg in BOTS.items():
        sums = {}
        for view, period in (("daily_stats", day), ("monthly_stats", month), ("yearly_stats", year)):
            row = db.execute(f"SELECT pnl_netto, trade_chiusi FROM {view} WHERE bot = ? AND period = ?", (bot, period)).fetchone()
            sums[view] = row or (0.0, 0)
        lines.append(f"{bot}: giorno {sums['daily_stats'][0]:+.2f} ({sums['daily_stats'][1]} trade) · "
                     f"mese {sums['monthly_stats'][0]:+.2f} · anno {sums['yearly_stats'][0]:+.2f} {cfg['ccy']}")
    age = now - datetime.strptime(last_ok, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ROME)
    if age > timedelta(hours=3):
        lines.append(f"⚠️ dati fermi al {last_ok}")
    text = "\n".join(lines)
    print(text)
    if not dry_run:
        send_telegram(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cmd", choices=["collect", "summary"])
    parser.add_argument("--dry-run", action="store_true", help="summary: stampa senza inviare")
    args = parser.parse_args()
    if args.cmd == "collect":
        collect()
    else:
        summary(args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
