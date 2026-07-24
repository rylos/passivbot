# RyLoS Multi-Oscillator Entry Signal — Implementazione

## Obiettivo

Sostituire il first entry di Passivbot (basato solo su EMA band) con il segnale multi-oscillatore oversold di RyLoSStrategy.py. I re-entry (DCA/grid/trailing) restano invariati.

## Logica RyLoS (da `populate_entry_trend`)

Entry long solo quando:
1. Almeno N indicatori su 4 sono in oversold (default N=2)
2. La candela è bearish (close < open)

Indicatori (su candele 5m):
- RSI(10) < 25.333
- Bollinger Bands %B(20) < 0.294
- Stochastic RSI(10, 5, 3) < 0.782
- Williams %R(10) < -74.991

## Architettura implementata

Un flag `initial_entry_allowed: bool` viene aggiunto a `StateParams` (Rust). Quando è `false`, le funzioni di entry restituiscono un ordine vuoto se `position.size == 0`. Il segnale viene calcolato in Python (numpy puro, no talib) e passato al Rust sia per backtest che per live.

```
Python (signal computation) → Rust (entry gating)
                                ↓
                    initial_entry_allowed = false → Order::default()
                    initial_entry_allowed = true  → normal EMA-based entry
```

## File modificati

### Rust

| File | Modifica |
|------|----------|
| `passivbot-rust/src/types.rs` | Aggiunto `initial_entry_allowed: bool` a `StateParams` (default `true`) |
| `passivbot-rust/src/entries.rs` | Gate su `initial_entry_allowed` in tutte e 4 le funzioni di initial entry (grid_long, grid_short, trailing_long, trailing_short). Sia normal che partial initial entry sono gatati |
| `passivbot-rust/src/orchestrator.rs` | Aggiunto `initial_entry_allowed: bool` a `SymbolSideInput` (serde default `true`). Passato a `StateParams` in entrambe le costruzioni (long ~riga 1611, short ~riga 1884) |
| `passivbot-rust/src/backtest.rs` | Aggiunto `entry_signal: Option<ArrayView2<u8>>` alla struct `Backtest`, setter `set_entry_signal()`, lettura per `(k, idx)` in `build_orchestrator_input_iter`. Long usa il segnale, short sempre `true` |
| `passivbot-rust/src/python.rs` | Aggiunto `PyReadonlyArray2` import. Lettura opzionale di `entry_signal` da `backtest_params_dict` in `run_backtest_core`, con validazione shape |

### Python

| File | Modifica |
|------|----------|
| `src/entry_signal.py` | **NUOVO** — Implementazione numpy-only di RSI, BB%B, StochRSI, Williams %R. Aggregazione 1m→5m. Due funzioni pubbliche: `compute_entry_signal_for_backtest(hlcvs, config)` → array uint8, `compute_entry_signal_live(candles_1m, config)` → bool |
| `src/backtest.py` | In `execute_backtest()`: se `config["entry_signal"]["enabled"]`, computa il segnale e lo aggiunge a `backtest_params["entry_signal"]` prima di chiamare il Rust |
| `src/passivbot.py` | In `calc_ideal_orders_orchestrator()`: computa il segnale per ogni simbolo usando le candele dal CandlestickManager, passa `initial_entry_allowed` nel dict dell'orchestrator input. Solo long è gatato; short sempre `True` |
| `src/config_utils.py` | Aggiunta sezione `entry_signal` al template config (disabled by default) |
| `configs/template.json` | Aggiunta sezione `entry_signal` con parametri RyLoS ottimizzati |

## Configurazione

Sezione `entry_signal` nel config JSON (top-level, accanto a `bot`, `live`, ecc.):

```json
"entry_signal": {
    "enabled": true,
    "timeframe_minutes": 5,
    "rsi_period": 10,
    "rsi_oversold": 25.333,
    "bb_period": 20,
    "bb_oversold": 0.294,
    "stochrsi_period": 10,
    "stochrsi_fastk": 5,
    "stochrsi_fastd": 3,
    "stochrsi_oversold": 0.782,
    "williams_period": 10,
    "williams_oversold": -74.991,
    "min_oversold_count": 2
}
```

Disabilitato di default (`"enabled": false`) per backward compatibility. Quando disabilitato, il comportamento è identico al Passivbot originale.

## Stato attuale

- [x] types.rs — `initial_entry_allowed` in `StateParams`
- [x] entries.rs — gate su tutte e 4 le funzioni di initial entry
- [x] orchestrator.rs — `initial_entry_allowed` in `SymbolSideInput`, threading a `StateParams`
- [x] backtest.rs — `entry_signal` array opzionale, lettura in `build_orchestrator_input_iter`
- [x] python.rs — lettura `entry_signal` da `backtest_params_dict`
- [x] entry_signal.py — calcolo indicatori numpy-only
- [x] backtest.py — integrazione segnale nel backtest
- [x] passivbot.py — integrazione segnale nel live trading
- [x] config_utils.py + template.json — parametri configurabili
- [ ] **Build Rust extensions** (`cd passivbot-rust && maturin develop --release`)
- [ ] Test backtest con `"entry_signal": {"enabled": true}`
- [ ] Test live (dry run)

## Come riprendere

1. Creare/attivare il venv Python 3.11
2. `cd passivbot-rust && maturin develop --release` — compilare le estensioni Rust
3. Se ci sono errori di compilazione, controllare i file Rust modificati sopra
4. Testare con un backtest: aggiungere `"entry_signal": {"enabled": true}` al config e lanciare `python3 src/backtest.py path/to/config.json`

## Note tecniche

- Gli indicatori sono calcolati con numpy puro (nessuna dipendenza da talib)
- L'aggregazione 1m→5m usa reshape: le candele vengono raggruppate in blocchi di 5
- Il segnale è applicato solo al lato **long**. Short mantiene il comportamento originale (sempre `true`)
- Per il backtest, il segnale è pre-calcolato come array `(n_timesteps, n_coins)` uint8 e passato al Rust
- Per il live, il segnale è calcolato on-the-fly dalle ultime ~150 candele 1m (30 × timeframe_minutes)
