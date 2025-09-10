#!/bin/bash

cd /opt/pb

# Controlla e riavvia singoli bot
bybit_processes=$(ps aux | grep "[p]ython src/main.py configs/live/config_bybit.json" -c)
hl_processes=$(ps aux | grep "[p]ython src/main.py configs/live/config_hl.json" -c)
hype_processes=$(ps aux | grep "[p]ython src/main.py configs/live/config_hype_only.json" -c)

if [ $bybit_processes -lt 1 ]; then
  zellij action write-chars "cd /opt/pb && source venv/bin/activate && python src/main.py configs/live/config_bybit.json" --session passivbot --pane bybit
  zellij action write-chars "Enter" --session passivbot --pane bybit
fi

if [ $hl_processes -lt 1 ]; then
  zellij action write-chars "cd /opt/pb && source venv/bin/activate && python src/main.py configs/live/config_hl.json" --session passivbot --pane hyperliquid
  zellij action write-chars "Enter" --session passivbot --pane hyperliquid
fi

if [ $hype_processes -lt 1 ]; then
  zellij action write-chars "cd /opt/pb && source venv/bin/activate && python src/main.py configs/live/config_hype_only.json" --session passivbot --pane hype
  zellij action write-chars "Enter" --session passivbot --pane hype
fi

# Healthcheck solo se tutti attivi
total_processes=$((bybit_processes + hl_processes + hype_processes))
if [ $total_processes -eq 3 ]; then
  curl -fsS -m 10 --retry 5 -o /dev/null https://hc-ping.com/d075b180-e7cf-4fa8-9fc5-423319d72d51
fi