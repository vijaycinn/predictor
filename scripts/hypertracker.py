#!/usr/bin/env python3
"""HyperTracker (CoinMarketMan) — crypto perps research tool.

Two data paths:
1. FREE (no key): scrape the public perps dashboard — OI, funding, whale OI %,
   24h whale bias per asset. Live table, no auth.
2. API (key in env HYPERTRACKER_API_KEY): position heatmap (cohort long/short
   bias), liquidation heatmap export (price-bin liquidation VALUE — the real
   liquidation-pool data for BTC strike mapping), liquidation fills.

Use case (VJ): verify "liquidation pool at $62K" claims with real on-chain
Hyperliquid data, map clusters to Kalshi one-touch strikes (round down to
$2.5K ladder), and read whale bias as independent direction signal.

API docs: https://docs.coinmarketman.com/endpoints/position-heatmap.md
           https://docs.coinmarketman.com/endpoints/liquidation-data.md
"""
import json
import os
import re
import sys
import urllib.request

HT_API = "https://ht-api.coinmarketman.com"
DASH = "https://app.coinmarketman.com/hypertracker/perps"
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def _get(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers=headers or UA)
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def _get_text(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")


# ---------------------------------------------------------------- free scrape

PERP_ROW = re.compile(
    r'<td class="[^"]*">(?P<name>[^<]{1,12})</td>'
    r'.*?(?P<last>[\d,]+\.\d+)'
    r'.*?(?P<vol>[\d,]+\.\d+[MB]?)'
    r'.*?(?P<oi>[\d,]+\.\d+[MB]?)'
    r'.*?(?P<funding>[+-]?0\.\d+)'
    r'.*?(?P<whale>\d+\.\d+)%'
    r'.*?(?P<bias>[A-Za-z ]+?)</td>',
    re.S,
)


def scrape_perps(wanted=None):
    """Parse the public perps table. Returns list of dicts. No key needed."""
    html = _get_text(DASH)
    # extract table rows between <tbody> and </tbody>
    m = re.search(r"<tbody>(.*?)</tbody>", html, re.S)
    body = m.group(1) if m else html
    # split on <tr
    rows_html = re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S)
    out = []
    for rh in rows_html:
        tds = re.findall(r"<td[^>]*>(.*?)</td>", rh, re.S)
        if len(tds) < 8:
            continue
        def clean(x):
            x = re.sub(r"<[^>]+>", "", x)
            return x.strip()
        name = clean(tds[0])
        last = clean(tds[1])
        vol = clean(tds[2])
        oi = clean(tds[3])
        funding = clean(tds[4])
        whale = clean(tds[5]) if len(tds) > 5 else ""
        bias = clean(tds[6]) if len(tds) > 6 else ""
        if not name or not re.match(r"^[\d,]+\.\d+$", last):
            continue
        out.append({"coin": name, "last": last, "vol24": vol, "oi": oi,
                    "funding": funding, "whale_oi_pct": whale, "whale_bias": bias})
    if wanted:
        out = [r for r in out if r["coin"] in wanted]
    return out


# ------------------------------------------------------------------- API legs

def api_heatmap(openedWithin="24h", key=None):
    """Position heatmap: per-coin cohort long/short bias. Needs key."""
    key = key or os.environ.get("HYPERTRACKER_API_KEY")
    if not key:
        return {"error": "HYPERTRACKER_API_KEY not set"}
    url = f"{HT_API}/api/external/positions/heatmap?openedWithin={openedWithin}"
    try:
        return _get(url, {"Authorization": f"Bearer {key}", **UA})
    except Exception as e:
        return {"error": str(e)[:120]}


def api_liquidation_heatmap(coin="BTC", key=None):
    """Liquidation heatmap export: price-bin liquidation VALUE + counts.
    THIS is the data for liquidation-pool -> Kalshi strike mapping."""
    key = key or os.environ.get("HYPERTRACKER_API_KEY")
    if not key:
        return {"error": "HYPERTRACKER_API_KEY not set"}
    url = f"{HT_API}/api/external/exports/coins/{coin}/liquidation-heatmap"
    try:
        return _get(url, {"Authorization": f"Bearer {key}", **UA})
    except Exception as e:
        return {"error": str(e)[:120]}


def api_liquidation_fills(coin="BTC", limit=20, key=None):
    """Recent liquidation fills. Needs key."""
    key = key or os.environ.get("HYPERTRACKER_API_KEY")
    if not key:
        return {"error": "HYPERTRACKER_API_KEY not set"}
    url = f"{HT_API}/api/external/fills/liquidation?coin={coin}&limit={limit}"
    try:
        return _get(url, {"Authorization": f"Bearer {key}", **UA})
    except Exception as e:
        return {"error": str(e)[:120]}


def strike_map(price):
    """Map a liquidation cluster price to nearest Kalshi one-touch strike
    (round DOWN to $2.5K ladder). Returns (strike_dollars, series)."""
    if price >= 65000:
        return (int(price // 2500 * 2500), "KXBTCMAXMON")
    return (int(price // 2500 * 2500), "KXBTCMINMON")


# ---------------------------------------------------------------------- main

def main():
    args = sys.argv[1:]
    coins = []
    if args and args[0] != "--api":
        coins = [c.upper() for c in args[0].split(",")]
    key = os.environ.get("HYPERTRACKER_API_KEY")

    print("=== HYPERTRACKER PERPS (free dashboard) ===")
    try:
        perps = scrape_perps(wanted=set(coins) if coins else None)
        if perps:
            for r in perps[:25]:
                print(f"  {r['coin']:6s} last {r['last']:>12s}  vol24 {r['vol24']:>10s}  "
                      f"OI {r['oi']:>10s}  funding {r['funding']:>8s}  whaleOI {r['whale_oi_pct']:>6s}%  "
                      f"{r['whale_bias']}")
        else:
            print("  parse failed — dashboard markup changed")
    except Exception as e:
        print(f"  scrape ERR: {str(e)[:100]}")

    if "--api" in args or key:
        print("\n=== HYPERTRACKER API ===")
        if not key:
            print("  (no HYPERTRACKER_API_KEY — free dashboard only)")
        else:
            for c in (coins or ["BTC", "ETH"]):
                hm = api_liquidation_heatmap(c, key)
                if isinstance(hm, dict) and isinstance(hm.get("heatmap"), list):
                    print(f"\n  {c} LIQUIDATION HEATMAP (price bins, $ value):")
                    bins = hm["heatmap"]
                    # highlight bins around spot and the biggest clusters
                    bins_sorted = sorted(bins, key=lambda b: b.get("liquidationValue", 0), reverse=True)[:8]
                    for b in bins_sorted:
                        lo, hi = b.get("priceBinStart"), b.get("priceBinEnd")
                        strike, series = strike_map(hi)
                        print(f"    ${lo:,.0f}-${hi:,.0f}: liq ${b.get('liquidationValue',0):,.0f} "
                              f"({b.get('positionsCount',0)} pos) -> strike ${strike:,} {series}")
                else:
                    print(f"  {c} liq heatmap: {hm}")
                pos = api_heatmap("24h", key)
                if isinstance(pos, dict) and isinstance(pos.get("heatmap"), list):
                    for h in pos["heatmap"]:
                        if h.get("coin") == c:
                            print(f"  {c} cohort bias: long ${h.get('totalLongValue',0):,.0f} / short "
                                  f"${h.get('totalShortValue',0):,.0f} ({h.get('count',0)} positions)")

if __name__ == "__main__":
    main()
