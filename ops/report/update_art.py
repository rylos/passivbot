"""Rigenera le pagine backtest di ry-hl e ry-bybit (artefatti claude.ai) da nuovi backtest.

Parte dall'HTML gia' pubblicato (stile, grafici, parametri) e sostituisce dati,
KPI, tabelle e la sezione "Win rate e rischio". Uso:

  python3 ops/report/update_art.py --template-hl hl.html --template-bybit bybit.html \
      --art DIR --end 2026-09-23 --generated 24/09/2026

DIR contiene i risultati copiati da debian (`~/passivbot-up/backtests_buf/`):
  <nome>_0.0/*/*/{analysis.json,balance_and_equity.csv.gz,config.json,fills.csv}
  <nome>_0.0001, <nome>_0.0005 e le varianti _twel25, _twel2, _hsl (solo analysis.json)
Le varianti mancanti vengono saltate. I template si ottengono con Artifact read.
"""
import argparse, csv, glob, gzip, json, math, re, sys
from collections import OrderedDict
from datetime import datetime

ap = argparse.ArgumentParser()
ap.add_argument("--template-hl", required=True)
ap.add_argument("--template-bybit", required=True)
ap.add_argument("--art", default="art")
ap.add_argument("--end", required=True, help="ultimo giorno dei dati, YYYY-MM-DD")
ap.add_argument("--generated", required=True, help="data di generazione, GG/MM/AAAA")
ap.add_argument("--out", default=".")
ARGS = ap.parse_args()
SRC = {"hl": ARGS.template_hl, "bybit": ARGS.template_bybit}
CUR = {"hl": "USDC", "bybit": "USDT"}


def it(x, d=2):
    s = f"{x:,.{d}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def pct(x, d=1):
    return it(100 * x, d) + "%"


def run_dir(tag):
    return sorted(glob.glob(f"{ARGS.art}/{tag}/*/*"))[-1]


def load(tag):
    d = run_dir(tag)
    return json.load(open(d + "/analysis.json")), d


def cycles_of(fills):
    out, cur = [], None
    for r in fills:
        pnl, fee = float(r["pnl"]), float(r["fee_paid"])
        if cur is None:
            cur = dict(start=r["timestamp"], b0=float(r["usd_total_balance"]) - pnl - fee,
                       net=0.0, n_entry=0, maxq=0.0, maxwe=0.0)
        cur["net"] += pnl + fee
        if "entry" in r["type"]:
            cur["n_entry"] += 1
        cur["maxq"] = max(cur["maxq"], abs(float(r["psize"])))
        cur["maxwe"] = max(cur["maxwe"], float(r["wallet_exposure"]))
        if abs(float(r["psize"])) < 1e-9:
            cur["end"] = r["timestamp"]
            cur["pct"] = 100 * cur["net"] / cur["b0"]
            out.append(cur)
            cur = None
    return out


