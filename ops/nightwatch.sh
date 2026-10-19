#!/bin/bash
# Sorveglianza ry-hl / ry-bybit: una riga per evento
# (processo giu', health fermo, ERROR/Traceback nuovi, ordini/fill close_panic, fill).
# Gira sul PC come servizio utente systemd (ops/passivbot-nightwatch.service):
# stato e log in ~/.local/state/passivbot-nightwatch, cosi' sopravvivono al riavvio.
ST=${NIGHTWATCH_DIR:-$HOME/.local/state/passivbot-nightwatch}/state
mkdir -p $ST
TG=$(dirname "$(readlink -f "$0")")/tg.py
echo "INIZIO sorveglianza"; touch $ST/first
IP=18.102.38.4
FAILS=0
while true; do
  r=$(getent hosts amazon.ziliani.net | awk '{print $1; exit}'); [ -n "$r" ] && IP=$r
  SSH="ssh -n -o ConnectTimeout=15 -o BatchMode=yes -o HostKeyAlias=amazon.ziliani.net admin@$IP"
  out=$($SSH '
    now=$(date +%s)
    for d in hl bybit; do
      cfg=config_${d}_4rsi.json
      ps aux | grep -q "[m]ain.py configs/live/$cfg" || echo "DOWN $d: processo assente"
      f=$(ls -t /opt/passivbot-$d/logs/2026*.log | head -1)
      echo "FILE $d $f $(wc -l < $f)"
      h=$(grep "\[health\]" $f | tail -1 | cut -c1-20)
      if [ -n "$h" ]; then
        age=$(( now - $(date -d "$h" +%s) ))
        [ $age -gt 2100 ] && echo "STALE $d: ultimo [health] ${age}s fa"
      fi
    done; echo OK' 2>&1)
  if ! echo "$out" | grep -q "^OK$"; then FAILS=$((FAILS+1)); [ $FAILS -eq 5 ] && echo "SSH fallito da 5 min: $(echo "$out" | tail -1)" && $TG "⚠️ passivbot monitor: amazon non raggiungibile da 5 min" >/dev/null; sleep 60; continue; fi
  [ $FAILS -ge 5 ] && echo "SSH di nuovo ok dopo $FAILS tentativi"; FAILS=0
  al=$(echo "$out" | grep -E "^(DOWN|STALE)" | sed 's/ [0-9]*s fa//')
  if [ -n "$al" ]; then echo "$al"; [ "$al" != "$(cat $ST/last_alert 2>/dev/null)" ] && $TG "⚠️ passivbot: $al" >/dev/null; fi
  echo "$al" > $ST/last_alert
  echo "$out" | grep "^FILE" | while read -r _ d f n; do
    prev_f=$(cat $ST/$d.f 2>/dev/null); prev_n=$(cat $ST/$d.n 2>/dev/null || echo 0)
    [ "$f" != "$prev_f" ] && prev_n=0 && [ -n "$prev_f" ] && echo "NUOVO LOG $d: $(basename $f) (riavvio)"
    if [ "$n" -gt "$prev_n" ] && [ ! -f $ST/first ]; then
      $SSH "sed -n '$((prev_n+1)),${n}p' $f" \
        | grep -E "ERROR|CRITICAL|Traceback|Fatal|close_panic|\[fill\]|post-only|crash|amend|taker|fresh book|entry gate|signal unavailable|entry_initial_normal_long \[(retire|new)\]|resting entries|no longer kept" \
        | grep -v "errors_1h" | grep -vE "T[0-9]{2}:[0-9][05]:[0-9]{2}Z .*entry gate .* closed" | cut -c1-260 | sed "s/^/$d | /" | head -20
    fi
    echo "$f" > $ST/$d.f; echo "$n" > $ST/$d.n
    t=$($SSH "python3 ~/watchdog/exec_timing.py $d last 1" 2>/dev/null | tail -1)
    tk=$(echo "$t" | cut -d"|" -f1-2)
    if [ -n "$t" ] && [ "$tk" != "$(cat $ST/$d.timing 2>/dev/null)" ]; then
      [ -f $ST/$d.timing ] && echo "TEMPI $d | $(echo "$t" | cut -d"|" -f3-)"
      echo "$tk" > $ST/$d.timing
    fi
  done
  rm -f $ST/first
  sleep 60
done
