# RyLoS 4RSI — prototipo entry/exit signal per passivbot v8

Branch: `rylos-4rsi-proto` (base: upstream master `957ba83b`).

Porta in passivbot l'**entry** della strategia freqtrade RyLoS Classic (config
5371, vedi `RyLoSStrategy.md` nel repo freqtrade) e l'**exit 4RSI overbought**,
su timeframe 5m, con soglie ottimizzabili dall'optimizer di passivbot.

## Segnale (candele 5m aggregate dalle 1m)

| Serie | Definizione |
|---|---|
| `osc_4rsi` | avg(RSI2, RSI7, RSI14) − 50 (Wilder, identico a talib, diff < 1e-13) |
| `stoch_k` | fast %D di STOCHF(14, 3) = SMA(3) dello stocastico grezzo |
| `candle_color` | segno di (close 5m − open 5m); open = close della 5m precedente (solo HLCV disponibile) |

**Entry gate** (solo initial entry long, `position.size == 0`):
`osc_4rsi < osc_entry_threshold` AND `stoch_k < entry_stoch_threshold` AND candela rossa.
L'ancoraggio EMA della 5371 (`initial_ema_dist`) NON è replicato qui: esiste già
nativo in passivbot (`entry_initial_ema_dist` / ema_gate della strategia attiva).
Re-entry/DCA, trailing, unstuck, close: invariati.

**Exit 4RSI** (chiusura totale forzata, ordine `close_panic_long`):
`osc_4rsi > osc_exit_threshold` AND `stoch_k > exit_stoch_threshold` AND candela
verde AND `(prezzo − pprice)/pprice > exit_min_gain`.
Nota mapping: il `min_profit_for_overbought_exit = 0.041` freqtrade è sullo stake
a leva 4 → in passivbot è **sul prezzo**: default `exit_min_gain = 0.0103`.

**Allineamento (no lookahead)**: i valori di una candela 5m diventano disponibili
alla riga 1m che la chiude (minuto % 5 == 4, wall-clock) e restano validi per i 5
minuti successivi — equivale a freqtrade che agisce sulla candela chiusa.
Warmup (prime ~16 candele 5m): segnale NaN → initial entry bloccata, tutto il
resto opera normalmente.

## Configurazione

Nuovo gruppo `bot.long.rylos_4rsi` (e `bot.short`, ignorato: il segnale gestisce
solo il lato long):

```json
"rylos_4rsi": {
  "enabled": false,
  "osc_entry_threshold": -10.028,
  "entry_stoch_threshold": 36.222,
  "osc_exit_threshold": 24.845,
  "exit_stoch_threshold": 73.05,
  "exit_min_gain": 0.0103
}
```

Default = candidato 5371. `enabled: false` di default → comportamento identico a
master (verificato: stesso numero di fill e stessa equity su run sintetico).
Periodi indicatori fissi (RSI 2/7/14, stoch 14/3, tf 5m), sovrascrivibili con una
sezione top-level opzionale `rylos_signal` (`timeframe_minutes`, `rsi_periods`,
`stoch_period`, `stoch_smooth`).

Bounds optimize (default, sezione `optimize.bounds.long.rylos_4rsi`):

```
osc_entry_threshold   [-40, -10]     entry_stoch_threshold [10, 40]
osc_exit_threshold    [10, 40]       exit_stoch_threshold  [60, 90]
exit_min_gain         [0.0025, 0.025]
```

`enabled` non è ottimizzabile (si fissa a true nel config dell'optimize).

## Architettura

Le **soglie vivono in Rust** (`BotParams`), gli **indicatori in Python**
(`src/rylos_signal.py`, numpy puro): la logica di gating è una sola,
nell'orchestrator, identica per backtest e live.

- **Backtest**: `build_backtest_payload` precalcola l'array `(T, N, 3)`
  `[osc_4rsi, stoch_k, candle_color]` per riga 1m e lo passa come
  `backtest_params["rylos_indicators"]`. Cache per processo: nell'optimize gli
  indicatori si calcolano **una volta sola** e si riusano a ogni valutazione
  (dipendono solo dalle candele, non dai parametri).
  Richiede `candle_interval_minutes = 1`.
- **Rust**: `Backtest` legge l'array alla riga `k`; l'orchestrator riceve
  `rylos_signal {osc_4rsi, stoch_k, candle_color}` in `SymbolSideInput.long` e
  applica le soglie: gate su `allow_initial`, exit → `calc_panic_close`.
- **Live**: `calc_ideal_orders_orchestrator` calcola il segnale a ogni ciclo
  dalle candele 1m del CandlestickManager (ultima candela 5m *chiusa*, esclusa
  la 1m in corso) e lo inserisce nell'input JSON. **Stateless**: nessun file di
  stato, restart con posizione aperta gestito come master (il segnale si
  ricalcola, la posizione arriva dall'exchange). Serve ≥100 candele 5m di
  storico (~8h20m, scaricate all'avvio in pochi secondi); se mancano, viene
  bloccata solo l'initial entry (fail-closed) con warning nel log.

### File toccati

| File | Cosa |
|---|---|
| `passivbot-rust/src/types.rs` | 6 campi `rylos_*` in `BotParams` (serde default, disabled) |
| `passivbot-rust/src/python.rs` | parsing campi + lettura/validazione `rylos_indicators` |
| `passivbot-rust/src/orchestrator.rs` | `RylosSignalInput`, campo in `SymbolSideInput`, `rylos_entry_allowed`, `rylos_exit_triggered`, innesti nel loop long |
| `passivbot-rust/src/backtest.rs` | array indicatori, `rylos_signal_at(k, coin)` nel build input |
| `src/rylos_signal.py` | indicatori numpy (testati vs talib), aggregazione 5m, API backtest+live |
| `src/backtest.py` | `_maybe_add_rylos_indicators` + cache |
| `src/passivbot.py` | `_compute_rylos_signals`, campi bot params, attach al lato long |
| `src/config/{shared_bot,schema,optimize_bounds,param_paths}.py` | gruppo config, defaults, bounds, path optimizer |

## Limiti noti del prototipo

- Solo lato **long** (la RyLoS è long-only); short invariato.
- `calc_ideal_orders_orchestrator_from_snapshot` (tool/doctor) non calcola il
  segnale: con `enabled: true` quel percorso blocca le initial entry (fail-closed).
- Open 5m ≈ close 5m precedente (i dati backtest sono HLCV, senza open); in live
  si usa la stessa convenzione per coerenza col backtest.
- L'exit usa ordine tipo panic (`close_panic_long`), prezzo `ask − price_step`.

## Test eseguiti (pc-work, sintetici)

- Indicatori vs talib: diff < 1e-13 (RSI 2/7/14, STOCHF fastd).
- Allineamento no-lookahead e disponibilità solo a candela chiusa.
- Live == backtest sullo stesso istante; guard warmup live.
- E2E `run_backtest_bundle`: disabled ≡ baseline; soglia impossibile → 0 fill;
  exit 4RSI → fill `close_panic_long`.

## Test su debian (tmux `opt`)

1. `git fetch origin && git checkout rylos-4rsi-proto`
2. `cd passivbot-rust && maturin develop --release`
3. Backtest HYPE con `enabled: false` → deve coincidere col baseline master.
4. Backtest con `enabled: true` (default 5371) → entry solo su oversold.
5. Optimize breve con bounds `rylos_4rsi` per verificare che l'optimizer muova le soglie.
