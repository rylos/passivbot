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

## Disattivato nel candidato live
- **`hsl` (hard stop loss)**: `enabled: false`. La meccanica esiste (tier giallo/arancione/rosso, `red_threshold` 0.0522, cooldown 2780 min dopo un rosso). ⚠️ **Non verificato** se sia stato bocciato in ablazione o semplicemente non selezionato dal fronte — non spacciare la non-selezione per bocciatura.
- short completamente disattivato.

Vedi anche `mem:rylos_4rsi_prototype`, `mem:optimize_workflow`.
