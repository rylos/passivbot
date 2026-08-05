# Panoramica progetto

Fork di passivbot (bot di trading grid/DCA per futures crypto): https://github.com/rylos/passivbot, upstream https://github.com/enarjord/passivbot. Base v8: core di simulazione in Rust (`passivbot-rust/`, pyo3/maturin), orchestrazione e live in Python (`src/`).

- Branch di lavoro principale: `rylos-4rsi-proto` (prototipo 4RSI, vedi `mem:rylos_4rsi_prototype`). Upstream master mergiato periodicamente (ultimo: 2026-08-04, 284 commit fino a `24081f14`, merge `93431faa`; conflitti solo su CHANGELOG.md e docs/ai/features/fill_events_manager.md, risolti prendendo upstream).
- Tutto il lavoro Hyperliquid same-millisecond fill-chain è ormai **upstream** (PR #1428 merged il 2026-07-30): la divergenza del fork è solo 4RSI + `pareto_dash_dark.py` + memorie Serena.
- Architettura v8: HlcvsBundle (T,N,4) f64 [HIGH,LOW,CLOSE,VOLUME]; orchestrator Rust con `SymbolSideInput`; `pbr.run_backtest_bundle`; gruppi config bot (risk/forager/hsl/unstuck/rylos_4rsi) appiattiti via `inject_flattened_shared_bot_side`; bounds optimize con chiavi flat `long_<flat>`.
- Strategia usata in produzione: `trailing_grid_v7`, LONG only su HYPE.
- Attenzione: `format_end_date("now")` = oggi − 2 giorni hardcoded (`src/utils.py`) → per backtest fino a oggi serve `end_date` esplicita.
- Doc del prototipo nel repo: `RYLOS_4RSI_PROTO.md`.

## Note di manutenzione (2026-08-04)
- Upstream ha spostato `src/optimize_bounds.py` → **`src/config/optimize_bounds.py`** (i bound `rylos_4rsi` sono sopravvissuti al rename).
- I test upstream asseriscono il set esatto dei gruppi di `bot.<side>`: quando cambia, va aggiornato `tests/test_config_utils_helpers.py` (deve includere `rylos_4rsi`).
- `_bot_params_to_rust_dict` (src/passivbot.py) ha fallback fail-closed sui campi `rylos_*` se la config non ha il gruppo (come `backtest.py`).
- Test locali: suite Python ~5400 test verdi; serve `pymoo` (sta in `requirements-full.txt`, non in `requirements-live.txt`). Test Rust: `cargo test --release --no-default-features --features abi3-py312` → 225 ok (con le feature di default il link fallisce per `extension-module`, limite noto pyo3).
- `.mcp.json` (server MCP Serena) è versionato; `*.bak` è in `.gitignore`.

## Infrastruttura (dettagli completi nel wiki Joplin, nota "passivbot")
- Server live "amazon" (`ssh admin@amazon.ziliani.net`, ARM): bot `ry` (Bybit, `/opt/passivbot`, tmux `ry`) e `ry-hl` (Hyperliquid user hyperliquid_vault, `/opt/passivbot-hl`, tmux `ry-hl`). Venv e build Rust **separati** per repo.
- Server optimize "debian" (`ssh marco@192.168.0.34`): `/opt/passivbot`, tmux `opt`, 26-29 cpu per gli optimize.
- Su amazon: MAI `venv/bin/pip` (trappola shebang), sempre `venv/bin/python -m pip`; requirements file = `requirements-live.txt`.
