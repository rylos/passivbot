# Panoramica progetto

Fork di passivbot (bot di trading grid/DCA per futures crypto): https://github.com/rylos/passivbot, upstream https://github.com/enarjord/passivbot. Base v8: core di simulazione in Rust (`passivbot-rust/`, pyo3/maturin), orchestrazione e live in Python (`src/`).

- Branch di lavoro principale: `rylos-4rsi-proto` (prototipo 4RSI, vedi memoria dedicata). Upstream master mergiato periodicamente (ultimo: `5726b901`, 2026-07-26, senza conflitti).
- Architettura v8: HlcvsBundle (T,N,4) f64 [HIGH,LOW,CLOSE,VOLUME]; orchestrator Rust con `SymbolSideInput`; `pbr.run_backtest_bundle`; gruppi config bot (risk/forager/hsl/unstuck/rylos_4rsi) appiattiti via `inject_flattened_shared_bot_side`; bounds optimize con chiavi flat `long_<flat>`.
- Strategia usata in produzione: `trailing_grid_v7`, LONG only su HYPE.
- Attenzione: `format_end_date("now")` = oggi − 2 giorni hardcoded (`src/utils.py`) → per backtest fino a oggi serve `end_date` esplicita.
- Doc del prototipo nel repo: `RYLOS_4RSI_PROTO.md`.

## Infrastruttura (dettagli completi nel wiki Joplin, nota "passivbot")
- Server live "amazon" (`ssh admin@amazon.ziliani.net`, ARM): bot `ry` (Bybit, `/opt/passivbot`, tmux `ry`) e `ry-hl` (Hyperliquid user hyperliquid_vault, `/opt/passivbot-hl`, tmux `ry-hl`).
- Server optimize "debian" (`ssh marco@192.168.0.34`): `/opt/passivbot`, tmux `opt`, 26-29 cpu per gli optimize.
- Su amazon: MAI `venv/bin/pip` (trappola shebang), sempre `venv/bin/python -m pip`; requirements file = `requirements-live.txt`.
