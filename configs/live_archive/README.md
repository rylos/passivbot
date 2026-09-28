# Archivio config live

Config complete (sezione `bot` + `live`) tolte dal live, con il periodo in cui hanno girato
e le metriche con cui sono state scelte e sostituite. Le API key non sono qui: stanno in
`api-keys.json` sul server.

## ry-hl_93b1ab16-emg0035_2026-09-07_2026-09-28.json

- Bot: ry-hl (Hyperliquid, user `hyperliquid_vault`), dal 2026-09-07 10:44 al 2026-09-28.
- Origine: candidato `93b1ab16` del run r4e (profilo robusto) con `rylos_4rsi.exit_min_gain`
  portato a 0,0035 (sopravvivenza alle partenze fredde di gennaio 2025); enforcer 1,01.
- Metriche alla scelta (dati bybit 2024-12-05 → 2026-09-13): adg 0,74%, dd 21,5%, held max 1,6 g,
  1188 cicli, 99,5% vincenti.
- Perché è stata sostituita (gate r8, serie di partenze mai viste y/z/q/r, fee HL):
  adg medio 0,664% (buffer 0) / 0,602% (buffer 0,05%), dd max 48,9% / 78,2%,
  held max 34,9 g (partenza fredda 2026-07-11), recupero 29-30 g.

## ry-bybit_2cab1b32-emg0035_2026-09-07_2026-09-28.json

- Bot: ry-bybit (Bybit, user `bybit_02`), dal 2026-09-07 10:45 al 2026-09-28.
- Origine: candidato `2cab1b32` del run r4e (profilo rendimento) con `exit_min_gain` 0,0035;
  enforcer 1,01.
- Metriche alla scelta: adg 0,86%, dd 24,5%, held max 2,1 g, 1182 cicli, 99,4% vincenti.
- Gate r8 (fee Bybit): adg medio 0,751% / 0,697%, dd max 38,2% / 80,4%, held 4,0-6,8 g,
  recupero 11-13 g. Rendeva il 6% in più di 4e066c8d senza buffer, ma il suo dd dipende
  da un'uscita riuscita di un soffio il 2025-04-02 (80% col buffer 0,05%).

## 4e066c8d_r8_pareto.json

Artefatto Pareto completo (config + metriche per scenario) del candidato messo live su
entrambi i bot il 2026-09-28. Run r8: obiettivo adg medio su 18 partenze sfasate (serie
seg/v/u) con e senza buffer, vincoli dd <= 40%, held <= 7 g, recupero <= 20 g, TWEL <= 3.
- r8 (36 scenari): adg medio 0,724% (0,741 / 0,707), dd max 27,9%, held 3,4 g, recupero 17 g.
- Gate r8 su serie mai viste: fee HL 0,713% / 0,678%, fee Bybit 0,708% / 0,673%,
  dd max 28,2%, held 3,7 g, recupero 16-17 g.
- Parità verificata: stesso risultato bit per bit sul codice live (088e26b85) e sul merge
  upstream 7d7010989 (adg 0,007865, 5481 fill, periodo intero).

Pagine backtest (artefatti claude.ai): ry-bybit precedente https://claude.ai/artifact/1uEigwyfEircREnHdjqP3H, ry-hl precedente https://claude.ai/artifact/Rpsfu37PUgyZebEA2z1PYn, 4e066c8d https://claude.ai/artifact/J8DWWt9C3bsGK4znwgfgzz (dati fino al 2026-09-27).

## Stato live dal 2026-09-28 14:05
Entrambi i bot: `bot.long` = 4e066c8d con HSL legacy acceso (red 0,25, ema 189 min, cooldown 720 min), codice `65877b070` (merge upstream fino a 4d30330f5). Test: su 112 partenze a freddo ogni 5 giorni × buffer 0/0,05% adg medio 0,736%/0,704%, dd max 32%, nessun fallimento (senza HSL: 3 su 224, dd max 95%); periodo intero invariato (lo stop non scatta).
