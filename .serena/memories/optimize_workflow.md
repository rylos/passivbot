# Workflow optimize + refinement (server debian, tmux "opt")

Metodologia consolidata (dettagli e storico nel wiki Joplin, nota "passivbot"):

1. **Run full-range**: bounds da `get_optimize_bounds_defaults()` con pin strutturali (n_positions [1,1], entry_cooldown [0,0], TWE [2.5,3]) e bounds rylos allargati. 500k iter, 26 cpu, `pareto_max_size` 1000. Esempio: `configs/hype_4rsi_long_v8_r1.json` → run `2026-07-24T09_03_41_..._f1f124cd`.
2. **Analisi manuale** del fronte con `src/tools/pareto_dash_dark.py` (Marco sceglie il candidato).
3. **Refinement ±20%**: bounds = candidato ±20% clampati al range full; pin invariati; TWE resta [2.5,3]; gruppi strategy inattivi RIMOSSI dai bounds (solo trailing_grid_v7); `bot` = candidato come seed; stessa finestra e budget. Esempio: `configs/hype_4rsi_long_v8_refine20_r2.json` → run `2026-07-25T02_49_45_..._65796f56`.
4. Selezione finale di Marco → deploy live (vedi memoria live_deployment).

Note operative:
- Lancio: `tmux send-keys -t opt.0 'cd /opt/passivbot && source venv/bin/activate; python3 src/optimize.py configs/<cfg>.json' C-m`.
- Stop: `pkill -INT -f "src/optimize.py"` (un singolo kill -INT spesso non basta), attendere "Shutdown complete".
- Monitoraggio: `tmux capture-pane -pt opt -S -N` + grep "Iter:"; ~600-730 iter/min con 26 cpu su 722 giorni HYPE → 500k iter ≈ 12-14h.
- ATTENZIONE pgrep via ssh: `pgrep -af pattern` matcha la propria shell ssh — usare `pgrep -f '^python...'` o verificare il comando.
- Backtest fino a oggi: serve `end_date` esplicita (default = oggi−2gg).
- I file in `pareto/` contengono anche `metrics.stats.*` → confronto candidati senza rifare backtest.
