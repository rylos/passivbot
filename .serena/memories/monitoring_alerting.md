# Monitoraggio e alerting (attivi dal 2026-08-04, canale rivisto il 2026-08-06)

**Canale unico dal 2026-08-06: healthchecks.io.** Il check `passivbot (hl)` (`58e8c8a4…`, `timeout 600` / `grace 900`) notifica su Telegram RyLoS e via email. Gli invii diretti al bot **Claude RyLoS Bot** (`claude_rylos_bot`, id 8826838785, chat_id 46772914) restano nel codice del watchdog ma **disattivati** (`TELEGRAM_ENABLED = False`): due notifiche dello stesso evento da due bot diversi sono rumore, e healthchecks copre in più il caso "watchdog o macchina morti", che l'invio diretto non può segnalare. Per riaccenderli basta rimettere `True`. Orari sempre in Europe/Rome.
⚠️ **L'URL di ping è una credenziale** (chi ce l'ha può segnare "up" un bot morto): sta solo in `~/watchdog/healthchecks.env` (chmod 600) su amazon, mai nel repo o nelle note.

## Watchdog bot live — su amazon
`~/watchdog/watchdog.py` (admin@amazon), cron `*/10`, log `~/watchdog/watchdog.log`, stato `~/watchdog/state.json` (offset incrementale sul log + cooldown per categoria). Copia versionata nel repo: **`ops/watchdog_ry_hl.py`** (+ `ops/README.md`) — da aggiornare a ogni modifica sul server. Legge `/opt/passivbot-hl/logs/hyperliquid_vault.log` (symlink stabile al log del run corrente; la rotazione azzera l'offset e genera una notifica di riavvio).
Rileva: processo `^python src/main.py` assente; log fermo >35 min con processo vivo; righe ERROR/CRITICAL/Traceback; pattern di blocco (`position_fill_confirmation_pending`, `trailing state unavailable`, `fill_after_state_mismatch`, `nontradable`, `tradable=false`) **persistenti da ≥20 min**; `err=N/10` con N≥3 nella riga `[health]`. Esito: ping di successo con l'ultima riga `[health]` nel body, `/fail` con la diagnosi.

### Riavvio automatico (dal 2026-08-06) — solo a processo ASSENTE
Scelta di Marco, la stessa applicata al watchdog freqtrade. Un bot **vivo ma bloccato NON viene toccato**: è il caso dell'incidente del 2026-07-29 (trailing fermo 27 ore), dove serviva capire prima di agire.
- Rilancio nel tmux `ry-hl`, ricreando la sessione se non esiste. ⚠️ Il comando usa **`venv/bin/python` esplicito** (`cd /opt/passivbot-hl && venv/bin/python src/main.py configs/live/config_hl_4rsi.json`): `python` generico è l'origine della trappola del venv copiato che puntava a `/opt/passivbot`
- Freni: **max 2 tentativi in 60 minuti** (un bot che non riparte da solo ha un problema che il riavvio non risolve), verifica del nuovo processo entro 90 s, e file **`~/watchdog/hl_maintenance`** che disabilita ogni riavvio — **da creare prima delle fermate volute** (deploy, ricompilazione Rust), altrimenti il watchdog rimette su il bot mentre ci si lavora
- Dopo ogni riavvio automatico il body ricorda di **verificare il banner `[runtime] python=<hash>`**: ricompilare il Rust non deploya il Python (lezione del 2026-07-29)
- ⚠️ **Bug corretto il 2026-08-13**: `bot_pid()` cercava il processo con `pgrep -f "^python src/main.py"` mentre `BOT_CMD` (e la procedura di restart) avviano `venv/bin/python src/main.py` → il pattern non matchava e il watchdog considerava assente un bot vivo, **avviandone un secondo**. Salvati solo dal file di manutenzione, attivo durante il deploy. Ora il pattern è `python src/main\.py configs/live/config_hl_4rsi\.json`, che regge entrambe le forme. Lezione: quando cambia il comando di avvio, va cambiato anche il pattern di rilevamento — sono due punti dello stesso file che devono restare allineati.
- Percorsi provati su sessione finta `ry-hl-wdtest` con un `sleep` al posto del bot, senza toccare il live: guardia di manutenzione, creazione sessione + rilancio, freno rate limit

### Soglie: tarate su dati reali dopo un falso positivo (2026-08-04)
- La riga `[health]` esce ogni ~15 min: misurando 3 giorni di log, gap p99 = 12 min e **massimo 15.5 min**, nessuno sopra i 20. La prima soglia "log fermo >12 min" era sotto la cadenza normale → falso allarme immediato. Ora 35 min (oltre due cicli health persi).
- Il warning di trailing warmup è normale per ~5 min dopo un fill o un restart → allarme solo se il pattern persiste ≥20 min (l'incidente vero del 28/07 durò 27 ore, non si perde nulla).
- `err=N/10` è un contatore su soglia 10: 1-2 errori transitori sono rumore, si segnala da 3 in su.
- **Regola generale**: prima di fissare una soglia su un log, misurare la distribuzione reale dei gap/valori su giorni di dati, non stimarla a occhio.

## Riavvio INTERNO del bot (da non confondere con un crash)
Su raffiche di errori dell'API Hyperliquid (`ExchangeNotAvailable` su `refresh_authoritative_state`) il bot raggiunge il proprio budget errori — riga `[health] error_budget count=10 limit=10 window=1h action=restart_at_limit` — solleva `RestartBotException` e **si riavvia dentro lo stesso processo**: PID invariato, contatore `up=` che riparte da zero, nessuna rotazione del log, watchdog non coinvolto (il processo non è mai morto). Ripartenza completa in ~3-4 minuti, con un `RequestTimeout` sul caricamento mercati che è normale in quella fase. Visto il 2026-08-08 e il 2026-08-15, entrambe le volte con recupero autonomo e riconciliazione corretta della posizione. Quindi: `up=` basso con PID vecchio non è un mistero, è questo.

## Monitor fronte di Pareto — su debian
`~/pareto_monitor/monitor.py` (marco@debian), cron `*/20`. Confronta i membri del fronte con la config live girata **sullo stesso dataset**. Baseline in `~/pareto_monitor/baseline_live.json`: dal 2026-08-05 è il backtest del candidato live **`afe61aed`** (`backtests/combined/2026-08-04T18_22_09/analysis.json`, 733gg, bybit, candele al 04/08). **Quando si cambia config live va rigenerato**, altrimenti il monitor confronta con la config vecchia (errore già commesso una volta). Avvisa su due livelli: DOMINANTE (meglio-o-uguale su tutti gli 8 obiettivi, meglio su ≥1) e FORTE (batte entrambi gli adg senza peggiorare `drawdown_worst_strategy_eq`). Dedup per hash, max 4 messaggi per giro, riepilogo finale e auto-spegnimento quando l'optimize termina.
- ⚠️ **TRAPPOLA**: nei file `pareto/*.json` le metriche sotto `metrics.stats.*` sono dict `{mean,min,max}`, NON scalari — leggerle come numeri fallisce in silenzio e il monitor non segnala mai nulla. Usare `metrics.objectives` (scalari, esattamente gli 8 obiettivi) oppure estrarre `["mean"]`. Le `analysis.json` dei backtest invece hanno scalari.
- Escludere i membri con `constraint_violation > 0` o `liquidated`.

## Bot freqtrade: watchdog gemello (progetto separato)
Dal 2026-08-06 anche il bot **freqtrade RyLoS T4G** su amazon ha il suo watchdog (`~/watchdog/freqtrade_watchdog.py`, cron `5-59/10` per non accavallarsi a questo, check healthchecks `freqtrade (bybit)`). Stessa impostazione: riavvio solo a processo assente, file `~/watchdog/ft_maintenance`, max 2 tentativi/ora. Vive nel repo freqtrade (`user_data/scripts/`), non qui: sono due progetti distinti.

## Controllo agentico
Cron di sessione Claude Code ogni 30 min (:08 e :38) che ispeziona ry-hl ed è autorizzato da Marco a fixare e riavviare, avvisando su Telegram prima e dopo. Vive solo finché la sessione è aperta (scade dopo 7 giorni): il watchdog di sistema su amazon è la rete di sicurezza sempre attiva.

Vedi anche `mem:live_deployment`, `mem:optimize_workflow`.
