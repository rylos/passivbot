#!/usr/bin/env python3
"""Registro movimenti del conto ry-bybit, in sola lettura, su stdout in JSON.

Gira su amazon: la chiave resta in /opt/passivbot-bybit/api-keys.json e non esce
da qui. Viene chiamato dal server docker con il timestamp di partenza in ms.
L'endpoint accetta finestre di massimo 7 giorni.
"""
import hashlib
import hmac
import json
import sys
import time
import urllib.parse
import urllib.request

API = "https://api.bybit.com/v5/account/transaction-log"
WEEK_MS = 7 * 24 * 3600 * 1000
RECV_WINDOW = "10000"
PAUSE = 0.25


def fetch(key, secret, params):
    query = urllib.parse.urlencode(params)
    stamp = str(int(time.time() * 1000))
    sign = hmac.new(secret.encode(), (stamp + key + RECV_WINDOW + query).encode(), hashlib.sha256).hexdigest()
    headers = {"X-BAPI-API-KEY": key, "X-BAPI-TIMESTAMP": stamp, "X-BAPI-RECV-WINDOW": RECV_WINDOW, "X-BAPI-SIGN": sign}
    with urllib.request.urlopen(urllib.request.Request(f"{API}?{query}", headers=headers), timeout=30) as resp:
        body = json.load(resp)
    if body.get("retCode") != 0:
        raise SystemExit(f"bybit retCode={body.get('retCode')} {body.get('retMsg')}")
    return body["result"]


def main():
    start = int(sys.argv[1])
    now = int(time.time() * 1000)
    with open("/opt/passivbot-bybit/api-keys.json") as fh:
        account = json.load(fh)["bybit_02"]
    rows = []
    while start < now:
        end = min(start + WEEK_MS - 1, now)
        cursor = ""
        while True:
            params = {"accountType": "UNIFIED", "currency": "USDT", "startTime": start, "endTime": end, "limit": 50}
            if cursor:
                params["cursor"] = cursor
            result = fetch(account["key"], account["secret"], params)
            rows += result.get("list", [])
            cursor = result.get("nextPageCursor") or ""
            time.sleep(PAUSE)
            if not cursor:
                break
        start = end + 1
    json.dump(rows, sys.stdout)


if __name__ == "__main__":
    main()
