# Prototipo RyLoS 4RSI (branch rylos-4rsi-proto)

Porta in passivbot v8 l'entry della strategia RyLoS Classic di freqtrade (`~/dev/freqtrade/user_data/strategies/`) e l'exit 4RSI, timeframe 5m, solo lato long. Doc completa: `RYLOS_4RSI_PROTO.md` in root.

## Segnale
- `osc_4rsi` = media(RSI2, RSI7, RSI14) − 50 (Wilder, seed compatibile talib, match < 1e-13).
- `stoch_k` = fast %D di STOCHF(14,3) = SMA(3) dello stocastico raw.
- Colore candela 5m: open = close della 5m precedente (i dati HLCV non hanno open).
- Entry gate (solo initial entry, size==0): osc < soglia AND stoch < soglia AND candela rossa.
- Exit: osc > soglia AND stoch > soglia AND candela verde AND gain prezzo > `exit_min_gain` → chiusura totale via `calc_panic_close` (`close_panic_long` = limit aggressivo a 1 tick sotto il best ask, NON market; vedi `orchestrator.rs::calc_panic_close`).

## Architettura
- Indicatori precalcolati in Python: `src/rylos_signal.py` (backtest: array (T,N,3) con warmup NaN; live: `compute_rylos_signal_live`, min 100 candele 5m ≈ 8h20m di storico, scaricato all'avvio).
- Soglie in Rust: `BotParams` campi `rylos_*` (`types.rs`), gruppo config `bot.long.rylos_4rsi` (`src/config/shared_bot.py`, `schema.py`), ottimizzabili via `optimize.bounds.long.rylos_4rsi.*` (`optimize_bounds.py`; default pinnati lo=hi ai valori config freqtrade 5371 → zero dimensioni extra se non allargati).
- Gate unico nell'orchestrator Rust (`rylos_entry_allowed` / `rylos_exit_triggered`), identico backtest/live. Segnale mancante/NaN → blocca solo l'initial entry (fail-closed).
- Live: stateless e restart-safe — ricalcolo a ogni ciclo dalle candele 1m del CandlestickManager (`_compute_rylos_signals` in `src/passivbot.py`).
- `enabled: false` (default) ≡ comportamento master identico, verificato.
- Cache indicatori nell'optimizer: `_rylos_indicators_cache` module-level in `src/backtest.py` (chiave: id hlcvs + shape + primo ts + config).

## Patch reconciler (dal merge upstream del 2026-08-13, commit `d1b352eb`)
Upstream valida ogni ordine prodotto da Rust contro l'input inviato e rifiuta la famiglia `close_panic_*` quando la modalità del lato non è `panic` (`src/live/reconciler.py`, `_validate_rust_order_family_for_submitted_mode`) → `FatalBotException`, processo morto. Siccome l'uscita 4RSI usa `calc_panic_close` restando in modalità normale, senza patch il bot muore **al primo segnale di uscita** (non all'avvio: invisibile ai test e allo smoke test di deploy).
- Fix: il reconciler legge `rylos_4rsi_enabled` dai `bot_params` già inviati a Rust (`_bot_params_to_rust_dict`) e accetta la famiglia panic fuori da modalità panic solo per quel symbol/side, nelle modalità `normal`/`graceful_stop`/`tp_only` (Rust emette l'uscita per ogni modalità non-manual). Restano attivi tutti gli altri invarianti panic: quantità = posizione intera, prezzo limite verificato contro il book.
- Test: `tests/test_rylos_4rsi_panic_close.py` (5 casi, incluso "panic close ancora rifiutato con 4RSI spento").
- ⚠️ `reconciler.py` è un file che upstream tocca spesso: aspettarsi attrito a ogni merge futuro. Se i test di quel file falliscono dopo un merge, guardare prima lì.
- Valutata e scartata una famiglia d'ordine dedicata (`close_rylos_*`): richiederebbe enum Rust + mappa custom_id + tutti i validatori per prefisso + contabilità fill in backtest/analysis, e perderebbe i comportamenti impliciti di `_order_is_panic` (priorità `risk_critical`, esenzione churn gate). Più superficie di divergenza, non meno.

## Caratterizzazione del comportamento (misurata il 2026-08-21)
Su 68 posizioni di un backtest giugno→agosto 2026:
- **L'uscita 4RSI domina**: **68 `close_panic_long` contro 12 `close_grid_long`**. La griglia di chiusura di `trailing_grid_v7` è quasi decorativa — chi chiude le posizioni è l'oscillatore.
- **Gradini di griglia riempiti**: media **3,25**, mediana 1, **max 12** (36 posizioni su 68 chiudono al primo gradino). Durata posizione: mediana 2,83h, media 4,76h, max 95,75h.
- ⚠️ Conseguenza da ricordare quando si ragiona sui bounds: la profondità teorica della griglia a budget TWE esaurito è ~17 gradini (formula `n = log(1 + TWE/(first·leva)·(mult−1))/log(mult)`, con `initial_qty_pct` 0.00812 e double-down 1.32), ma se ne osservano 12 perché **l'uscita 4RSI arriva prima che il budget si saturi**. Qualsiasi ragionamento sulla griglia che ignori l'uscita sovrastima i gradini reali.

## Comportamento live degli ingressi (osservato 13-15/08/2026)
Il gate d'ingresso vale per **una sola candela 5m**: il bot piazza un `entry_initial_normal_long` alla chiusura della candela che soddisfa il segnale e lo **ritira** (`reasons=retire`) quando la candela successiva non lo conferma. La finestra utile per il fill è quindi di ~5 minuti, e il limite sta sotto il mercato: serve un ritracciamento dello 0.2-0.9% dentro quei 5 minuti.
- In un drift al rialzo si possono accumulare giorni senza un solo fill pur piazzando decine di ordini al giorno (47 ordini in 2 giorni, zero fill, il più vicino mancato per 0.18%). **Non è un guasto**: prima di sospettare il codice, misurare.
- Ricetta di diagnosi: estrarre dal log le righe `post HYPE | buy long <qty>@<prezzo> entry_initial_normal_long` con il loro timestamp, scaricare le candele 1m da ccxt e confrontare il prezzo dell'ordine col **minimo dei 5 minuti successivi**. Se il gap è positivo il prezzo non è mai sceso al limite. Confrontando la stessa statistica prima e dopo un deploy si verifica anche che il pricing degli ingressi non sia cambiato (13/08: mediana +0.85% prima, +0.53% dopo → invariato nella sostanza).
- ⚠️ Riferimento per capire se un periodo flat è anomalo: nel backtest `entry_interval_hours` ha mediana 10h, p95 ~40h, p99 ~62h.
- ✅ **L'uscita 4RSI è scattata in live la prima volta il 2026-08-20 alle 02:30Z, e la patch ha retto**: `close_panic_long` emesso con il lato in modalità **normale**, accettato dal reconciler, nessun `FatalBotException` né `order family inconsistent`, processo vivo con PID invariato. È esattamente lo scenario che senza la patch del 13/08 avrebbe ucciso il bot **con posizione aperta**. Il percorso non è più solo teoria: è validato sul campo.
  - Trade completo: entrata `entry_initial_normal_long` 15.28 HYPE @ 68.639 (01:16Z) → uscita in 4 fill @ 69.873/69.884 (02:30-02:31Z), durata 1h14m, **+17.89 USDC netti** (11709.64 → 11727.53). Chiusura totale, nessun residuo, posizione a zero.
  - Da notare: l'uscita è arrivata in 2 ondate (l'ordine da 15.28 riempito in parte, poi ripiazzato per i 7.3 residui con `replace reason=qty Δq=109%`). La riga `missing order ... src=fetch_open_orders` in mezzo è normale: l'ordine era già stato consumato dal fill.

## Vincoli noti
- `candle_interval_minutes` deve restare 1.
- `exit_min_gain` è sul PREZZO (0.0103 ≈ min_profit 4.1% / leva 4 di freqtrade).
- Allineamento no-lookahead: valori 5m disponibili alla riga 1m che chiude la candela (minute_idx % 5 == 4).
- Dopo l'exit il bot resta flat finché non torna il segnale d'ingresso (diverso dal master che rientra subito).
