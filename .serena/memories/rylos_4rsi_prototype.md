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

## Vincoli noti
- `candle_interval_minutes` deve restare 1.
- `exit_min_gain` è sul PREZZO (0.0103 ≈ min_profit 4.1% / leva 4 di freqtrade).
- Allineamento no-lookahead: valori 5m disponibili alla riga 1m che chiude la candela (minute_idx % 5 == 4).
- Dopo l'exit il bot resta flat finché non torna il segnale d'ingresso (diverso dal master che rientra subito).
