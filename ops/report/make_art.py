"""Genera la pagina backtest di UNA config (artefatto claude.ai) dal template di ry-bybit.

A differenza di update_art.py (che aggiorna le due pagine storiche) rigenera anche
testata, nota e parametri dalla config del backtest. Uso:

  python3 ops/report/make_art.py --template tpl.html --art DIR --name n4e \
      --end 2026-09-27 --generated 28/09/2026 --out art_4e066c8d.html \
      --title "ry-hl · ry-bybit backtest 4e066c8d" --h1 "ry-hl · ry-bybit" --code 4e066c8d \
      --role "..." --note "..." --compare "ry-bybit precedente=prevby" --compare "ry-hl precedente=prevhl"

DIR contiene i risultati copiati da debian:
  <name>_0.0/*/*/{analysis.json,balance_and_equity.csv.gz,config.json,fills.csv}
  <name>_0.0001, <name>_0.0005, <name>_0.0_twel25 ... (solo analysis.json)
  <tag>_0.0 e <tag>_0.0005 per ogni --compare
"""
import argparse, csv, glob, gzip, json, re
from collections import OrderedDict
from datetime import datetime

ap = argparse.ArgumentParser()
ap.add_argument("--template", required=True)
ap.add_argument("--art", required=True)
ap.add_argument("--name", required=True)
ap.add_argument("--end", required=True, help="ultimo giorno dei dati, YYYY-MM-DD")
ap.add_argument("--generated", required=True, help="data di generazione, GG/MM/AAAA")
ap.add_argument("--out", required=True)
ap.add_argument("--title", required=True)
ap.add_argument("--h1", required=True)
ap.add_argument("--code", required=True)
ap.add_argument("--role", required=True)
ap.add_argument("--note", required=True)
ap.add_argument("--footer", default="")
ap.add_argument("--compare", action="append", default=[], help="etichetta=tag")
ap.add_argument("--cur", default="USDT")
ap.add_argument("--hsl-windows", default="", help="JSON con le finestre in cui scatta lo stop (con/senza HSL)")
ap.add_argument("--hsl-summary", default="", help="JSON: esito delle partenze a freddo con/senza HSL")
ARGS = ap.parse_args()
CUR = ARGS.cur


def it(x, d=2):
    s = f"{x:,.{d}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def pct(x, d=1):
    return it(100 * x, d) + "%"


def load(tag):
    d = sorted(glob.glob(f"{ARGS.art}/{tag}/*/*"))[-1]
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


def replace_tbody(s, h2, body):
    i = s.index(f"<h2>{h2}</h2>")
    j = s.index("<tbody>", i) + len("<tbody>")
    k = s.index("</tbody>", j)
    return s[:j] + body + s[k:]


def params_html(lg):
    r, q, tg = lg["rylos_4rsi"], lg["risk"], lg["strategy"]["trailing_grid_v7"]
    en, cl = tg["entry"], tg["close"]
    group = lambda h, rows: "<div class='pgroup'><h4>" + h + "</h4><dl>" + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows) + "</dl></div>"
    return "".join([
        group("Segnale 4RSI", [("Ingresso: oscillatore &lt;", it(r["osc_entry_threshold"])),
                               ("Ingresso: stocastico &lt;", it(r["entry_stoch_threshold"])),
                               ("Uscita: oscillatore &gt;", it(r["osc_exit_threshold"])),
                               ("Uscita: stocastico &gt;", it(r["exit_stoch_threshold"])),
                               ("Guadagno minimo in uscita", pct(r["exit_min_gain"], 2))]),
        group("Rischio", [("Esposizione totale (TWEL)", it(q["total_wallet_exposure_limit"])),
                          ("Soglia enforcer", it(q["total_exposure_enforcer_threshold"])),
                          ("Eccedenza WE ammessa", "+" + pct(q["we_excess_allowance_pct"], 1)),
                          ("Posizioni", str(int(q["n_positions"])))]),
        group("Griglia di ingresso", [("Primo ingresso (% saldo × WEL)", pct(en["initial_qty_pct"], 2)),
                                      ("Distanza iniziale da EMA", pct(en["initial_ema_dist"], 2)),
                                      ("Spaziatura", pct(en["grid_spacing_pct"], 2)),
                                      ("Fattore raddoppio", it(en["grid_double_down_factor"])),
                                      ("Peso volatilità", it(en["grid_spacing_volatility_weight"])),
                                      ("Peso esposizione", it(en["grid_spacing_we_weight"])),
                                      ("EMA span 0 / 1 (min)", f"{tg['ema_span_0']:.0f} / {tg['ema_span_1']:.0f}")]),
        group("Griglia di chiusura", [("Markup inizio → fine", f"{pct(cl['grid_markup_start'], 2)} → {pct(cl['grid_markup_end'], 2)}"),
                                      ("Quota per gradino", pct(cl["grid_qty_pct"], 0)),
                                      ("Quota trailing", pct(cl["trailing_grid_ratio"], 0)),
                                      ("Trailing soglia / ritraccio", f"{pct(cl['trailing_threshold_pct'], 2)} / {pct(cl['trailing_retracement_pct'], 2)}")]),
    ] + ([group("Stop sull'equity (HSL)", [("Soglia rossa (drawdown)", pct(h["red_threshold"], 0)),
                                         ("Media del drawdown", f"{h['ema_span_minutes']:.0f} min"),
                                         ("Pausa dopo lo stop", f"{h['cooldown_minutes_after_red'] / 60:.0f} h"),
                                         ("Chiusura", h["panic_close_order_type"]),
                                         ("Soglie gialla / arancione", f"{pct(h['tier_ratios']['yellow'] * h['red_threshold'], 1)} / {pct(h['tier_ratios']['orange'] * h['red_threshold'], 1)}")])]
         if (h := lg.get("hsl", {})).get("enabled") else []))


