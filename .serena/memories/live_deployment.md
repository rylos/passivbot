# Deploy live e stato corrente (aggiornato 2026-08-13)

## Stato
- **ry-hl** (Hyperliquid, user `hyperliquid_vault`, tmux `ry-hl` su amazon): branch `rylos-4rsi-proto` @ **`d1b352eb`** (merge upstream fino a `aeb6269f` del 2026-08-12, release upstream v8.1.0, + patch reconciler 4RSI — vedi `mem:rylos_4rsi_prototype`), live dal 2026-08-13 00:45 ora italiana, riavviato da flat. Config invariata (nessun cambio di parametri: il merge è neutro sulla strategia). Storia precedente: `b9a71bed` (merge upstream fino a `24081f14` del 2026-08-03), config `configs/live/config_hl_4rsi.json` = **candidato `afe61aed`** del run r3 (`optimize_results/2026-08-04T13_29_26_combined_733days_HYPE_f8459165/pareto/afe61aed*.json` su debian), live dal 2026-08-04 20:22 ora italiana. TWE **2.93**, `risk.total_exposure_enforcer_threshold` forzato a **1.01** (il candidato aveva 1.003: anti-chattering TWEL, fenomeno live-only invisibile al backtest). Entry osc<−23.8698/stoch<12.703; exit osc>19.304/stoch>87.183, gain>0.646%.
  - Metriche di riferimento (backtest 733gg, candele al 04/08, `backtests/combined/2026-08-04T18_22_09/analysis.json` su debian — è anche il baseline del monitor): adg 0.010105, adg_w 0.006020, drawdown_worst 0.2804, dd_1pct 0.2585, recovery_days_max 4.70, position_held_days_max 3.99, sortino 0.2072.
  - Storico deploy del 04/08: `7b05e3b7` (precedente) → `61d1986b` alle 17:26 → `afe61aed` alle 20:22. Backup progressivi in `configs/live/config_hl_4rsi.json.pre-*`. Il run r3 completo (500k iter) non ha prodotto nulla di meglio: zero dominanti, zero sopra la soglia del 3% (vedi `mem:deploy-autonomo-vincitore-netto`).
  - I contatori ordini/fills nella riga `[health]` ripartono da zero a ogni restart.
- **ry** (Bybit, user `bybit_02`, tmux `ry` su amazon): master upstream `5726b901`, bot FERMO per scelta di Marco (config `configs/live/config.json`). NON aggiornato al merge del 04/08.
- **debian** (`/opt/passivbot`): stesso commit `d1b352eb`, Rust ricompilata, nessun optimize in corso.

## Merge upstream del 2026-08-13 (213 commit, fino a `aeb6269f`)
- Zero conflitti. Tag di rollback locale su pc-work: `pre-upstream-merge-20260813` = `e95649b11`.
- **Blocker trovato e risolto**: upstream ora valida la famiglia dell'ordine contro la modalità inviata a Rust (`src/live/reconciler.py`, `_validate_rust_order_family_for_submitted_mode`) e rifiuta un `close_panic_*` fuori da modalità panic con `FatalBotException` (processo morto). L'uscita 4RSI chiude via `calc_panic_close` in modalità normale → il bot sarebbe morto **al primo segnale di uscita**, non all'avvio. Patch fork-local in `d1b352eb` + test `tests/test_rylos_4rsi_panic_close.py`.
- La config `v8.0.0` è ancora accettata (`SUPPORTED_PREVIOUS_CONFIG_SCHEMA_VERSIONS`) e migra a `v8.2.0`; `backtest.aggregate` è rinominato `backtest.reducer` (alias accettato). Nessun cambio ai requirements.
- **Neutralità verificata con 3 backtest** (dettagli in `mem:optimize_workflow`): il merge non sposta le metriche.

## Procedura swap config da candidato optimize (CRITICA)
1. Backup della config attuale (`cp ... .pre-<tag>-<data>`).
2. **Sostituire la sezione `live` del candidato con quella di produzione** — il candidato porta `live.user` dell'ambiente optimize (es. `bybit_02`), MAI usarlo su ry-hl. `coin_overrides` = quelli di produzione.
2b. ⚠️ Dal 2026-08-06 PRIMA di fermare il bot: `touch ~/watchdog/hl_maintenance` (senza, il watchdog lo rimette su entro 10 minuti mentre ci lavori) e `rm ~/watchdog/hl_maintenance` a fine intervento.
3. Stop pulito: `kill -INT <pid>` (pid via `pgrep -f '^python src/main.py'`), attendere "Bot stopped via signal".
4. Restart: `tmux send-keys -t <sessione>.0 'python src/main.py configs/live/<cfg>.json' C-m`.
5. Verifica: banner TWEL atteso, `[pos]` riconciliata (prende in carico posizioni aperte), warning trailing warmup sparisce in ~5 min, nessun traceback.

## Procedura aggiornamento codice (repo + Rust)
Su amazon-hl il remote del fork è **`fork`** (`origin` = enarjord); su debian e pc-work è `origin`.
`git fetch fork rylos-4rsi-proto && git merge --ff-only fork/rylos-4rsi-proto` → `export PATH=$HOME/.cargo/bin:$PATH && source venv/bin/activate && cd passivbot-rust && maturin develop --release` → restart. Requirements solo se cambiati: `venv/bin/python -m pip install -r requirements-live.txt` (MAI `venv/bin/pip` su amazon). Preferire i riavvii quando il bot è flat.
- Verifica post-deploy OBBLIGATORIA: banner `[runtime] python=<hash>` = commit del fix (ricompilare il Rust NON deploya il Python) e `grep -c rylos_4rsi_enabled <venv>/lib/python3.12/site-packages/passivbot_rust/passivbot_rust.abi3.so` → 3 su hl, 0 su bybit.
- Pre-check utile prima del restart: `python -c` con `load_config(<config live>)` per verificare che il codice nuovo accetti la config in produzione.
- Nota: dopo `maturin develop` il bot al primo avvio segnala comunque "Rust extension is stale" e ricompila (~30s); serve cargo nel PATH. Lo stesso vale per `src/backtest.py` su debian: **senza `export PATH=$HOME/.cargo/bin:$PATH` il backtest fallisce** con "rustc non installato" quando l'extension è stale.
- Verifica requirements senza rischi: `venv/bin/python -m pip install --dry-run -r requirements-live.txt` — se non stampa righe "Would install/Collecting/Downloading" non c'è nulla da installare.

## Notifiche e sorveglianza
Telegram a Marco: bot **Claude RyLoS Bot** (token in `~/.claude/channels/telegram/.env` su pc-work, chat_id 46772914) — NON il bot del config freqtrade. Orari SEMPRE in Europe/Rome nei report.
Watchdog automatico su ry-hl attivo dal 2026-08-04 (cron ogni 10 min su amazon), **dal 2026-08-06 riavvia da solo il bot se il processo è assente** (vedi il punto 2b della procedura di restart: file di manutenzione obbligatorio prima di ogni fermata voluta) + controllo agentico ogni 30 min con autorizzazione di Marco a fixare e riavviare: dettagli in `mem:monitoring_alerting`.
