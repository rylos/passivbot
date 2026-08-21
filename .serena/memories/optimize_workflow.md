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
## ⚠️ Non confrontare mai il live con l'adg MEDIO del backtest
Errore in cui sono quasi caduto il 2026-08-22. Misurando il live dal 04/08 al 21/08 (17,16 giorni, 1619 letture di balance dai log, nessun deposito/prelievo): 11.628,41 → 11.825,93 = **+1,70%, adg +0,0982%/g**. Contro l'`adg_usd` +1,0105%/g del backtest di riferimento fa un rapporto di **0,097** — sembra che il live renda un decimo del promesso.
**È un errore di composizione.** Il confronto giusto è col backtest **sulla stessa finestra**: lì fa +1,11% (adg 0,0643%/g, 8 posizioni) contro +1,70% del live (11 posizioni) → **il live ha fatto il 53% MEGLIO**. L'adg medio è una media su 589 giorni che include regimi molto più ricchi; ritagliarne 17 giorni qualsiasi e confrontarli con la media misura il regime, non il degrado.
Regola: **per misurare il degrado live-vs-backtest, rigirare il backtest sulla finestra esatta del live.** Vale anche fra due periodi qualsiasi (in-sample vs out-of-sample): parte del divario è sempre regime, non overfit, e i due contributi si separano solo girando un candidato *non* ottimizzato sulle stesse finestre.

## Limiti noti del nostro metodo (onestà, 2026-08-22)
- **Non facciamo walk-forward né validazione fuori campione**: il candidato è scelto su un fronte costruito su tutta la finestra e misurato sulla stessa finestra. Il 376,9x di `afe61aed` ha dentro overfit **mai quantificato**. L'unica validazione out-of-sample è il live, e 17 giorni con 11 posizioni sono un indizio, non una prova.
- La selezione sul fronte è **manuale** (8 obiettivi in `optimize.scoring` + penalità dure in `optimize.limits`: completion ≥0.99, `drawdown_worst_strategy_eq` ≤0.45). **Nessun criterio di robustezza fra fold o sotto-periodi.**
- **Nessuna mitigazione del mercato in salita**: niente filtro di regime, niente "lascia correre i vincitori", `n_positions` fisso a 1. Con durata mediana 2,83h e uscita a segnale che chiude tutto, in un rialzo dritto si resta strutturalmente indietro al buy&hold. È il costo della difesa, ed è accettato — non risolto.

## Objective aggregato su più scenari: supportato, mai provato
`backtest.scenarios` definisce più scenari e **`backtest.reducer` aggrega le metriche fra loro**. Modi ammessi (`src/config_utils.py:1397-1418`): **`mean`, `min`, `max`, `std`, `median`**, con voci **per singola metrica** che sovrascrivono il default.
Noi usiamo `mean`. Ottimizzare sul **peggior sotto-periodo** (`reducer.default: min` sulle metriche da massimizzare) è quindi **configurazione, non codice** — ma non l'abbiamo mai provato. Cautela se lo si fa: con `min` il segnale diventa molto più rumoroso (un solo scenario sfortunato affonda un candidato buono), convergenza più lenta, `median` come via di mezzo; e gli scenari devono essere **regimi diversi**, altrimenti il "peggior caso" è solo il campione più corto.

## Confronto backtest ↔ live (metodo validato il 2026-08-21)
Serve a rispondere a "il backtest descrive davvero quello che fa il bot?". Config pronta: `configs/bt_vs_live.json` su debian.
- ⚠️ **Hyperliquid non è utilizzabile come fonte per il backtest**: l'API `candleSnapshot` restituisce al massimo ~5000 candele e **non conserva storia 1m oltre ~3,5 giorni** (chiedere agosto o giugno espliciti torna 0 candele — non è un limite di paginazione, i dati non esistono). Il warmup della config live è di **21.905 minuti (~15 giorni)**, quindi la materializzazione fallisce con `HLCV data has no tradable candles after warmup`. Il download "riesce" ma lascia la cache con soli dati recenti: `first_valid_index` altissimo e `invalid_rows` = quasi tutto l'array.
- Quindi il backtest gira su **bybit**, allineando i due parametri che altrimenti falsano il confronto in partenza: `backtest.market_settings.overrides.HYPE.price_step = 0.001` (bybit è passato a 0.01, HL è ancora a 0.001) e `maker_fee_override = 0.00015` (HL ~0.015%, non lo 0.04% dei backtest storici).
- Il codice su debian deve stare **allo stesso commit del live**, altrimenti il confronto non vale.
- I PnL assoluti **non sono confrontabili** (il backtest arriva al giorno del confronto con capitale diverso, quindi size diverse): normalizzare per guadagno % del trade o per pnl/unità.
- ✅ **Esito del 20/08/2026**: 3 trade su 4 combaciano, le **uscite al minuto esatto** (02:30, 15:25, 20:20), gli ingressi entro 1-2 minuti, guadagno per trade 5,19% backtest vs 5,35% live (scarto medio 0,175 punti). Il live ha fatto **un trade in più** (03:25→04:45) che il backtest non ha: atteso, perché RSI/Stoch sono calcolati su prezzi bybit e vicino alla soglia i due exchange divergono.
- Differenza sistematica da tenere presente: nel backtest il `close_panic_long` è eseguito **taker** con slippage, in live è un **limit maker**. Il backtest è quindi leggermente pessimista sulle fee di uscita.

- ⚠️ Il backtest **non scarica** le candele mancanti quando si estende `end_date`: costruisce il dataset da quello che ha e lo marca `partial_window`. Scaricare prima con `PYTHONPATH=src python src/ohlcv_download.py <config> -s HYPE -e binance,bybit -ed <data>`, poi cancellare l'eventuale dataset combinato stale in `caches/hlcvs_data/` e rilanciare.
