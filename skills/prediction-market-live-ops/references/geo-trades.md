# Geo-trades pipeline — DeItaone feed → Kalshi shortlist (rule 18)

Full recipe for the 7pm CST geo-trades scan. Codified in RULES.md rule 18,
memory `[GEO-TRADES]`, script `scripts/geo_scan.py`.

## Core mapping

Choke-point incidents (Hormuz, Suez, Bab el-Mandeb, straits) →
**oil ▲, gold ▲, VIX ▲, risk-OFF**. De-escalation → inverse (risk-ON).
The feed is the tiebreaker for after-hours/weekend moves; thin after-hours
quotes (USO post-market, etc.) are NOT tradable signals on weekends.

## Feed fetch (verified 2026-08-02)

```bash
HOME=/data/.hermes/home /data/.hermes/home/.local/bin/xurl \
  '/2/users/2704294333/tweets?max_results=20&tweet.fields=created_at,public_metrics'
```
- DeItaone = *Walter Bloomberg, id `2704294333`.
- xurl installed PERSISTENT at `/data/.hermes/home/.local/bin/xurl` (npm
  global = ephemeral container FS; local install survives). Auth in
  `/data/.hermes/home/.xurl` (oauth1). Always set `HOME=/data/.hermes/home`.
- Fallback: `web_extract` on https://x.com/DeItaone (X may rate-limit).

## Classification keywords (scripts/geo_scan.py)

- ESCALATE: strike(s), attack(s), war, missile, drone, sanction, seize(d),
  blockade, shutdown, conflict, military, troops, invasion, escalate,
  threaten, nuclear, houthi, strait, chokepoint, kill.
- DE-ESCALATE: deal, ceasefire, truce, negotiation(s), talks, agreement,
  delay(ed), postpone, call off, pullback, withdraw, diplomatic, peace,
  pause, halt, suspend(ed), "signal of friendship".
- CHOKEPOINT: hormuz, suez, bab el-mandeb, strait, chokepoint, gulf, red sea,
  canal. MIXED = both escalate + de-escalate keywords (e.g. "delayed strikes").
- **TRUMP = BIGGEST MARKET MOVER (VJ 2026-08-02)**: US president statements
  (via DeItaone) dominate direction. `is_trump` = text contains trump/president.
  Trump override: TRUMP-ESCALATION (strike/attack/war/missile/tariff/sanction/
  punish), TRUMP-DE-ESCALATION (ceasefire/deal/negotiation/talks/delay/peace/
  call off/friendship), TRUMP-MIXED (both), TRUMP-TRADE (tariff/trade/commerce/
  china/europe/import/export). Output marks Trump tweets with ★.
- Direction score = (choke_dee − choke_esc)×2 + (recent6_dee − recent6_esc)
  + (t_dee − t_esc)×3 + (t_trade − t_mixed)×2: ≤−2 → RISK-OFF; ≥2 → RISK-ON;
  else lean/neutral. Recent-6 tweets weighted (fresh signal), choke-point ×2,
  **Trump ×3** (his words move oil/commodities/commerce hardest).

## Time gating

- Window: 19:00-20:00 America/Chicago ONLY. Script returns silently outside
  it (watchdog: empty stdout = no cron delivery).
- Cron: `geo-trades-scan`, schedule `0 0 * * *` (UTC) = 7pm CT. NOT `0 19 * * *`
  (that's 19:00 UTC = 14:00 CT). Server timezone is Etc/UTC — always convert
  CT → UTC before writing cron schedules.
- Test recipe: monkeypatch `gs.datetime` with a fake `datetime(2026,8,2,19,30,
  tzinfo=ZoneInfo("America/Chicago"))` subclass to force the window, then
  call `gs.main()`.

## Kalshi shortlist mapping

- WTI: series `KXWTI` (daily settle events close 18:30Z, e.g.
  `KXWTI-26AUG0314-T80.49`); monthly `KXWTIMAX` / `KXWTIMIN`.
- Brent: `KXBRENTD`. Gold: `KXGOLDD` (daily) / `KXGOLDMON` (monthly).
- No VIX binary on Kalshi — VIX = directional read only.
- risk-ON (de-escalation): oil/gold BELOW strikes — NO side or cheap low
  strikes. risk-OFF (escalation): above strikes, cheap high strikes.
- Same hunt gates: limit-only, YES ≤40c band, ≥50% win floor from the geo
  feed as independent source, TTL event-aware.

## Verified example (2026-08-02)

DeItaone 21:40-21:50Z: Hormuz deal in sight; Saudi/UAE/Qatar/Iran urged delay
of strikes; Iran negotiations Monday. → DE-ESCALATION → RISK-ON (oil ▼).
Killed the WTI ≥84.49 @ 10c spike-strike candidate that USO post-market +3.5%
suggested. Lesson: geo feed BEFORE options/technicals; after-hours ETF quotes
alone are fragile.

## Output style (VJ preference, embedded)

Caveman terse, ACTION-first (BUY/SKIP first word), trend icons ▲▼ for streaks.
**No tables for individual-match analysis cards** (VJ reads on phone — wide
tables don't render). EXCEPTION: scanner/multi-candidate output IS a compact
table (VJ explicitly asked 2026-08-02: "I want scanner output as table. Avoid
verbose reasons with bias on what I need to choose") — one row per candidate,
BUY rows → WATCH → SKIP, decision-first. Two formats: card = single match
deep-dive, table = ranked shortlist.
