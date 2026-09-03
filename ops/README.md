# ops — script operativi del live (copia di riferimento)

Gli script qui dentro **girano su amazon**, non da questo repo: la copia serve a
sopravvivere a una ricostruzione del server e a versionare le modifiche.

| file | dove gira | cron |
|---|---|---|
| `watchdog_ry_hl.py` | amazon, `~/watchdog/watchdog.py` | `*/10 * * * *` (ry-hl) e `3-59/10 * * * *` con argomento `bybit` (ry-bybit) |
| `hl_report.py` | amazon, `~/watchdog/hl_report.py` | `*/5 * * * *` (ry-hl) e `*/5 * * * *` con argomento `bybit` (ry-bybit) |

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
- `✅ ry-hl chiusa · +25.78 USDT · 2 gradini · wallet 12271.96 · 17:35`

I gradini intermedi della griglia **non generano messaggi** (sarebbero il grosso
del traffico: fino a 12 per posizione) ma vengono contati e riassunti alla
chiusura.

Stato in `~/watchdog/trades_state.json`: ultimo evento `[pos]` notificato, il
contatore dei gradini e **l'istante di apertura** della posizione in corso.

Tre trappole già pagate, tutte verificate con un test:

- **il PnL di una posizione** è la somma dei fill di chiusura fra la sua
  apertura e la sua chiusura — per questo l'istante di apertura sta in stato.
  Due versioni sbagliate prima di questa: scorrere all'indietro "fino a un
  timestamp minore" sommava anche le chiusure precedenti dello stesso giorno
  (+44,13 dove il fill vero era +25,78, il 20/08); la finestra di 3 minuti che
  turava quel buco escludeva però le riduzioni intermedie della griglia di
  chiusura (+237,81 dove la posizione aveva reso +246,57, il 28/08).
- **il wallet** si legge dalla riga `[balance] ... equity=`, non da `[health]
  bal=`: la health esce ogni ~15 minuti, quindi alla chiusura riporta quasi
  sempre il saldo *pre*-chiusura (28/08: notificato 12290,05 quando il wallet
  reale era già 12521,68). La riga `[balance]` esce invece nello stesso secondo
  del fill che muove il saldo.
- **se `last_key` esce dal buffer** letto dal log (rotazione, o script fermo a
  lungo), NON si rigioca lo storico — si risincronizza in silenzio. Rigiocare
  manderebbe una raffica di notifiche su trade vecchi. Si preferisce perdere
  una notifica che inondare la chat; i trade restano comunque nel log.

Le credenziali stanno in `~/watchdog/telegram.json` (chmod 600), condiviso col
watchdog.

## Due istanze, un solo script (dal 2026-09-03)

Il 2026-09-03 il bot freqtrade su Bybit (account `bybit_02`) è stato fermato e
sostituito da una seconda istanza passivbot, **ry-bybit**: `/opt/passivbot-bybit`
(copia di `/opt/passivbot-hl` allo stesso commit, venv e Rust inclusi),
`configs/live/config_bybit_4rsi.json` (candidato `f6b2b013` dell'optimize r4e,
10x cross, hedge mode), tmux `ry-bybit`, log alias `logs/bybit_02.log`.

Watchdog e report sono gli stessi file con un **profilo scelto dal primo
argomento** (`hl` di default, `bybit`): file di stato, flag di manutenzione
(`hl_maintenance` / `bybit_maintenance`), sessione tmux e check healthchecks
sono per istanza. Il check healthchecks di ry-bybit è quello ereditato da
freqtrade (`HC_FREQTRADE` in `healthchecks.env`): va rinominato sul sito, non
nello script.

⚠️ Bybit in hedge mode: passivbot lo imposta all'avvio e Bybit non permette di
cambiare position mode con una posizione aperta. Se freqtrade dovesse tornare su
questo account, va rimesso one-way **a conto piatto**.
