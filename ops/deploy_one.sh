# uso: deploy_one.sh hl|bybit  (su amazon)
x=$1; d=/opt/passivbot-$x; cfg=configs/live/config_${x}_4rsi.json
touch ~/watchdog/${x}_maintenance
cd $d || exit 1
git fetch -q fork && git merge -q --ff-only fork/rylos-4rsi-proto || { echo "MERGE FALLITO"; rm -f ~/watchdog/${x}_maintenance; exit 1; }
git log --oneline -1
tmux send-keys -t ry-$x.0 C-c
for i in $(seq 40); do pgrep -f "main.py $cfg" >/dev/null || break; sleep 2; done
if pgrep -f "main.py $cfg" >/dev/null; then echo "NON SI FERMA"; exit 1; fi
tmux send-keys -t ry-$x.0 "venv/bin/python src/main.py $cfg" C-m
sleep 75
L=$(ls -t $d/logs/*.log | head -1)
grep -m1 "python=" $L | cut -c1-200
grep -cE "ERROR|Traceback" $L
grep "\[health\] bot=" $L | tail -1 | cut -c1-120
pgrep -f "main.py $cfg" >/dev/null && rm -f ~/watchdog/${x}_maintenance && echo "OK manutenzione tolta"
