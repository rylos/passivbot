import sys
import pandas as pd
import matplotlib.pyplot as plt
import os

# Controllo argomenti
if len(sys.argv) < 2:
    print("Uso: python plot_pnl.py path/fills.csv")
    sys.exit(1)

# Caricamento file
csv_path = sys.argv[1]
df = pd.read_csv(csv_path)

# Conversione minuti → giorni
df['giorni'] = df['minute'] / 1440.0  # 1440 minuti in un giorno

# Preparazione dati
grouped = df.groupby('coin')

# --- Grafico con scala lineare ---
plt.figure(figsize=(20, 10))
for coin, data in grouped:
    plt.plot(data['giorni'], data['pnl'].cumsum(), label=coin)
plt.xlabel('Tempo (giorni)')
plt.ylabel('PNL cumulativo')
plt.title('PNL dei Coin nel Tempo (Lineare)')
plt.legend()
plt.grid(True)
output_path_linear = os.path.join(os.path.dirname(csv_path), "pnl_plot.png")
plt.savefig(output_path_linear, dpi=300)
plt.close()

# --- Grafico con scala logaritmica ---
plt.figure(figsize=(20, 10))
for coin, data in grouped:
    pnl_cumsum = data['pnl'].cumsum()
    pnl_cumsum[pnl_cumsum <= 0] = float('nan')  # evita log di valori <= 0
    plt.plot(data['giorni'], pnl_cumsum, label=coin)
plt.xlabel('Tempo (giorni)')
plt.ylabel('PNL cumulativo (scala log)')
plt.title('PNL dei Coin nel Tempo (Logaritmica)')
plt.yscale('log')
plt.legend()
plt.grid(True, which='both')
output_path_log = os.path.join(os.path.dirname(csv_path), "pnl_plot_log.png")
plt.savefig(output_path_log, dpi=300)
plt.close()

print(f"Grafico lineare salvato in: {output_path_linear}")
print(f"Grafico logaritmico salvato in: {output_path_log}")
