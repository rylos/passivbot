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

## ry-bybit: seconda istanza passivbot su Bybit (dal 2026-09-03 14:34)
**Config attuale (dal 2026-09-03 19:08 ora italiana): candidato `72d37fa6`** (r4e, `optimize_results/2026-09-03T11_51_29_bybit_634days_suite_1_coins_b9861089/pareto/72d37fa670f7190f*.json` su debian), `bot.long` sostituito con `risk.total_exposure_enforcer_threshold` forzato a 1.01; TWEL 3.0, `exit_min_gain` 0,53%, `osc_entry` −25,3, `grid_qty_pct` 0,12, unstuck threshold 0,476. Backup `configs/live/config_bybit_4rsi.json.pre-72d37fa6-20260903`. Motivo: unico candidato sotto 26% di dd su tutte e 4 le partizioni (suite 19 + quarta partizione da 2025-02-18): dd max 25,5%, mdg min 0,00165 > live, held max 3,3 g, adg 0,82%, gain 153x; f6b2b013 aveva dd max 38% e held 7,1 g. Test quarta partizione: script `/tmp/shifted4.py` su debian, risultati `backtests/suite_runs/2026-09-03T17_0*`. Nota: il live HL sulla quarta partizione fa dd 95,5% sul segmento da 2025-02-18 (partenza fredda nel crollo) e 6db9f7f1 65% su u6 → le partizioni spostate restano il gate obbligatorio.
Storia: 14:34–19:07 candidato `f6b2b013` (dettagli sotto).
Sostituisce il bot freqtrade RyLoS T4G sullo stesso account (`bybit_02`, unified, saldo 8.533 USDT al via). Freqtrade fermato dalla sessione freqtrade con l'ok diretto di Marco: trade #28 chiuso con forceexit a 81,99 (−32 USDT), `ft_maintenance` permanente, cron freqtrade commentati (backup `~/watchdog/crontab.bak-20260903`), db intatto.
- Perché non si è "presa in carico" la posizione: passivbot su Bybit lavora **solo in hedge mode** (`positionIdx` 1/2, `set_position_mode(True)` all'avvio) e Bybit non cambia position mode con posizioni aperte. Conto piatto → hedge mode → avvio pulito.
- Istanza: `/opt/passivbot-bybit` (rsync di `/opt/passivbot-hl` senza logs/caches, commit `d1b352eb8`, Rust in site-packages del venv copiato → indipendente da HL; `venv/bin/pip` ha lo shebang di HL: usare sempre `venv/bin/python -m pip`), tmux `ry-bybit`, config `configs/live/config_bybit_4rsi.json` = `bot.long` del candidato **`f6b2b013`** (r4e, 19 scenari; TWEL 2,94, `exit_min_gain` 0,53%, `osc_entry` −26,5, `grid_qty_pct` 0,31) + sezione `live` di produzione HL con `user: bybit_02`, leva 10, `margin_mode_preference: cross`, hedge mode. Verificato sull'exchange dopo l'avvio: positionIdx 1/2, leverage 10, tradeMode 0 (cross), account marginMode passato da ISOLATED_MARGIN a REGULAR_MARGIN.
- Scelta della leva: 10x cross come su HL, coerente col backtest (liquidazione ≈ −30% dal medio); 4x isolato avrebbe richiesto un TWEL più basso e un candidato diverso.
- Al primo avvio il bot ha letto 123 fill storici (+1.210 USDT, sono i trade di freqtrade) e `[candle] HYPE 1h missing=314`: l'EMA di volatilità a 1825 h parte non convergente, come su HL a ogni riavvio.
- Rischio noto del candidato (suite a 19): dd max 38% in giugno 2026 su tutte e tre le partizioni, 7,1 giorni; adg 0,79% contro 0,985% del live HL. Test della quarta partizione (+75 g) ancora da fare a fine r4e.
- Monitoraggio: `watchdog.py bybit` (cron `3-59/10`), `hl_report.py bybit` (cron `*/5`), flag `~/watchdog/bybit_maintenance`, healthchecks = check ex-freqtrade (`HC_FREQTRADE`). Notifiche Telegram con prefisso `ry-bybit`.
