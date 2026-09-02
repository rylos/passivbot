# Meccanica reale di trailing_grid_v7 (letta dal codice il 2026-08-21)

Serve a **interpretare i parametri quando si sceglie un candidato dal fronte di Pareto**: senza queste quattro cose, numeri come un markup di chiusura negativo o un `trailing_grid_ratio` negativo sembrano errori e non lo sono. Riferimenti a `passivbot-rust/src/`.

## 1. Il gate 4RSI apre solo la PRIMA posizione
`orchestrator.rs:~3780`: `rylos_entry_allowed` entra solo in `allow_initial`. **I gradini successivi della griglia non passano dall'oscillatore** — una volta aperta la posizione la griglia scende per conto suo. Oscillatore = selettore del momento d'ingresso; griglia = gestore della posizione. Due meccaniche disaccoppiate.
`initial_ema_dist` **sposta il prezzo, non filtra** (`utils.rs:425`): `prezzo = min(bid, ema_banda_inferiore * (1 - ema_dist))`. Con 0.01204 l'ordine sta l'1,2% sotto la banda EMA inferiore → è la ragione per cui i limit d'ingresso stanno ~0,84% sotto mercato e per cui si resta flat per giorni quando la volatilità è bassa.

## 2. Lo spacing della griglia cresce con volatilità **e** con esposizione
`trailing_grid_v7.rs:104-137`:
```
we_mult  = (wallet_exposure / effective_WEL) * grid_spacing_we_weight
vol_mult = volatility_ema_1h * grid_spacing_volatility_weight
spacing_multiplier = 1 + we_mult + vol_mult
reentry = min(position_price * (1 - grid_spacing_pct * max(spacing_multiplier,0)), bid)
```
Coi valori live (spacing 0.01004, we_weight 6.541): 1,00% a esposizione zero → 4,29% a metà → **7,57% a esposizione piena**. Freno progressivo: più sei dentro, più il mercato deve muoversi per farti comprare ancora. È questo, più del double-down gentile, a rendere sostenibile una coda di 12 gradini.

## 3. `trailing_grid_ratio` è uno switch con soglia, e **il segno decide l'ordine** delle due modalità
`trailing_grid_v7.rs:455-525`:
- `>=1` o `<=-1` → solo trailing · `==0` → solo griglia
- `>0` → **prima trailing, poi griglia**, passaggio a `wallet_exposure_ratio == ratio`
- `<0` → **prima griglia, poi trailing**, passaggio a `wallet_exposure_ratio == 1 + ratio`

Col live **−0.302**: la griglia lavora per il primo **69,8%** del budget di esposizione, l'ultimo 30,2% si aggiunge **solo col trailing** (serve discesa + rimbalzo confermato). Cioè **i gradini più grossi e pericolosi non si comprano automaticamente**. È il punto in cui una griglia normale si fa male, e qui è protetto.

## 4. Il markup di chiusura negativo NON è un errore: è de-risking progressivo
`trailing_grid_v7.rs:948-992`:
```
start = position_price * (1 + grid_markup_start)   # live: +0,2944%
end   = position_price * (1 + grid_markup_end)     # live: -1,8556%
close_price = max(order_book.ask, start + (end - start) * min(1, wallet_exposure_ratio))
```
Il prezzo di chiusura è **interpolato fra start ed end secondo l'esposizione**: a esposizione ≈0 chiude a +0,29% (profitto), a esposizione piena a **−1,86% (perdita accettata)**. Più sei carico, più diventa arrendevole: liberare capitale vale più che spuntare il prezzo. Il `max(ask, ...)` impedisce di vendere sotto il book. Con `wallet_exposure_ratio > 1` salta l'interpolazione e prende direttamente il più basso dei due.
`grid_qty_pct` è la frazione per clip ma con pavimento `max(grid_qty_pct, 1/n_steps)`.
Sul lato chiusura `trailing_grid_ratio` +0.1 è speculare (`:1129-1160`): sotto il 10% di esposizione trailing close, sopra griglia riservando `trailing_allocation` al trailing.

