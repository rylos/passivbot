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

## Notifiche trade su Telegram (dal 2026-08-15; **event-driven dal 2026-08-27**)
`~/watchdog/hl_report.py` su amazon, cron **`*/5 * * * *`**, log `~/watchdog/hl_report.log`, stato `~/watchdog/trades_state.json`. Copia versionata in **`ops/hl_report.py`**. **Sola lettura**: non riavvia e non tocca il bot — guasti e riavvii restano esclusiva del watchdog. È l'unico canale con invio Telegram diretto attivo (`send()` propria, con `~/watchdog/telegram.json`).

**Storia del cambiamento, perché è la lezione**: nato per le ferie (15→27 agosto 2026) come report a **orari fissi** (`0 9,21`) che diceva "va tutto bene" — la domanda che healthchecks non copre, dato che notifica solo sul fail e il suo silenzio non è distinguibile da un watchdog morto. Il 27/08 Marco ha detto che era **troppo verboso**: sei righe di diagnostica identiche a quelle di ieri, due volte al giorno, si smettono di leggere — e un report che non si legge non protegge. Prima l'ho ridotto a una riga, poi lui ha chiesto di spegnere gli orari fissi e **notificare solo i trade**.

Ora manda solo quando **cambia lo stato della posizione**:
- `📈 ry-hl aperta · 13.62 HYPE @ 80.629 · 13:25`
- `✅ ry-hl chiusa · +25.78 USDT · 2 gradini · wallet 12271.96 · 17:35`

I gradini intermedi della griglia **non generano messaggi** (fino a 12 per posizione: sarebbero il grosso del traffico) ma vengono contati e riassunti alla chiusura.

⚠️ **Due trappole già pagate, entrambe con un test a dimostrarle**:
1. **Il PnL di una chiusura** va sommato su una **finestra di 3 minuti che finisce sull'evento**, non scorrendo all'indietro "fino a un timestamp minore": quella versione inglobava le chiusure precedenti dello stesso giorno e dava **+44,13 dove il fill vero era +25,78**. Una chiusura può essere spezzata su più fill e scavallare il minuto (20/08: 02:30 e 02:31; 25/08: tre fill sullo stesso minuto).
2. **Se `last_key` esce dal buffer letto dal log** (rotazione, o script fermo a lungo) NON si rigioca lo storico: ci si **risincronizza in silenzio**. Rigiocare manderebbe una raffica di notifiche su trade vecchi. Meglio perdere una notifica che inondare la chat — i trade restano nel log.

## Monitor fronte di Pareto — su debian
`~/pareto_monitor/monitor.py` (marco@debian), cron `*/20`. Confronta i membri del fronte con la config live girata **sullo stesso dataset**. Baseline in `~/pareto_monitor/baseline_live.json`: dal 2026-08-05 è il backtest del candidato live **`afe61aed`** (`backtests/combined/2026-08-04T18_22_09/analysis.json`, 733gg, bybit, candele al 04/08). **Quando si cambia config live va rigenerato**, altrimenti il monitor confronta con la config vecchia (errore già commesso una volta). Avvisa su due livelli: DOMINANTE (meglio-o-uguale su tutti gli 8 obiettivi, meglio su ≥1) e FORTE (batte entrambi gli adg senza peggiorare `drawdown_worst_strategy_eq`). Dedup per hash, max 4 messaggi per giro, riepilogo finale e auto-spegnimento quando l'optimize termina.
- ⚠️ **TRAPPOLA**: nei file `pareto/*.json` le metriche sotto `metrics.stats.*` sono dict `{mean,min,max}`, NON scalari — leggerle come numeri fallisce in silenzio e il monitor non segnala mai nulla. Usare `metrics.objectives` (scalari, esattamente gli 8 obiettivi) oppure estrarre `["mean"]`. Le `analysis.json` dei backtest invece hanno scalari.
- Escludere i membri con `constraint_violation > 0` o `liquidated`.

## Bot freqtrade: watchdog gemello (progetto separato)
Dal 2026-08-06 anche il bot **freqtrade RyLoS T4G** su amazon ha il suo watchdog (`~/watchdog/freqtrade_watchdog.py`, cron `5-59/10` per non accavallarsi a questo, check healthchecks `freqtrade (bybit)`). Stessa impostazione: riavvio solo a processo assente, file `~/watchdog/ft_maintenance`, max 2 tentativi/ora. Vive nel repo freqtrade (`user_data/scripts/`), non qui: sono due progetti distinti.

## Controllo agentico
Cron di sessione Claude Code ogni 30 min (:08 e :38) che ispeziona ry-hl ed è autorizzato da Marco a fixare e riavviare, avvisando su Telegram prima e dopo. Vive solo finché la sessione è aperta (scade dopo 7 giorni): il watchdog di sistema su amazon è la rete di sicurezza sempre attiva.
⚠️ **Limite da dire sempre a Marco**: monitor e cron di sessione **non sopravvivono a un'assenza lunga** (sessione chiusa, PC spento, riavvio). Per le assenze — es. le ferie del 15-27 agosto 2026 — la copertura vera è solo quella server-side: watchdog `*/10` con riavvio automatico + healthchecks come dead man switch + `hl_report.py`. Non spacciare un monitor di sessione per sorveglianza continua.
✅ **Confermato dai fatti**: il monitor di sessione è morto il 22/08 per un errore ssh (exit 255) e me ne sono accorto **quattro giorni dopo**, il 26. In quei giorni la copertura server-side ha retto senza aiuto — bot vivo, 13 chiusure di cui 12 in profitto, +422 USDC. Quando si riarma il monitor, far sì che la caduta del canale ssh **si annunci** invece di morire in silenzio.

Vedi anche `mem:live_deployment`, `mem:optimize_workflow`.

## Dal 2026-09-03: watchdog e report a profili (hl / bybit)
`~/watchdog/watchdog.py` e `~/watchdog/hl_report.py` su amazon scelgono l'istanza dal primo argomento (`bybit`), default `hl` → il cron storico di ry-hl è invariato. Per istanza: stato (`state.json`/`state_bybit.json`, `trades_state.json`/`trades_state_bybit.json`), flag di manutenzione (`hl_maintenance`/`bybit_maintenance`), tmux, log alias (`hyperliquid_vault.log`/`bybit_02.log` = `<user>.log` creato da passivbot), check healthchecks (`HC_PASSIVBOT`/`HC_PASSIVBOT_BYBIT`; il secondo è l'ex check freqtrade rinominato "passivbot (bybit)" via API il 2026-09-03, stesso uuid). Cron ry-bybit: `3-59/10` watchdog, `*/5` report. Il watchdog freqtrade e `ft_report.py` sono commentati nel crontab (freqtrade fermo). Copie versionate: `ops/watchdog_ry_hl.py`, `ops/hl_report.py`, `ops/README.md`.