def rome(ts):
    """Timestamp UTC 'YYYY-MM-DD HH:MM' -> ora italiana."""
    from datetime import timezone
    from zoneinfo import ZoneInfo
    d = datetime.fromisoformat(ts).replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Europe/Rome"))
    return d.strftime("%d/%m/%Y alle %H:%M")


def hsl_section(win, summ):
    """Dove scatta lo stop: esito sulle partenze a freddo e le finestre in cui interviene."""
    rows = "".join(
        f"<tr class='{'base' if r['hsl'] else ''}'><td>{r['label']}</td><td class='num'>{pct(r['adg0'], 2)} / {pct(r['adg5'], 2)}</td>"
        f"<td class='num'>{pct(r['dd0'])} / {pct(r['dd5'])}</td><td class='num'>{r['bad']} su {r['n']}</td><td class='num'>{r['rec']:.0f} g</td></tr>"
        for r in summ["rows"])
    cards = []
    for i, w in enumerate(win):
        ev = w["hsl"]["ev"]
        start = w["label"][1:9]
        start = f"{start[6:8]}/{start[4:6]}/{start[:4]}"
        buf = " · buffer 0,05%" if w["label"].endswith("_b5") else ""
        cards.append(f"""<div class="hslw">
      <h3>Partenza {start}{buf}</h3>
      <p class="sub">Stop il {rome(ev['t'])} (ora italiana): chiude {it(ev['qty'], 1)} HYPE a {it(ev['price'])}, perdita {it(-ev['pnl'], 0)} {CUR}, poi {summ['pause_h']} ore di pausa.</p>
      <div class="chart"><div class="legend"><span><i style="background:var(--acc)"></i>Con stop</span><span><i style="background:var(--mute)"></i>Senza stop</span><span><i style="background:var(--neg)"></i>Stop</span></div><div class="box s"><canvas id="hw{i}"></canvas></div></div>
      <dl class="hsld"><dt>Drawdown con / senza stop</dt><dd>{pct(w['hsl']['dd'])} / {pct(w['off']['dd'])}</dd>
      <dt>Equity a fine finestra</dt><dd>{it(w['hsl']['end'], 0)} / {it(w['off']['end'], 0)} {CUR}</dd>
      <dt>Giorni per tornare ai massimi</dt><dd>{w['hsl']['rec']:.0f} / {'mai (liquidato)' if w['off']['dd'] > 0.9 else format(w['off']['rec'], '.0f')}</dd></dl>
    </div>""")
    data = json.dumps([dict(s=w["hsl"]["series"], o=w["off"]["series"], t=w["hsl"]["ev"]["t"][:13]) for w in win], separators=(",", ":"))
    return f"""<section>
  <h2>Stop sull'equity: dove scatta</h2>
  <p class="sub">{summ['intro']}</p>
  <div class="tbl wr" style="max-height:none;margin-bottom:16px"><table><thead><tr><th>Variante</th><th class="num">ADG buffer 0 / 0,05%</th><th class="num">DD max</th><th class="num">Finestre oltre il 40%</th><th class="num">Recupero max</th></tr></thead><tbody>{rows}</tbody></table></div>
  <div class="hslgrid">{"".join(cards)}</div>
</section>
<script>const HSLW={data};</script>"""


