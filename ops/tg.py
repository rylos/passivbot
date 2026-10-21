#!/usr/bin/env python3
# Invia un messaggio a Claude RyLoS Bot (chat 46772914) con le credenziali su amazon (~/watchdog/telegram.json).
# Con --gruppo lo stesso messaggio va anche al gruppo RyLoS-Trading (group_chat_id): per gli avvisi di correzioni e deploy.
import base64, subprocess, sys
args = sys.argv[1:]
gruppo = "--gruppo" in args
args = [a for a in args if a != "--gruppo"]
msg = base64.b64encode(" ".join(args).encode()).decode()
remote = f'''
import base64, json, urllib.request, urllib.parse
c = json.load(open("/home/admin/watchdog/telegram.json"))
chats = [c["chat_id"]] + ([c["group_chat_id"]] if {gruppo!r} else [])
for chat in chats:
    data = urllib.parse.urlencode({{"chat_id": chat, "text": base64.b64decode("{msg}").decode()}}).encode()
    r = urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % c["token"], data, timeout=20)
    print("ok" if json.load(r).get("ok") else "errore")
'''
p = subprocess.run(["ssh", "-o", "ConnectTimeout=15", "-o", "BatchMode=yes", "admin@amazon.ziliani.net", "python3", "-"],
                   input=remote, text=True, capture_output=True)
print(p.stdout.strip() or p.stderr.strip()[-200:])
