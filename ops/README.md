# ops — script operativi del live (copia di riferimento)

Gli script qui dentro **girano su amazon**, non da questo repo: la copia serve a
sopravvivere a una ricostruzione del server e a versionare le modifiche.

| file | dove gira | cron |
|---|---|---|
| `watchdog_ry_hl.py` | amazon, `~/watchdog/watchdog.py` | `*/10 * * * *` |
| `hl_report.py` | amazon, `~/watchdog/hl_report.py` | `0 9,21 * * *` |

Dopo ogni modifica qui, ricopiare sul server e verificare che l'md5 combaci:

```bash
scp ops/watchdog_ry_hl.py amazon.ziliani.net:'~/watchdog/watchdog.py'
ssh amazon.ziliani.net 'python3 ~/watchdog/watchdog.py; echo exit=$?'
```

Il gemello per il bot freqtrade sta nell'altro repo, `freqtrade/ops/watchdog_freqtrade.py`.

## watchdog_ry_hl.py

Sorveglia il bot live **ry-hl** (Hyperliquid, prototipo 4RSI) leggendo
`/opt/passivbot-hl/logs/hyperliquid_vault.log` — che è un symlink stabile al log
del run corrente, quindi sopravvive ai riavvii.

Rileva: processo assente · log fermo da >35 min · righe ERROR/CRITICAL · pattern
di blocco del trailing persistenti da ≥20 min · contatore `err=N/10` con N≥3.
Le soglie sono misurate sulla distribuzione reale dei log, non stimate a occhio.

**Riavvio automatico solo a processo ASSENTE.** Un bot vivo ma bloccato non viene
toccato: è il caso dell'incidente del 2026-07-29 (trailing fermo 27 ore), dove
serviva capire prima di agire. Freni: max 2 tentativi in 60 minuti, e il file
`~/watchdog/hl_maintenance` che disabilita ogni riavvio (crearlo prima delle
fermate volute: deploy, ricompilazione Rust). Il rilancio usa il **python del
proprio venv** in modo esplicito, per non ricadere nella trappola del venv
copiato che puntava a `/opt/passivbot`.

**Notifiche**: canale unico su healthchecks.io, check `passivbot (hl)` — ping di
successo col riepilogo nel body, `/fail` con la diagnosi, e scadenza automatica
se cron o macchina muoiono (dead man switch). Gli invii diretti su Telegram
restano nel codice ma disattivati (`TELEGRAM_ENABLED = False`), per non ricevere
due notifiche dello stesso evento da due bot diversi.

⚠️ L'URL di ping **è una credenziale**: sta solo in `~/watchdog/healthchecks.env`
(chmod 600) sul server, mai nel repo.

## hl_report.py

Report periodico su Telegram (Claude RyLoS Bot), **sola lettura**: non riavvia e
non tocca il bot. Nato per il periodo di ferie del 2026-08-15 → 25.

Risponde alla domanda che il watchdog non copre: *"va tutto bene?"*. Healthchecks
notifica solo quando qualcosa rompe, e il silenzio non è distinguibile da un
watchdog morto senza aprire il telefono e controllare a mano.

Manda pid, riga `[health]` corrente (up, posizione, balance, ordini, contatore
errori), età dell'ultima riga di log e il conteggio 24h di errori/riavvii
interni/fill.

Verde vs giallo: il giallo deve voler dire *"guarda adesso"*, quindi pesano solo
gli **errori delle ultime 2 ore** — non quelli delle 24h, che includono gli
hiccup dell'API Hyperliquid da cui il bot si riprende da solo con un riavvio
interno. Giallo anche se il processo è assente, il log è fermo da >35 min, o i
riavvii interni in 24h sono ≥5 (uno o due sono fisiologici, una raffica no).

Le credenziali stanno in `~/watchdog/telegram.json` (chmod 600), già presente e
condiviso col watchdog.