HSL_JS = """<script>
(function(){
  const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  let hc=[];
  const vline={id:'vline',afterDatasetsDraw(c,a,o){const i=o.idx;if(i<0)return;const x=c.scales.x.getPixelForValue(i);const g=c.ctx;g.save();g.strokeStyle=o.color;g.lineWidth=1.5;g.setLineDash([4,3]);g.beginPath();g.moveTo(x,c.chartArea.top);g.lineTo(x,c.chartArea.bottom);g.stroke();g.restore();}};
  function hbuild(){
    hc.forEach(c=>c.destroy());hc=[];
    const acc=css('--acc'),mute=css('--mute'),neg=css('--neg'),grid=css('--grid');
    HSLW.forEach((w,i)=>{
      const lab=w.s.map(p=>p[0]);const om=Object.fromEntries(w.o.map(p=>[p[0],p[1]]));
      const idx=lab.findIndex(t=>t>=w.t);
      hc.push(new Chart(document.getElementById('hw'+i),{type:'line',data:{labels:lab,datasets:[
        {label:'Con stop',data:w.s.map(p=>p[1]),borderColor:acc,borderWidth:2,pointRadius:0,pointHitRadius:10,tension:0},
        {label:'Senza stop',data:lab.map(t=>om[t]??null),borderColor:mute,borderWidth:1.5,borderDash:[5,4],pointRadius:0,pointHitRadius:10,tension:0,spanGaps:true}]},
        options:{animation:false,responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},
          plugins:{legend:{display:false},vline:{idx,color:neg},tooltip:{mode:'index',intersect:false,displayColors:false,callbacks:{label:c=>`${c.dataset.label}: ${Math.round(c.parsed.y).toLocaleString('it-IT')}`}}},
          scales:{x:{ticks:{autoSkip:false,maxRotation:0,callback:(v,j)=>{const t=lab[j];return t&&t.slice(8,13)==='01 00'?t.slice(0,7):null}},grid:{color:grid,drawTicks:false},border:{display:false}},
                  y:{grid:{color:grid,drawTicks:false},border:{display:false},ticks:{callback:v=>v.toLocaleString('it-IT'),font:{family:'"JetBrains Mono",monospace'}}}}},plugins:[vline]}));
    });
  }
  hbuild();
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change',hbuild);
  new MutationObserver(hbuild).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
})();
</script>"""

HSL_CSS = """.hslgrid{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}
.hslw h3{font-size:14px;margin:0 0 4px;font-weight:600}
.hslw .sub{font-size:13px;min-height:3.2em}
.hsld{margin-top:10px}
.params.p5{grid-template-columns:repeat(5,1fr)}
@media (max-width:900px){.hslgrid,.params.p5{grid-template-columns:1fr}}
"""


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

    rows = [(f"Questa config ({ARGS.code})", f"{name}_0.0", f"{name}_0.0005", "base"),
            ("TWEL 2,5", f"{name}_0.0_twel25", f"{name}_0.0005_twel25", ""),
            ("TWEL 2,0", f"{name}_0.0_twel2", f"{name}_0.0005_twel2", "")]
    rows += [(lab, f"{tag}_0.0", f"{tag}_0.0005", "") for lab, tag in (c.split("=", 1) for c in ARGS.compare)]
    trs = []
    for lab, t0, t5, cls in rows:
        try:
            a0, _ = load(t0)
            a5, _ = load(t5)
        except IndexError:
            continue
        trs.append(f"<tr class='{cls}'><td>{lab}</td><td class='num'>{pct(a0['adg_strategy_eq'], 2)}</td><td class='num'>{pct(a0['drawdown_worst_strategy_eq'])}</td>"
                   f"<td class='num'>{pct(a5['adg_strategy_eq'], 2)}</td><td class='num hi'>{pct(a5['drawdown_worst_strategy_eq'])}</td>"
                   f"<td class='num'>{it(a5['position_held_days_max'], 1)} g</td></tr>")
    a0, _ = load(f"{name}_0.0")
    a1, _ = load(f"{name}_0.0001")
    a5, _ = load(f"{name}_0.0005")
    return f"""<section class="two">
  <div>
    <h2>Win rate e rischio</h2>
    <p class="sub">Cicli dall'apertura alla chiusura completa, netti di commissioni, in % del wallet all'apertura. Le perdite chiuse sono trascurabili: il rischio vero è il drawdown a posizione aperta.</p>
    <div class="tbl"><table><thead><tr><th>Cicli</th><th class="num">Valore</th></tr></thead><tbody>{st}</tbody></table></div>
  </div>
  <div>
    <h2>Sensibilità ai fill</h2>
    <p class="sub">Con <code>limit_order_fill_buffer_pct</code> un ordine limite si riempie solo se il prezzo lo oltrepassa di quel margine. Con 0,01% (≈1 tick): ADG {pct(a1['adg_strategy_eq'], 2)}, dd {pct(a1['drawdown_worst_strategy_eq'])}; con 0,05%: ADG {pct(a5['adg_strategy_eq'], 2)}, dd {pct(a5['drawdown_worst_strategy_eq'])}.</p>
    <div class="tbl wr"><table><thead><tr><th>Variante</th><th class="num">ADG</th><th class="num">DD</th><th class="num">ADG 0,05%</th><th class="num">DD 0,05%</th><th class="num">Held 0,05%</th></tr></thead><tbody>{"".join(trs)}</tbody></table></div>
    <p class="sub" style="margin-top:10px">Le config precedenti dipendevano da un'uscita trailing riuscita per un soffio il 2 aprile 2025 (col buffer 0,05% il drawdown saliva al 78-80%). Questa config è stata ottimizzata con e senza buffer su 18 partenze sfasate: il drawdown quasi non cambia fra i due casi.</p>
  </div>
</section>"""


