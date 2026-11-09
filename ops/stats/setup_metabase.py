#!/usr/bin/env python3
"""Configura l'istanza Metabase separata delle statistiche (porta 3003).

Rilanciabile: account, database, collection e dashboard si creano solo se mancano,
le domande vengono ricreate. Le password stanno in BASE/.mb-*.
"""
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

URL = "https://cmonitor.ziliani.net"
BASE = Path(os.environ.get("STATS_BASE", "/opt/passivbot-stats"))
SITE = "cmonitor"
NAME = "Bot"
CONFIG = json.loads((BASE / "config.json").read_text())  # nomi ed email restano fuori dal repo pubblico
MARCO = CONFIG["metabase_users"]["admin"]
SECOND_USER = CONFIG["metabase_users"]["second"]
TAB_CHARTS, TAB_DETAILS = -1, -2
session = None


def api(method, path, body=None):
    headers = {"Content-Type": "application/json"}
    if session:
        headers["X-Metabase-Session"] = session
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(URL + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as err:
        raise SystemExit(f"{method} {path}: HTTP {err.code} {err.read()[:400].decode(errors='replace')}")
    return json.loads(raw) if raw else None


def items(obj):
    return obj["data"] if isinstance(obj, dict) and "data" in obj else obj


def login():
    global session
    password = (BASE / ".mb-marco").read_text().strip()
    props = api("GET", "/api/session/properties")
    if not props.get("has-user-setup"):
        user = {**MARCO, "password": password, "password_confirm": password, "site_name": SITE}
        result = api("POST", "/api/setup", {"token": props["setup-token"], "user": user,
                                            "prefs": {"site_name": SITE, "site_locale": "it", "allow_tracking": "false"}})
        session = result["id"]
    else:
        session = api("POST", "/api/session", {"username": MARCO["email"], "password": password})["id"]


def ensure_second_user():
    known = {u["email"].lower(): u for u in items(api("GET", "/api/user"))}
    user = known.get(SECOND_USER["email"])
    if user is None:
        user = api("POST", "/api/user", SECOND_USER)
        api("PUT", f"/api/user/{user['id']}/password", {"password": (BASE / CONFIG["metabase_users"]["second_password_file"]).read_text().strip()})
    if not user.get("is_superuser"):
        api("PUT", f"/api/user/{user['id']}", {"is_superuser": True})


def ensure_database():
    existing = items(api("GET", "/api/database"))
    for db in existing:
        if db.get("is_sample"):
            api("DELETE", f"/api/database/{db['id']}")
    found = [db for db in existing if db["name"] == NAME]
    if found:
        return found[0]["id"]
    return api("POST", "/api/database", {"engine": "sqlite", "name": NAME, "details": {"db": "/passivbot-stats/stats.db"}})["id"]


def ensure_collection():
    for col in api("GET", "/api/collection"):
        if col.get("name") == NAME and not col.get("archived"):
            return col["id"]
    return api("POST", "/api/collection", {"name": NAME})["id"]


BOT_COLORS = {"ry-hl": "#3987e5", "ry-bybit": "#d95926"}
OWNER_COLORS = CONFIG["owner_colors"]
OWNERS = [name for name in OWNER_COLORS if name != "Altri"]


def chart(x, y, unit):
    return {
        "graph.dimensions": [x, "bot"], "graph.metrics": [y], "graph.x_axis.scale": "ordinal",
        "graph.x_axis.title_text": "", "graph.y_axis.title_text": unit, "graph.show_values": False,
        "line.missing": "interpolate",
        "series_settings": {bot: {"color": color, "line.missing": "interpolate"} for bot, color in BOT_COLORS.items()},
    }


def tile(title, sql, col, row, suffix, decimals):
    viz = {"column_settings": {'["name","v"]': {"suffix": suffix, "number_style": "decimal", "decimals": decimals}}}
    return {"title": title, "display": "scalar", "viz": viz, "sql": sql, "tab": TAB_CHARTS, "col": col, "row": row, "w": 8, "h": 3}


def graph(title, display, viz, sql, col, row, width, height):
    return {"title": title, "display": display, "viz": viz, "sql": sql, "tab": TAB_CHARTS, "col": col, "row": row, "w": width, "h": height}


def table(title, sql, row, height):
    return {"title": title, "display": "table", "viz": {}, "sql": sql, "tab": TAB_DETAILS, "col": 0, "row": row, "w": 24, "h": height}


def heading(text, tab, row):
    return {"heading": text, "tab": tab, "col": 0, "row": row, "w": 24, "h": 1}


APR = "SELECT apr_pct AS v FROM apr_stats WHERE bot = '{}' AND anno = strftime('%Y', 'now')"
MONTH = "SELECT pct AS v FROM monthly_return WHERE bot = '{}' ORDER BY mese DESC LIMIT 1"
CAPITAL = "SELECT ROUND(equity, 0) AS v FROM equity WHERE bot = '{}' ORDER BY ts_ms DESC LIMIT 1"
CUMULATED = ("SELECT period AS giorno, bot, ROUND(SUM(pnl_netto) OVER (PARTITION BY bot ORDER BY period), 2) AS cumulato "
             "FROM daily_stats ORDER BY 1, 2")
DRAWDOWN = ("WITH c AS (SELECT period AS giorno, bot, SUM(pnl_netto) OVER (PARTITION BY bot ORDER BY period) AS cum FROM daily_stats) "
            "SELECT giorno, bot, ROUND(cum - MAX(cum) OVER (PARTITION BY bot ORDER BY giorno), 2) AS drawdown FROM c ORDER BY 1, 2")
BALANCE = ("SELECT giorno, bot, saldo FROM ("
           "SELECT substr(ts_rome, 1, 10) AS giorno, 'ry-hl' AS bot, value AS saldo, MAX(ts_ms) FROM hl_points WHERE ts_rome >= '2026-08-01' GROUP BY 1 "
           "UNION ALL "
           "SELECT substr(ts_rome, 1, 10), 'ry-bybit', cash_balance, MAX(ts_ms) FROM bybit_ledger WHERE ts_rome >= '2026-08-01' GROUP BY 1"
           ") ORDER BY 1, 2")
PIE = {"pie.dimension": "titolare", "pie.metric": "valore", "pie.show_legend": True, "pie.percent_visibility": "both", "pie.decimal_places": 2, "pie.slice_threshold": 0, "pie.colors": OWNER_COLORS}

CARDS = [
    heading("Rendimento", TAB_CHARTS, 0),
    tile("APR 2026 · ry-hl", APR.format("ry-hl"), 0, 1, "%", 1),
    tile("APR 2026 · ry-bybit", APR.format("ry-bybit"), 8, 1, "%", 1),
    tile("Capitale · ry-hl", CAPITAL.format("ry-hl"), 16, 1, " USDC", 0),
    tile("Mese in corso · ry-hl", MONTH.format("ry-hl"), 0, 4, "%", 2),
    tile("Mese in corso · ry-bybit", MONTH.format("ry-bybit"), 8, 4, "%", 2),
    tile("Capitale · ry-bybit", CAPITAL.format("ry-bybit"), 16, 4, " USDT", 0),
    heading("Quote del vault e guadagno mensile", TAB_CHARTS, 7),
    graph("Quote vault ry-hl", "pie", PIE, "SELECT titolare, valore FROM vault_shares ORDER BY valore DESC", 0, 8, 10, 9),
    graph("Guadagno mensile %", "bar", chart("mese", "pct", "%"), "SELECT mese, bot, pct FROM monthly_return ORDER BY 1, 2", 10, 8, 14, 9),
    *[{**tile(f"{name} · quota vault", f"SELECT pct AS v FROM vault_shares WHERE titolare = '{name}'", index * 6, 17, "%", 2), "w": 6}
      for index, name in enumerate(OWNERS)],
    heading("Andamento", TAB_CHARTS, 20),
    graph("PnL netto cumulato (fee incluse)", "line", chart("giorno", "cumulato", "USD"), CUMULATED, 0, 21, 24, 8),
    graph("Drawdown del PnL realizzato", "area", chart("giorno", "drawdown", "USD"), DRAWDOWN, 0, 29, 12, 7),
    graph("Saldo reale (con depositi e prelievi)", "line", chart("giorno", "saldo", "USD"), BALANCE, 12, 29, 12, 7),
    graph("PnL netto giornaliero (30 giorni)", "bar", chart("giorno", "pnl_netto", "USD"),
          "SELECT period AS giorno, bot, pnl_netto FROM daily_stats WHERE period >= date('now','-30 days') ORDER BY 1, 2", 0, 36, 24, 7),
    table("Quote vault: dettaglio", "SELECT titolare, valore, pct, aggiornato FROM vault_shares ORDER BY valore DESC", 0, 5),
    table("Base di calcolo % mensili", "SELECT mese, bot, saldo_base, data_saldo, fonte, pnl_netto, funding, guadagno, pct FROM monthly_return ORDER BY mese DESC, bot", 5, 8),
    table("APR: dettaglio", "SELECT * FROM apr_stats ORDER BY anno DESC, bot", 13, 4),
    table("Riepilogo annuale", "SELECT * FROM yearly_stats ORDER BY period DESC, bot", 17, 4),
    table("Riepilogo mensile", "SELECT * FROM monthly_stats ORDER BY period DESC, bot", 21, 8),
    table("Riepilogo giornaliero (60 giorni)", "SELECT * FROM daily_stats WHERE period >= date('now','-60 days') ORDER BY period DESC, bot", 29, 10),
    table("Ultimi 50 trade",
          "SELECT bot, open_rome AS apertura, close_rome AS chiusura, duration_min AS minuti, grid_steps AS gradini, ROUND(max_qty, 2) AS quantita_max, "
          "ROUND(avg_entry, 3) AS entrata_media, ROUND(avg_exit, 3) AS uscita_media, ROUND(pnl, 2) AS pnl_lordo, ROUND(fees, 2) AS fee, ROUND(net, 2) AS pnl_netto, "
          "exit_type AS uscita FROM trades ORDER BY close_ts_ms DESC LIMIT 50", 39, 10),
]


def build_dashboard(db_id, collection_id):
    found = [d for d in items(api("GET", "/api/dashboard")) if d["name"] == NAME]
    dash_id = found[0]["id"] if found else api("POST", "/api/dashboard", {"name": NAME, "collection_id": collection_id})["id"]
    old_cards = [c["id"] for c in items(api("GET", f"/api/collection/{collection_id}/items?models=card"))]
    dashcards = []
    for index, spec in enumerate(CARDS, start=1):
        place = {"id": -index, "dashboard_tab_id": spec["tab"], "col": spec["col"], "row": spec["row"], "size_x": spec["w"], "size_y": spec["h"]}
        if "heading" in spec:
            virtual = {"name": None, "display": "heading", "visualization_settings": {}, "archived": False}
            dashcards.append({**place, "card_id": None, "visualization_settings": {"virtual_card": virtual, "text": spec["heading"], "dashcard.background": False}})
            continue
        card = api("POST", "/api/card", {
            "name": spec["title"], "display": spec["display"], "visualization_settings": spec["viz"], "collection_id": collection_id,
            "dataset_query": {"type": "native", "database": db_id, "native": {"query": spec["sql"]}},
        })
        dashcards.append({**place, "card_id": card["id"]})
    tabs = [{"id": TAB_CHARTS, "name": "Panoramica"}, {"id": TAB_DETAILS, "name": "Dettagli"}]
    api("PUT", f"/api/dashboard/{dash_id}", {"tabs": tabs, "dashcards": dashcards})
    for card_id in old_cards:
        api("PUT", f"/api/card/{card_id}", {"archived": True})
    return dash_id


def main():
    login()
    ensure_second_user()
    db_id = ensure_database()
    collection_id = ensure_collection()
    time.sleep(5)
    dash_id = build_dashboard(db_id, collection_id)
    # Accesso solo con login: nessun link pubblico, condivisione pubblica spenta.
    dash = api("GET", f"/api/dashboard/{dash_id}")
    if dash.get("public_uuid"):
        api("DELETE", f"/api/dashboard/{dash_id}/public_link")
    api("PUT", "/api/setting/enable-public-sharing", {"value": False})
    dash = api("GET", f"/api/dashboard/{dash_id}")
    print(f"utenti: {[(u['email'], 'admin' if u.get('is_superuser') else 'utente') for u in items(api('GET', '/api/user'))]}")
    print(f"public_uuid: {dash.get('public_uuid')}")
    api("PUT", "/api/setting/site-url", {"value": URL})
    for dc in dash["dashcards"]:
        if dc.get("card_id") is None:
            continue
        res = api("POST", f"/api/dashboard/{dash_id}/dashcard/{dc['id']}/card/{dc['card_id']}/query", {"parameters": []})
        print(f"{dc['card']['name']}: {res.get('status')} righe={len(res.get('data', {}).get('rows', []))} {str(res.get('error', ''))[:160]}")
    groups = {g["name"]: g["id"] for g in api("GET", "/api/permissions/group")}
    all_users = str(groups["All Users"])
    print(f"gruppi: {sorted(groups)}")
    print(f"collection per All Users: {api('GET', '/api/collection/graph')['groups'][all_users].get(str(collection_id))}")
    print(f"database per All Users: {api('GET', '/api/permissions/graph')['groups'][all_users].get(str(db_id))}")
    try:
        api("PUT", "/api/setting/color-scheme", {"value": "dark"})
        print("tema account Marco: dark")
    except SystemExit as err:
        print(f"tema account non impostato: {err}")
    print(f"schede: {[t['name'] for t in dash.get('tabs', [])]}")
    print(f"LINK {URL}/dashboard/{dash_id}")


if __name__ == "__main__":
    main()
