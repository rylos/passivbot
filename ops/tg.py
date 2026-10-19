#!/usr/bin/env python3
# Invia un messaggio a Claude RyLoS Bot (chat 46772914) con le credenziali su amazon (~/watchdog/telegram.json).
import base64, subprocess, sys
msg = base64.b64encode(" ".join(sys.argv[1:]).encode()).decode()
remote = f'''
import base64, json, urllib.request, urllib.parse
c = json.load(open("/home/admin/watchdog/telegram.json"))
data = urllib.parse.urlencode({{"chat_id": c["chat_id"], "text": base64.b64decode("{msg}").decode()}}).encode()
r = urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % c["token"], data, timeout=20)
print("ok" if json.load(r).get("ok") else "errore")
'''
p = subprocess.run(["ssh", "-o", "ConnectTimeout=15", "-o", "BatchMode=yes", "admin@amazon.ziliani.net", "python3", "-"],
                   input=remote, text=True, capture_output=True)
print(p.stdout.strip() or p.stderr.strip()[-200:])