## 5. L'unstuck è un budget di perdita che si ricarica coi profitti, non uno stop loss
`risk.rs:390-580` + `utils.rs:412-423`. Attivo nel live.
- **stuck** se: allowance > 0 **e** `wallet_exposure/effective_WEL > threshold` (0.54) **e** EMA gating — per il long `current_price >= ema_band_upper * (1 + ema_dist)` con `ema_dist` **−0.1977**, cioè sopra l'80,23% della banda superiore: gate largo, serve solo a non vendere sul minimo assoluto.
- fra più posizioni sceglie la **meno** stuck (`least_stuck_order`) — libera per prima quella che costa meno. Accademico con `n_positions`=1.
- **quanto**: `balance * effective_WEL * close_pct` → col live 0.0836 l'**8,36% del budget di esposizione per clip**, mai tutta la posizione. **Prezzo: il mercato corrente**, nessun target.
- **finanziamento**:
```
balance_peak = balance + (pnl_cumsum_max - pnl_cumsum_last)
allowance = max(0, balance_peak * (loss_allowance_pct*TWE + drop_since_peak_pct))
se pnl_clip < 0 e |pnl| > allowance:  close_qty *= allowance/|pnl|
```
Il budget **si ricarica quando il bot guadagna** (sale il picco) e **si erode col drawdown fino ad azzerarsi**, spegnendo l'unstuck da solo. Non può andare in spirale. La differenza fra questo e un unstuck senza tetto è tutta qui.

## Quali pezzi reggono davvero l'impianto (A/B misurate il 2026-08-31)
Tre ablazioni sulla **stessa** finestra 2024-12-10 → 2026-08-06, dati bybit, saldo 7353, config live, cambiando **un solo parametro** per volta. Configs su debian: `bt_cmp_full.json` (base), `bt_cmp_full_nogrid.json`, `bt_cmp_th1475.json`, `bt_cmp_th300.json`.
```
                            adg      drawdown   completion  giorni_max_in_pos
base                     1,0408%      27,99%       1,00           4,0
close grid OFF           0,7771%      99,97%       0,67          47,2
  (close.trailing_grid_ratio 0,1 -> 1,0)
exit_min_gain 0,646 -> 1,475%   0,1760%   99,19%   0,14          11,7
exit_min_gain 0,646 -> 3,0%     0,4564%   99,36%   0,14          12,5
```
**Entrambi i pezzi contribuiscono pochissimo al pnl diretto e reggono tutto l'impianto.** L'attribuzione contabile del pnl per tipo di fill dice: `close_panic_long` (uscita 4RSI) 96%, close grid 1,7%, trailing 2,3%. Ma togliere la close grid porta il drawdown al 99,97%, e alzare `exit_min_gain` liquida il conto al 14% della finestra.
⚠️ **Regola generale: l'attribuzione del pnl per tipo di fill misura chi incassa, non chi rende possibile incassare.** Il 4RSI chiude in guadagno posizioni che la griglia d'ingresso ha mediato e la close grid ha alleggerito. Ci sono cascato in entrambe le direzioni: prima chiamando la close grid "quasi decorativa" perché faceva 12 chiusure su 68, poi la sessione freqtrade stava per scartarla perché rende l'1,7%. Solo l'ablazione risponde.
Il meccanismo comune: **soglia d'uscita bassa e close grid servono a liberare esposizione in fretta**, non a incassare. Alzando la soglia le posizioni restano appese (durata massima da 4 a 12 giorni), la WE resta al tetto, la griglia non ha spazio per mediare il ribasso successivo, il conto salta.

