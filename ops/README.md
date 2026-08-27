# ops — script operativi del live (copia di riferimento)

Gli script qui dentro **girano su amazon**, non da questo repo: la copia serve a
sopravvivere a una ricostruzione del server e a versionare le modifiche.

| file | dove gira | cron |
|---|---|---|
| `watchdog_ry_hl.py` | amazon, `~/watchdog/watchdog.py` | `*/10 * * * *` |
| `hl_report.py` | amazon, `~/watchdog/hl_report.py` | `*/5 * * * *` |

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

Notifiche Telegram sui **trade** di ry-hl (Claude RyLoS Bot), **sola lettura**:
non riavvia e non tocca il bot. Il guasto resta compito del watchdog.

Nato come report a orari fissi per le ferie del 2026-08-15 → 27; dal 27/08 è
**event-driven**, perché due messaggi al giorno che dicono sempre la stessa
cosa si smettono di leggere — e un report che non si legge non protegge.

Parla solo quando **cambia lo stato della posizione**:

- `📈 ry-hl aperta · 13.62 HYPE @ 80.629 · 13:25`
- `✅ ry-hl chiusa · +25.78 USDT · 2 gradini · cassa 12271.96 · 17:35`

I gradini intermedi della griglia **non generano messaggi** (sarebbero il grosso
del traffico: fino a 12 per posizione) ma vengono contati e riassunti alla
chiusura.

Stato in `~/watchdog/trades_state.json`: ultimo evento `[pos]` notificato più il
contatore dei gradini.

Due trappole già pagate, entrambe verificate con un test:

- **il PnL di una chiusura** va sommato su una **finestra di 3 minuti che
  finisce sull'evento**, non scorrendo all'indietro "fino a un timestamp
  minore": quella versione sommava anche le chiusure precedenti dello stesso
  giorno e dava +44,13 dove il fill vero era +25,78. Una chiusura può essere
  spezzata su più fill e scavallare il minuto (20/08: 02:30 e 02:31).
- **se `last_key` esce dal buffer** letto dal log (rotazione, o script fermo a
  lungo), NON si rigioca lo storico — si risincronizza in silenzio. Rigiocare
  manderebbe una raffica di notifiche su trade vecchi. Si preferisce perdere
  una notifica che inondare la chat; i trade restano comunque nel log.

Le credenziali stanno in `~/watchdog/telegram.json` (chmod 600), condiviso col
watchdog.