s = open(ARGS.template).read()
name = ARGS.name
a, d = load(f"{name}_0.0")
cfg = json.load(open(d + "/config.json"))
fills = list(csv.DictReader(open(d + "/fills.csv")))
rows = list(csv.DictReader(gzip.open(d + "/balance_and_equity.csv.gz", "rt")))
cyc = cycles_of(fills)

# serie a 4 ore: ultimo valore della finestra, drawdown minimo nella finestra
buck, peak = OrderedDict(), 0.0
for r in rows:
    t = r[""][:13]
    key = f"{t[:11]}{int(t[11:13]) // 4 * 4:02d}"
    e, b = float(r["strategy_equity"]), float(r["usd_total_balance"])
    peak = max(peak, e)
    dd = e / peak - 1
    if key not in buck:
        buck[key] = dict(t=key, e=e, b=b, dd=dd)
    else:
        x = buck[key]
        x["e"], x["b"], x["dd"] = e, b, min(x["dd"], dd)
series = [dict(t=x["t"], e=round(x["e"], 2), b=round(x["b"], 2), dd=round(x["dd"], 4)) for x in buck.values()]
e_end = series[-1]["e"]

monthly = OrderedDict()
for r in fills:
    monthly[r["timestamp"][:7]] = monthly.get(r["timestamp"][:7], 0.0) + float(r["pnl"]) + float(r["fee_paid"])
eq_month = OrderedDict((r[""][:7], float(r["strategy_equity"])) for r in rows)

ndays = a["n_days"]
gain = e_end / 10000
cagr = gain ** (365 / ndays) - 1
wins = [c for c in cyc if c["pct"] > 0]
loss = [c for c in cyc if c["pct"] <= 0]

# --- titolo, testata, nota
s = re.sub(r"<title>.*?</title>", f"<title>{ARGS.title}</title>", s, count=1)
s = re.sub(r"2024-12-05 → 2026-\d\d-\d\d", f"2024-12-05 → {ARGS.end}", s)
s = re.sub(r"<h1>.*?</h1>", f"<h1>{ARGS.h1} <code>{ARGS.code}</code></h1>", s, count=1, flags=re.S)
s = re.sub(r'<p class="role">.*?</p>', f'<p class="role">{ARGS.role}</p>', s, count=1, flags=re.S)
s = re.sub(r'<p class="note">.*?</p>', f'<p class="note">{ARGS.note}</p>', s, count=1, flags=re.S)
s = re.sub(r'<div class="stamp">.*?</div>',
           f'<div class="stamp">{round(ndays)} giorni · {len(fills)} fill · {len(cyc)} cicli<br>'
           f'saldo iniziale <b>10.000 {CUR}</b> · fee maker 0,015% / taker 0,055%<br>generato il {ARGS.generated}</div>',
           s, count=1, flags=re.S)
