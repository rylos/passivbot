# uso: deploy_rust.sh hl|bybit  (su amazon) - deploy con cambio Rust
x=$1; d=/opt/passivbot-$x; cfg=configs/live/config_${x}_4rsi.json
export PATH=$HOME/.cargo/bin:$PATH
touch ~/watchdog/${x}_maintenance
cd $d || exit 1
git fetch -q fork && git merge -q --ff-only fork/rylos-4rsi-proto || { echo "MERGE FALLITO"; rm -f ~/watchdog/${x}_maintenance; exit 1; }
git log --oneline -1
fp=$(venv/bin/python -c 'import sys;sys.path.insert(0,"src");import rust_utils as r;print(r.source_fingerprint())')
t0=$(date +%s)
(cd passivbot-rust && PASSIVBOT_RUST_SOURCE_FINGERPRINT=$fp VIRTUAL_ENV=$d/venv $d/venv/bin/python -m maturin build --release >/tmp/prebuild_$x.log 2>&1) || { echo "PREBUILD FALLITO"; tail -5 /tmp/prebuild_$x.log; exit 1; }
echo "prebuild $(( $(date +%s)-t0 ))s"
tmux send-keys -t ry-$x.0 C-c
for i in $(seq 40); do pgrep -f "main.py $cfg" >/dev/null || break; sleep 2; done
if pgrep -f "main.py $cfg" >/dev/null; then echo "NON SI FERMA"; exit 1; fi
t1=$(date +%s)
venv/bin/python -c 'import sys;sys.path.insert(0,"src");import rust_utils as r;r.check_and_maybe_compile();print("rust ok")' 2>&1 | tail -2
echo "build $(( $(date +%s)-t1 ))s"
tmux send-keys -t ry-$x.0 "venv/bin/python src/main.py $cfg" C-m
sleep 75
L=$(ls -t $d/logs/*.log | head -1)
grep -m1 "python=" $L | cut -c1-200
grep -cE "ERROR|Traceback" $L
grep "\[health\] bot=" $L | tail -1 | cut -c1-120
pgrep -f "main.py $cfg" >/dev/null && rm -f ~/watchdog/${x}_maintenance && echo "OK manutenzione tolta"
