import sys
import pandas as pd
import plotly.graph_objs as go
import plotly.offline as pyo
import os

# Controllo argomenti
if len(sys.argv) < 2:
    print("Uso: python plot_pnl.py path/fills.csv")
    sys.exit(1)

# Caricamento file
csv_path = sys.argv[1]
df = pd.read_csv(csv_path)
df['giorni'] = df['minute'] / 1440.0

# Gruppo per coin
grouped = df.groupby('coin')

# --- Grafico lineare ---
line_traces = []
for coin, data in grouped:
    trace = go.Scatter(
        x=data['giorni'],
        y=data['pnl'].cumsum(),
        mode='lines',
        name=coin
    )
    line_traces.append(trace)

layout_line = go.Layout(
    title='PNL dei Coin nel Tempo (Lineare)',
    xaxis=dict(title='Tempo (giorni)'),
    yaxis=dict(title='PNL cumulativo'),
)

fig_line = go.Figure(data=line_traces, layout=layout_line)
output_path_line = os.path.join(os.path.dirname(csv_path), 'pnl_plot_interactive.html')
pyo.plot(fig_line, filename=output_path_line, auto_open=False)

# --- Grafico logaritmico ---
log_traces = []
for coin, data in grouped:
    pnl_cumsum = data['pnl'].cumsum()
    pnl_cumsum[pnl_cumsum <= 0] = float('nan')
    trace = go.Scatter(
        x=data['giorni'],
        y=pnl_cumsum,
        mode='lines',
        name=coin
    )
    log_traces.append(trace)

layout_log = go.Layout(
    title='PNL dei Coin nel Tempo (Logaritmica)',
    xaxis=dict(title='Tempo (giorni)'),
    yaxis=dict(title='PNL cumulativo (log)', type='log'),
)

fig_log = go.Figure(data=log_traces, layout=layout_log)
output_path_log = os.path.join(os.path.dirname(csv_path), 'pnl_plot_log_interactive.html')
pyo.plot(fig_log, filename=output_path_log, auto_open=False)

print(f"Grafico interattivo lineare: {output_path_line}")
print(f"Grafico interattivo logaritmico: {output_path_log}")
