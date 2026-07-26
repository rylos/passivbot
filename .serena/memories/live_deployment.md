# Deploy live e stato corrente (aggiornato 2026-07-26)

## Stato
- **ry-hl** (Hyperliquid, user `hyperliquid_vault`, tmux `ry-hl` su amazon): branch `rylos-4rsi-proto` @ `1fbe9dae`, config `configs/live/config_hl_4rsi.json` = candidato **7b05e3b7** (full: `7b05e3b743c566054193b980043b1808268e99745797e5deebed01c9a56c26e9`, run refinement `2026-07-25T02_49_45_..._65796f56` su debian). TWE 3.0; entry osc<−23.77/stoch<12.79; exit osc>19.97/stoch>87.16, gain>0.606%. Prima uscita 4RSI live: 2026-07-26 04:15 ora italiana, +97.79 USDC.
- **ry** (Bybit, user `bybit_02`, tmux `ry` su amazon): master upstream `5726b901`, bot FERMO per scelta di Marco (config `configs/live/config.json`).

## Procedura swap config da candidato optimize (CRITICA)
1. Backup della config attuale (`cp ... .pre-<tag>-<data>`).
2. **Sostituire la sezione `live` del candidato con quella di produzione** — il candidato porta `live.user` dell'ambiente optimize (es. `bybit_02`), MAI usarlo su ry-hl. `coin_overrides` = quelli di produzione.
3. Stop pulito: `kill -INT <pid>` (pid via `pgrep -f '^python src/main.py'`), attendere "Bot stopped via signal".
4. Restart: `tmux send-keys -t <sessione>.0 'python src/main.py configs/live/<cfg>.json' C-m`.
5. Verifica: banner TWEL atteso, `[pos]` riconciliata (prende in carico posizioni aperte), warning trailing warmup sparisce in ~5 min, nessun traceback.

## Procedura aggiornamento codice (repo + Rust)
git fetch + merge --ff-only → `export PATH=$HOME/.cargo/bin:$PATH && source venv/bin/activate && cd passivbot-rust && maturin develop --release` → restart. Requirements solo se cambiati: `venv/bin/python -m pip install -r requirements-live.txt` (MAI `venv/bin/pip` su amazon). Preferire i riavvii quando il bot è flat.

## Notifiche
Telegram a Marco: token+chat_id nel campo `telegram` di `~/dev/freqtrade/user_data/config.json` (pc-work). Orari SEMPRE in Europe/Rome nei report.