def build(name):
    s = open(SRC[name]).read()
    cur = CUR[name]
    a, d = load(f"{name}_0.0")
    fills = list(csv.DictReader(open(d + "/fills.csv")))
    rows = list(csv.DictReader(gzip.open(d + "/balance_and_equity.csv.gz", "rt")))
    cyc = cycles_of(fills)

    # serie a 4 ore: ultimo valore della finestra, drawdown minimo nella finestra
    series, peak, buck = [], 0.0, OrderedDict()
    for r in rows:
        t = r[""][:13]
        h = int(t[11:13]) // 4 * 4
        key = f"{t[:11]}{h:02d}"
        e, b = float(r["strategy_equity"]), float(r["usd_total_balance"])
        peak = max(peak, e)
        dd = e / peak - 1
        if key not in buck:
            buck[key] = dict(t=key, e=e, b=b, dd=dd)
        else:
            x = buck[key]
            x["e"], x["b"], x["dd"] = e, b, min(x["dd"], dd)
    for x in buck.values():
        series.append(dict(t=x["t"], e=round(x["e"], 2), b=round(x["b"], 2), dd=round(x["dd"], 4)))
    e_end = series[-1]["e"]

    monthly = OrderedDict()
    for r in fills:
        m = r["timestamp"][:7]
        monthly[m] = monthly.get(m, 0.0) + float(r["pnl"]) + float(r["fee_paid"])
    eq_month = OrderedDict()
    for r in rows:
        eq_month[r[""][:7]] = float(r["strategy_equity"])

    ndays = a["n_days"]
    gain = e_end / 10000
    cagr = gain ** (365 / ndays) - 1
    wins = [c for c in cyc if c["pct"] > 0]
    loss = [c for c in cyc if c["pct"] <= 0]

    # --- testata
    s = re.sub(r"2024-12-05 → 2026-09-\d\d", f"2024-12-05 → {ARGS.end}", s)
    s = re.sub(r'<div class="stamp">.*?</div>',
               f'<div class="stamp">{round(ndays)} giorni · {len(fills)} fill · {len(cyc)} cicli<br>'
               f'saldo iniziale <b>10.000 {cur}</b> · fee maker 0,015% / taker 0,055%<br>generato il {ARGS.generated}</div>',
               s, count=1, flags=re.S)
    kp = lambda l, v, sub: f"<div class='kpi'><div class='l'>{l}</div><div class='v'>{v}</div><div class='s'>{sub}</div></div>"
    kpis = "".join([
        kp("Guadagno", it(gain, 1) + "×", f"10.000 → {it(e_end, 0)} {cur}"),
        kp("ADG", pct(a["adg_strategy_eq"], 3), f"pesato {pct(a['adg_strategy_eq_w'], 3)} · CAGR {it(100 * cagr, 0)}%"),
        kp("Drawdown max", pct(a["drawdown_worst_strategy_eq"]), f"media peggior 1% {pct(a['drawdown_worst_mean_1pct_strategy_eq'])}"),
        kp("MDG", pct(a["mdg_strategy_eq"], 3), f"Sharpe {it(a['sharpe_ratio_strategy_eq'])} · Sortino {it(a['sortino_ratio_strategy_eq'])} (giornalieri)"),
        kp("Cicli chiusi", str(len(cyc)), f"{len(wins)} in utile · {len(loss)} in perdita"),
        kp("Posizione più lunga", it(a["position_held_days_max"], 1) + " g",
           f"media {it(a['position_held_days_mean'])} g · recupero max {it(a['strategy_eq_recovery_days_max'], 0)} g"),
    ])
    s = re.sub(r'<div class="kpis">.*?</div></div></div>', f'<div class="kpis">{kpis}</div>', s, count=1, flags=re.S)
    s = re.sub(r"Il punto più basso è il [\d,]+%", f"Il punto più basso è il {pct(a['drawdown_worst_strategy_eq'])}", s)

    # --- tabella mensile
    trs, prev = [], 10000.0
    for m, net in monthly.items():
        r_ = net / prev
        cls = "neg" if net < 0 else ""
        trs.append(f"<tr><td>{m}</td><td class='num {cls}'>{it(net, 0)}</td><td class='num {cls}'>{pct(r_)}</td>"
                   f"<td class='num'>{it(eq_month[m], 0)}</td></tr>")
        prev = eq_month[m]
    s = replace_tbody(s, "Per mese", "".join(trs))

    # --- metriche complete
    M = [("ADG (equity strategia)", pct(a["adg_strategy_eq"], 3)),
         ("ADG pesato sul recente", pct(a["adg_strategy_eq_w"], 3)),
         ("MDG (mediana giornaliera)", pct(a["mdg_strategy_eq"], 3)),
         ("Guadagno (×)", it(a["gain_strategy_eq"], 3)),
         ("Drawdown peggiore", pct(a["drawdown_worst_strategy_eq"], 3)),
         ("Drawdown, media peggior 1%", pct(a["drawdown_worst_mean_1pct_strategy_eq"], 3)),
         ("Sharpe", it(a["sharpe_ratio_strategy_eq"], 3)),
         ("Sortino", it(a["sortino_ratio_strategy_eq"], 3)),
         ("Calmar", it(a["calmar_ratio_strategy_eq"], 3)),
         ("Giorni max per recuperare un massimo", it(a["strategy_eq_recovery_days_max"], 3)),
         ("Posizione più lunga (giorni)", it(a["position_held_days_max"], 3)),
         ("Durata media posizione (giorni)", it(a["position_held_days_mean"], 3)),
         ("Perdite / profitti", it(a["loss_profit_ratio"], 3)),
         ("Tempo medio sott'acqua", pct(a["strategy_eq_underwater_pct_mean"], 3)),
         ("Volume medio giornaliero (% wallet)", pct(a["volume_pct_per_day_avg"], 3)),
         ("Posizioni per giorno", it(a["positions_held_per_day"], 3)),
         ("Quota tempo esposto", pct(a["exposure_ratio_usd"], 3)),
         ("Completamento backtest", pct(a["backtest_completion_ratio"], 3)),
         ("Hard stop per anno", it(a["hard_stop_restarts_per_year"], 3)),
         ("Giorni con fill", pct(a["fills_active_days_ratio"], 3)),
         ("Ore medie fra ingressi", it(a["entry_interval_hours_mean"], 3)),
         ("Ore max fra ingressi", it(a["entry_interval_hours_max"], 3))]
    s = replace_tbody(s, "Metriche complete", "".join(f"<tr><td>{k}</td><td class='num'>{v}</td></tr>" for k, v in M))

    # --- cicli
    trs = []
    for c in reversed(cyc):
        t0, t1 = c["start"][:16], c["end"][:16]
        days = (datetime.fromisoformat(t1) - datetime.fromisoformat(t0)).total_seconds() / 86400
        cls = "neg" if c["net"] < 0 else ""
        trs.append(f"<tr><td>{t0}</td><td>{t1}</td><td class='num'>{it(days, 1)}</td><td class='num'>{c['n_entry']}</td>"
                   f"<td class='num'>{it(c['maxq'], 1)}</td><td class='num'>{it(c['maxwe'])}</td>"
                   f"<td class='num {cls}'>{it(c['net'])}</td></tr>")
    s = replace_tbody(s, "Cicli di posizione", "".join(trs))

    # --- parametri: enforcer come in produzione, eccedenza WE espressa correttamente
    s = re.sub(r"(<dt>Soglia enforcer</dt><dd>)[^<]*", r"\g<1>1,01", s)
    allow = json.load(open(d + "/config.json"))["bot"]["long"]["risk"]["we_excess_allowance_pct"]
    s = re.sub(r"(<dt>Eccedenza WE ammessa</dt><dd>)[^<]*", rf"\g<1>+{it(100 * allow, 1)}%", s)

    # --- nuova sezione win rate e rischio
    s = re.sub(r'<section class="two">\s*<div>\s*<h2>Win rate e rischio</h2>.*?</section>\n?', "", s, count=1, flags=re.S)
    s = s.replace("<section>\n  <h2>Parametri della config</h2>", risk_section(name, cyc, wins, loss) + "\n<section>\n  <h2>Parametri della config</h2>", 1)

    # --- dati grafici e piè di pagina
    data = json.dumps({"series": series, "monthly": monthly}, separators=(",", ":"))
    s = re.sub(r"const DATA=\{.*?\};\n", lambda _: f"const DATA={data};\n", s, count=1, flags=re.S)
    s = re.sub(r"dal 2024-12-05 al 2026-09-\d\d", f"dal 2024-12-05 al {ARGS.end}", s)
    if "backtest del " not in s:
        s = s.replace("saldo iniziale 10.000,", f"saldo iniziale 10.000, backtest del {ARGS.generated},")
    else:
        s = re.sub(r"backtest del [^,]*,", f"backtest del {ARGS.generated},", s, count=1)
    if "</style>" in s and ".wr" not in s:
        s = s.replace("</style>", ".wr td.hi{font-weight:600}\n.wr tr.base td{background:var(--acc-soft)}\n</style>", 1)
    return s