### Le soglie d'ingresso sono il pezzo che regge di più (ablazioni del 2026-09-02)
Richieste dalla sessione freqtrade per capire dove sta l'edge: il nostro bot con le **loro** soglie d'ingresso (osc `-12,505`, stoch `37,369`, EMA `-0,9%` invece di `-23,87` / `12,70` / `-1,2%`), oppure con la **loro** geometria (`initial_qty_pct` 0,069, `grid_double_down_factor` 1,365, TWEL 2,19), tutto il resto invariato. Configs su debian: `abl_ftentry_{full,ribasso}.json`, `abl_ftgeom_{full,ribasso}.json`.
```
                              full 2024-12-05→2026-08-31          ribasso 2025-09-18→12-18
live                          +41.474%  dd 25,2%  1029 pos        +144%   dd 15,8%  170 pos, 6 WE piene
soglie ingresso freqtrade     LIQUIDATO 2025-03-06 (14%)          LIQUIDATO 2025-10-10 (25%), 54 pos, 2 WE piene
geometria freqtrade           LIQUIDATO 2025-03-11 (15%)          +52%    dd 53,3%  116 pos, 18 WE piene
```
**L'edge sta nell'ingresso selettivo; la griglia densa serve a sopravvivere dato quell'ingresso, non regge da sola.** A `-12,5/37` si entra sul primo cedimento e la griglia si carica *durante* la vera discesa: la media resta troppo alta per il rimbalzo di +0,65%. Nel ribasso bastano 54 posizioni e 2 a WE piena per morire: non uccide la coda lunga, uccide **una** posizione aperta troppo presto. Senza stop, una sola basta.
Meccanismo di sopravvivenza nel ribasso (6 posizioni a WE piena, tutte chiuse in utile in 6–25 h): l'esposizione piena arriva a −8/−12% dalla prima entrata con media a **−5,2/−6,4%**, da lì non si compra più; l'uscita chiede media+0,65% cioè **+5/+8% dal minimo**, che HYPE ha sempre fatto. Peggior equity non realizzata −15,8% di conto (22/11/2025). Unstuck ed enforcer TWEL: **zero fill in tutta la storia**, sono valvole mai aperte. Il limite reale è la liquidazione a circa −30% dalla media (leva 10 cross, notional 2,93× equity), mai avvicinata in-sample.

## Commissioni effettive per tipo (misurate sui fill, non dedotte dalla config)
```
entry_grid / entry_initial / close_grid / close_trailing   0,0150%   maker
close_panic_long (uscita 4RSI)                             0,0550%   TAKER
```
`calc_panic_close` prezza a `ask − 1 tick` per il long: **attraversa lo spread**. La gamba che porta il 96% del pnl è taker. Giro completo 0,070%; fee totali 220.269 su 3.671.682 di lordo = **6,0%**.
⚠️ Nel confrontare i costi con un'altra strategia: **la leva si semplifica** nel rapporto fee/lordo (moltiplica costo e guadagno lordo nella stessa misura). La variabile che comanda è il **guadagno per trade**, non la leva.

## Distribuzione dei guadagni realizzati dall'uscita 4RSI (994 fill)
Mediana **+1,278%** di prezzo vs `pprice`, p5 +0,552%, max +7,346%. **Oltre +2% sta il 45,9% del pnl lordo, prodotto dal 25,5% dei fill**: la coda destra non è un residuo.
⚠️ 117 fill su 994 hanno realizzato **meno** della soglia nominale 0,646%, minimo +0,127%: il cancello si valuta su `ob.bid` al segnale, l'esecuzione esce taker con slippage. La soglia effettiva è più morbida di quella nominale.
Terzo cancello che non è un parametro e non sta nella config: `candle_color > 0.0` — l'ultima candela 5m chiusa dev'essere **verde** (`orchestrator.rs:2575`), in AND con osc, stoch e gain.

## Disattivato nel candidato live
- **`hsl` (hard stop loss)**: `enabled: false`. La meccanica esiste (tier giallo/arancione/rosso, `red_threshold` 0.0522, cooldown 2780 min dopo un rosso). ⚠️ **Non verificato** se sia stato bocciato in ablazione o semplicemente non selezionato dal fronte — non spacciare la non-selezione per bocciatura.
- short completamente disattivato.

Vedi anche `mem:rylos_4rsi_prototype`, `mem:optimize_workflow`.
