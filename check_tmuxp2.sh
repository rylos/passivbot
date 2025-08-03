#!/bin/bash

cd /opt/passivbot
# Conta il numero di processi Python in esecuzione (bots)
num_python_processes=$(ps aux | grep "[p]ython src/main.py configs/live/config_hl.json" -c)

# Numero desiderato dei bot (bots number) 
bots_num=1

# Verifica se il numero di processi Python è inferiore a quello desiderato
if [ $num_python_processes -lt $bots_num ]; then
  #echo "Il numero dei bot in esecuzione è inferiore. Eseguo start_tmuxp2.sh..."
  /usr/bin/bash /opt/pb/start_tmuxp2.sh
else
  #echo "Il numero dei bot in esecuzione è corretto."
  #healthchecks.io ping ok
  curl -fsS -m 10 --retry 5 -o /dev/null https://hc-ping.com/58e8c8a4-4a3c-4bd0-b153-ce0a83681d02
fi
