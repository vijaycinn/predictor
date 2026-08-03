#!/usr/bin/env python3
"""Morning X news pull — DeItaone feed (VJ 2026-08-03).

Pulls latest DeItaone (Walter Bloomberg) tweets for the 9:30am CT news
brief. Prints raw feed; agent cron layer turns it into a digest with
Kalshi implications (see cron prompt). Self-gates to morning window
(14:30Z = 9:30am CT) — silent otherwise (watchdog pattern).
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

XURL = os.environ.get("XURL_BIN", "/data/.hermes/home/.local/bin/xurl")
HOME = "/data/.hermes/home"
DEITAONE_ID = "2704294333"


def fetch_feed(n=20):
    url = f"/2/users/{DEITAONE_ID}/tweets?max_results={n}&tweet.fields=created_at,public_metrics"
    env = dict(os.environ, HOME=HOME)
    r = subprocess.run([XURL, url], capture_output=True, text=True, timeout=60, env=env)
    if r.returncode != 0:
        return []
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        return []
    return d.get("data", [])


def main():
    tweets = fetch_feed(20)
    if not tweets:
        print("DeItaone feed: no tweets returned (xurl error?).")
        return
    for t in tweets:
        ts = t.get("created_at", "?")[11:16]
        text = t.get("text", "").replace("\n", " ")
        print(f"[{ts}Z] {text}")


if __name__ == "__main__":
    main()