kp = lambda l, v, sub: f"<div class='kpi'><div class='l'>{l}</div><div class='v'>{v}</div><div class='s'>{sub}</div></div>"
kpis = "".join([
    kp("Guadagno", it(gain, 1) + "×", f"10.000 → {it(e_end, 0)} {CUR}"),
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
    cls = "neg" if net < 0 else ""
    trs.append(f"<tr><td>{m}</td><td class='num {cls}'>{it(net, 0)}</td><td class='num {cls}'>{pct(net / prev)}</td>"
               f"<td class='num'>{it(eq_month[m], 0)}</td></tr>")
    prev = eq_month[m]
s = replace_tbody(s, "Per mese", "".join(trs))

# --- metriche complete
M = [("ADG (equity strategia)", pct(a["adg_strategy_eq"], 3)), ("ADG pesato sul recente", pct(a["adg_strategy_eq_w"], 3)),
     ("MDG (mediana giornaliera)", pct(a["mdg_strategy_eq"], 3)), ("Guadagno (×)", it(a["gain_strategy_eq"], 3)),
     ("Drawdown peggiore", pct(a["drawdown_worst_strategy_eq"], 3)), ("Drawdown, media peggior 1%", pct(a["drawdown_worst_mean_1pct_strategy_eq"], 3)),
     ("Sharpe", it(a["sharpe_ratio_strategy_eq"], 3)), ("Sortino", it(a["sortino_ratio_strategy_eq"], 3)),
     ("Calmar", it(a["calmar_ratio_strategy_eq"], 3)), ("Giorni max per recuperare un massimo", it(a["strategy_eq_recovery_days_max"], 3)),
     ("Posizione più lunga (giorni)", it(a["position_held_days_max"], 3)), ("Durata media posizione (giorni)", it(a["position_held_days_mean"], 3)),
     ("Perdite / profitti", it(a["loss_profit_ratio"], 3)), ("Tempo medio sott'acqua", pct(a["strategy_eq_underwater_pct_mean"], 3)),
     ("Volume medio giornaliero (% wallet)", pct(a["volume_pct_per_day_avg"], 3)), ("Posizioni per giorno", it(a["positions_held_per_day"], 3)),
     ("Quota tempo esposto", pct(a["exposure_ratio_usd"], 3)), ("Completamento backtest", pct(a["backtest_completion_ratio"], 3)),
     ("Hard stop per anno", it(a["hard_stop_restarts_per_year"], 3)), ("Giorni con fill", pct(a["fills_active_days_ratio"], 3)),
     ("Ore medie fra ingressi", it(a["entry_interval_hours_mean"], 3)), ("Ore max fra ingressi", it(a["entry_interval_hours_max"], 3))]
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

# --- win rate / sensibilità ai fill, parametri
s = re.sub(r'<section class="two">\s*<div>\s*<h2>Win rate e rischio</h2>.*?</section>\n?', "", s, count=1, flags=re.S)
s = s.replace("<section>\n  <h2>Parametri della config</h2>", risk_section(name, cyc, wins, loss) + "\n<section>\n  <h2>Parametri della config</h2>", 1)
hsl_on = cfg["bot"]["long"].get("hsl", {}).get("enabled")
s = re.sub(r'<div class="params">.*?</dl></div></div>', lambda _: f'<div class="params{" p5" if hsl_on else ""}">{params_html(cfg["bot"]["long"])}</div>', s, count=1, flags=re.S)
if ARGS.hsl_windows:
    win = json.load(open(ARGS.hsl_windows))
    summ = json.loads(open(ARGS.hsl_summary).read())
    s = s.replace("<section>\n  <h2>Parametri della config</h2>", hsl_section(win, summ) + "\n<section>\n  <h2>Parametri della config</h2>", 1)
    s = s.replace("</style>", HSL_CSS + "</style>", 1)
    s = s.replace("</body></html>", HSL_JS + "\n</body></html>", 1) if "</body></html>" in s else s + HSL_JS

# --- dati grafici e piè di pagina
data = json.dumps({"series": series, "monthly": monthly}, separators=(",", ":"))
s = re.sub(r"const DATA=\{.*?\};\n", lambda _: f"const DATA={data};\n", s, count=1, flags=re.S)
if ARGS.footer:
    s = re.sub(r"<footer>.*?</footer>", f"<footer>{ARGS.footer}</footer>", s, count=1, flags=re.S)
open(ARGS.out, "w").write(s)
print(ARGS.out, len(s))
