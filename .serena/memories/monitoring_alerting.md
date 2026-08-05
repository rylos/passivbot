# Monitoraggio e alerting (attivi dal 2026-08-04)

Tutte le notifiche a Marco vanno sul bot **Claude RyLoS Bot** (`claude_rylos_bot`, id 8826838785, chat_id 46772914), MAI sul bot del config freqtrade (quello è del bot freqtrade in produzione). Token in `~/.claude/channels/telegram/.env` su pc-work, copiato con chmod 600 sugli host che devono notificare. Orari sempre in Europe/Rome.

## Watchdog bot live — su amazon
`~/watchdog/watchdog.py` (admin@amazon), cron `*/10`, log `~/watchdog/watchdog.log`, stato `~/watchdog/state.json` (offset incrementale sul log + cooldown per categoria). Legge `/opt/passivbot-hl/logs/hyperliquid_vault.log` (symlink stabile al log del run corrente; la rotazione azzera l'offset e genera una notifica di riavvio).
Rileva: processo `^python src/main.py` assente; log fermo >35 min con processo vivo; righe ERROR/CRITICAL/Traceback; pattern di blocco (`position_fill_confirmation_pending`, `trailing state unavailable`, `fill_after_state_mismatch`, `nontradable`, `tradable=false`) **persistenti da ≥20 min**; `err=N/10` con N≥3 nella riga `[health]`. Non tocca il bot: solo diagnosi e avviso.

### Soglie: tarate su dati reali dopo un falso positivo (2026-08-04)
- La riga `[health]` esce ogni ~15 min: misurando 3 giorni di log, gap p99 = 12 min e **massimo 15.5 min**, nessuno sopra i 20. La prima soglia "log fermo >12 min" era sotto la cadenza normale → falso allarme immediato. Ora 35 min (oltre due cicli health persi).
- Il warning di trailing warmup è normale per ~5 min dopo un fill o un restart → allarme solo se il pattern persiste ≥20 min (l'incidente vero del 28/07 durò 27 ore, non si perde nulla).
- `err=N/10` è un contatore su soglia 10: 1-2 errori transitori sono rumore, si segnala da 3 in su.
- **Regola generale**: prima di fissare una soglia su un log, misurare la distribuzione reale dei gap/valori su giorni di dati, non stimarla a occhio.

## Monitor fronte di Pareto — su debian
`~/pareto_monitor/monitor.py` (marco@debian), cron `*/20`. Confronta i membri del fronte con la config live girata **sullo stesso dataset**. Baseline in `~/pareto_monitor/baseline_live.json`: dal 2026-08-05 è il backtest del candidato live **`afe61aed`** (`backtests/combined/2026-08-04T18_22_09/analysis.json`, 733gg, bybit, candele al 04/08). **Quando si cambia config live va rigenerato**, altrimenti il monitor confronta con la config vecchia (errore già commesso una volta). Avvisa su due livelli: DOMINANTE (meglio-o-uguale su tutti gli 8 obiettivi, meglio su ≥1) e FORTE (batte entrambi gli adg senza peggiorare `drawdown_worst_strategy_eq`). Dedup per hash, max 4 messaggi per giro, riepilogo finale e auto-spegnimento quando l'optimize termina.
- ⚠️ **TRAPPOLA**: nei file `pareto/*.json` le metriche sotto `metrics.stats.*` sono dict `{mean,min,max}`, NON scalari — leggerle come numeri fallisce in silenzio e il monitor non segnala mai nulla. Usare `metrics.objectives` (scalari, esattamente gli 8 obiettivi) oppure estrarre `["mean"]`. Le `analysis.json` dei backtest invece hanno scalari.
- Escludere i membri con `constraint_violation > 0` o `liquidated`.

## Controllo agentico
Cron di sessione Claude Code ogni 30 min (:08 e :38) che ispeziona ry-hl ed è autorizzato da Marco a fixare e riavviare, avvisando su Telegram prima e dopo. Vive solo finché la sessione è aperta (scade dopo 7 giorni): il watchdog di sistema su amazon è la rete di sicurezza sempre attiva.

Vedi anche `mem:live_deployment`, `mem:optimize_workflow`.
