#!/usr/bin/env python3
"""Compact live-score lookup via mcp-sports-hub (espn provider only).

Usage:
  espn_live.py --sport tennis --league wta [--date 20260809] [--player Sabalenka]

Walks ESPN tennis payload: tournament event -> groupings -> matches.
Prints one compact status line per matching match.
"""
import argparse, json, os, select, subprocess, sys

def call_tool(proc, name, args, timeout=40):
    def send(obj):
        proc.stdin.write(json.dumps(obj) + "\n"); proc.stdin.flush()
    def recv():
        r, _, _ = select.select([proc.stdout], [], [], timeout)
        if not r: return None
        line = proc.stdout.readline()
        return json.loads(line) if line.strip() else None
    send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
          "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                     "clientInfo": {"name": "espn_live", "version": "1.0"}}})
    recv()
    send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
    send({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
          "params": {"name": name, "arguments": args}})
    r = recv()
    if not r: raise TimeoutError("no response from MCP server")
    return r.get("result", {}).get("content", [])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", default="tennis")
    ap.add_argument("--league", default="wta")
    ap.add_argument("--date", default=None)
    ap.add_argument("--player", default=None)
    a = ap.parse_args()

    env = dict(os.environ); env["SPORTS_HUB_PROVIDERS"] = "espn"
    proc = subprocess.Popen(["npx", "-y", "mcp-sports-hub"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, env=env)
    try:
        args = {"sport": a.sport, "league": a.league}
        if a.date: args["date"] = a.date
        content = call_tool(proc, "espn_get_scoreboard", args)
        txt = "".join(c.get("text", "") for c in content)
        data = json.loads(txt)
        inner = json.loads(data["result"]) if isinstance(data.get("result"), str) else data

        def walk(o, out):
            if isinstance(o, dict):
                comps = o.get("competitions") or []
                for comp in comps:
                    names = []
                    for c in comp.get("competitors") or []:
                        nm = (c.get("athlete") or {}).get("displayName", "") or (c.get("team") or {}).get("displayName", "")
                        names.append(nm)
                    blob = " ".join(names)
                    if a.player is None or a.player.lower() in blob.lower():
                        st = comp.get("status", {}).get("type", {})
                        note = [n.get("text") for n in (comp.get("notes") or [])]
                        ls = {}
                        for c in comp.get("competitors") or []:
                            nm = (c.get("athlete") or {}).get("displayName", "") or (c.get("team") or {}).get("displayName", "")
                            ls[nm] = [(x.get("value"), x.get("tiebreak")) for x in (c.get("linescores") or [])]
                        out.append({"names": names, "status": st.get("description"),
                                    "detail": st.get("detail"), "note": note, "linescores": ls})
                for k, v in o.items():
                    if k in ("competitions", "groupings", "events", "matches", "children"):
                        walk(v, out)
            elif isinstance(o, list):
                for v in o: walk(v, out)
            return out

        matches = walk(inner, [])
        if not matches:
            print("no match found")
            sys.exit(1)
        for m in matches:
            print(f"{' | '.join(m['names'])}")
            print(f"  status: {m['status']} {m['detail'] or ''}".rstrip())
            if m["note"]: print(f"  note: {m['note'][0]}")
            for nm, ls in m["linescores"].items():
                print(f"  {nm}: {ls}")
    finally:
        proc.kill()

if __name__ == "__main__":
    main()
