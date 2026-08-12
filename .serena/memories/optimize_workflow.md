# Workflow optimize + refinement (server debian, tmux "opt")

## ⚠️ PRIMO PASSO DEL PROSSIMO RUN (in sospeso dal 2026-08-13)
Prima di lanciare il prossimo optimize va riarmato il monitor del fronte di Pareto su debian: il suo baseline è del 04/08 ed è stato prodotto col tick di HYPE vecchio (0.001), quindi confronterebbe candidati calcolati in regimi di tick diversi. Tre cose:
1. **Baseline** = `analysis.json` di un backtest della config live, prodotto **sullo stesso dataset del run** (stessa finestra, stessa `end_date`, stessi metadati di mercato), copiato su `~/pareto_monitor/baseline_live.json`. Se la finestra arriva a oggi servono prima le candele (`src/ohlcv_download.py`, poi cancellare il dataset combinato stale in `caches/hlcvs_data/`). Config pronta: `configs/bt_verify_merge_20260813.json` (è la config live, basta aggiornare `end_date`).
2. **`RUN_DIR`** in `~/pareto_monitor/monitor.py` (riga ~18) è hardcoded e punta ancora al run r3 del 04/08: va fatto puntare alla nuova directory di run.
3. **`~/pareto_monitor/state.json`** va azzerato: contiene `finished: true` (il monitor esce subito) e gli hash dei candidati già notificati.

Metodologia consolidata (dettagli e storico nel wiki Joplin, nota "passivbot"):

1. **Run full-range**: bounds da `get_optimize_bounds_defaults()` con pin strutturali (n_positions [1,1], entry_cooldown [0,0], TWE [2.5,3]) e bounds rylos allargati. 500k iter, 26 cpu, `pareto_max_size` 1000. Esempio: `configs/hype_4rsi_long_v8_r1.json` → run `2026-07-24T09_03_41_..._f1f124cd`.
2. **Analisi manuale** del fronte con `src/tools/pareto_dash_dark.py` (Marco sceglie il candidato).
3. **Refinement ±20%**: bounds = candidato ±20% clampati al range full; pin invariati; TWE resta [2.5,3]; gruppi strategy inattivi RIMOSSI dai bounds (solo trailing_grid_v7); `bot` = candidato come seed; stessa finestra e budget. Esempio: `configs/hype_4rsi_long_v8_refine20_r2.json` → run `2026-07-25T02_49_45_..._65796f56`.
4. Selezione finale di Marco → deploy live (vedi memoria live_deployment).

Note operative:
- Lancio: `tmux send-keys -t opt.0 'cd /opt/passivbot && source venv/bin/activate; python3 src/optimize.py configs/<cfg>.json' C-m`.
- Stop: `pkill -INT -f "src/optimize.py"` (un singolo kill -INT spesso non basta), attendere "Shutdown complete".
- Monitoraggio: `tmux capture-pane -pt opt -S -N` + grep "Iter:"; ~600-730 iter/min con 26 cpu su 722 giorni HYPE → 500k iter ≈ 12-14h.
- ATTENZIONE pgrep via ssh: `pgrep -af pattern` matcha la propria shell ssh — usare `pgrep -f '^python...'` o verificare il comando.
- Backtest fino a oggi: serve `end_date` esplicita (default = oggi−2gg).
- I file in `pareto/` contengono anche `metrics.stats.*` → confronto candidati senza rifare backtest. ⚠️ Lì le metriche sono dict `{mean,min,max}`, non scalari: per confronti automatici usare `metrics.objectives`. Vedi `mem:monitoring_alerting` per il monitor che avvisa su Telegram quando un candidato batte la config live.
- Run r3 (2026-08-04, `configs/hype_4rsi_long_v8_refine20_r3_to20260804.json`): stessi bounds del r2 ma finestra estesa a 733 giorni con candele fino al 04/08.
- ⚠️ **I metadati di mercato nella cache si congelano**: il `cache_hash` del dataset dipende anche dal contenuto di `market_specific_settings.json`, che resta quello del primo run finché qualcosa non invalida la cache. Il 2026-08-13 il merge upstream ha invalidato le cache e rifetchato i metadati, scoprendo che **Bybit ha cambiato il tick di HYPE da 0.001 a 0.01** (verificato via ccxt): da solo spostava adg −3.5% e `drawdown_worst` 0.280 → 0.453. Su **Hyperliquid**, dove gira il live, il tick di HYPE è ancora 0.001, quindi il baseline resta valido per il live ma i backtest su dati bybit ora girano col tick nuovo.
  - Per isolare "codice vs dati" si può pinnare il tick: `backtest.market_settings.overrides.<COIN>.price_step`. Con questo pin il codice post-merge riproduce il baseline entro l'1% (adg −0.10%, drawdown identico, 2 fill di differenza su 5040) → **merge neutro**.
  - Metodo di verifica di un merge: (1) run col codice pre-merge di oggi — deve riprodurre il baseline **bit-identico**, altrimenti il confronto non vale; (2) run col codice post-merge; (3) run post-merge coi metadati pinnati ai valori del baseline. La differenza (2)−(3) è dato, (3)−(1) è codice.
  - Il residuo sotto l'1% viene da `preparation_algorithm_version` 5 → 7 di upstream, che sposta `trade_start_index`/`warmup_minutes`.
- ⚠️ Il backtest **non scarica** le candele mancanti quando si estende `end_date`: costruisce il dataset da quello che ha e lo marca `partial_window`. Scaricare prima con `PYTHONPATH=src python src/ohlcv_download.py <config> -s HYPE -e binance,bybit -ed <data>`, poi cancellare l'eventuale dataset combinato stale in `caches/hlcvs_data/` e rilanciare.