def replace_tbody(s, h2, body):
    i = s.index(f"<h2>{h2}</h2>")
    j = s.index("<tbody>", i) + len("<tbody>")
    k = s.index("</tbody>", j)
    return s[:j] + body + s[k:]


def risk_section(name, cyc, wins, loss):
    pw = [c["pct"] for c in wins]
    pl = [c["pct"] for c in loss]
    med = sorted(pw)[len(pw) // 2]
    worst = min(c["pct"] for c in cyc)
    be = abs(sum(pl) / len(pl)) / (abs(sum(pl) / len(pl)) + sum(pw) / len(pw)) if pl else 0
    stats = [("Cicli chiusi", str(len(cyc))),
             ("Cicli in utile", f"{len(wins)} ({it(100 * len(wins) / len(cyc))}%)"),
             ("Guadagno medio per ciclo", f"+{it(sum(pw) / len(pw))}% del wallet (mediana +{it(med)}%)"),
             ("Perdita media per ciclo", f"{it(sum(pl) / len(pl))}%" if pl else "—"),
             ("Perdita chiusa peggiore", f"{it(worst)}%"),
             ("Somma vincite / perdite", f"+{it(sum(pw), 1)}% / {it(sum(pl), 1)}%"),
             ("Win rate di pareggio", f"{it(100 * be, 1)}%")]
    st = "".join(f"<tr><td>{k}</td><td class='num'>{v}</td></tr>" for k, v in stats)

    rows = [("Config live", "", "live"), ("TWEL 2,5", "_twel25", ""), ("TWEL 2,0", "_twel2", ""), ("Stop-loss HSL acceso", "_hsl", "")]
    trs = []
    for lab, tag, cls in rows:
        try:
            a0, _ = load(f"{name}_0.0{tag}")
            a5, _ = load(f"{name}_0.0005{tag}")
        except IndexError:
            continue
        cells = f"<td>{lab}</td><td class='num'>{pct(a0['adg_strategy_eq'], 2)}</td><td class='num'>{pct(a0['drawdown_worst_strategy_eq'])}</td>" \
                f"<td class='num'>{pct(a5['adg_strategy_eq'], 2)}</td><td class='num hi'>{pct(a5['drawdown_worst_strategy_eq'])}</td>" \
                f"<td class='num'>{it(a5['position_held_days_max'], 1)} g</td>"
        trs.append(f"<tr class='{'base' if cls else ''}'>{cells}</tr>")
    a1, _ = load(f"{name}_0.0001")
    tbl = "".join(trs)
    return f"""<section class="two">
  <div>
    <h2>Win rate e rischio</h2>
    <p class="sub">Cicli dall'apertura alla chiusura completa, netti di commissioni, in % del wallet all'apertura. Le perdite chiuse sono trascurabili: il rischio vero è il drawdown a posizione aperta.</p>
    <div class="tbl"><table><thead><tr><th>Cicli</th><th class="num">Valore</th></tr></thead><tbody>{st}</tbody></table></div>
  </div>
  <div>
    <h2>Sensibilità ai fill</h2>
    <p class="sub">Con <code>limit_order_fill_buffer_pct</code> un ordine limite si riempie solo se il prezzo lo oltrepassa di quel margine. Con 0,01% (≈1 tick) non cambia quasi nulla (ADG {pct(a1['adg_strategy_eq'], 2)}, dd {pct(a1['drawdown_worst_strategy_eq'])}); con 0,05% emerge la coda.</p>
    <div class="tbl wr"><table><thead><tr><th>Variante</th><th class="num">ADG</th><th class="num">DD</th><th class="num">ADG 0,05%</th><th class="num">DD 0,05%</th><th class="num">Held 0,05%</th></tr></thead><tbody>{tbl}</tbody></table></div>
    <p class="sub" style="margin-top:10px">Il drawdown con buffer 0,05% nasce da un solo episodio: il 2 aprile 2025 alle 20:19 UTC, senza buffer, la chiusura trailing esce a 14,04 poco prima del crollo dei dazi; col buffer manca per pochi decimi di centesimo, il bot fa DCA fino al pieno e subisce il crollo. TWEL più basso scala il danno ma non lo elimina; lo stop-loss sull'equity lo contiene al 23-30% al costo di circa un terzo del rendimento (parametri HSL mai ottimizzati).</p>
  </div>
</section>"""


for name in ("hl", "bybit"):
    out = build(name)
    open(f"{ARGS.out}/art_{name}.html", "w").write(out)
    print(name, len(out))
