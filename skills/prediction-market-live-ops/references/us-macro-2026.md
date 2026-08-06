# US Macro & Election Calendar — 2026 (for economic/political trade analysis)

Captured 2026-08-02 from VJ's analysis. Factor into ALL Fed/economic market
research until year-end.

## Key dates

- **US Midterm election: Tuesday Nov 3, 2026.** Post-election political climate
  may shift economic/political incentives — administration changes posture after
  the vote, not before.
- FOMC meetings remaining in 2026 (from federalreserve.gov calendar):
  - Sept 15-16, 2026 (decision markets close ~Sep 16)
  - Oct 27-28, 2026 (decision markets close ~Oct 28)
  - Dec 8-9, 2026 (decision markets close ~Dec 9)
  - There is NO November FOMC meeting. "Between now and Nov" = Sept + Oct only.

## The cut-then-hike path (VJ thesis, 2026-08-02)

- Political incentive: Fed may CUT rates BEFORE the Nov 3 election (pressure to
  show easing), then HIKE by Dec 2026 once the election is behind it.
- This invalidates naive "no hike by Dec 31" bets (e.g. `FEDHIKE-26DEC31` NO at
  0.32): a pre-election cut does not rule out a Dec hike. Cut-then-hike is a
  real path the market may be pricing (market at 68% YES hike).
- Bank consensus (JPM: hold rest of 2026, hike Sept 2027; Goldman: hikes
  unlikely, cuts June/Dec 2027) does NOT model political dynamics. Treat bank
  base cases as incomplete for pre/post-election windows.

## Market expressions (Kalshi, verified 2026-08-02)

- `FEDHIKE-26DEC31` — any hike by Dec 31, 2026. YES ~0.68 (subtitle "Before 2027").
- `KXFEDDECISION-26SEP-H25/H0/C25` — Sept 16 meeting hike 25bp / hold / cut 25bp.
- `KXFEDDECISION-26OCT-H25/H0/C25` — Oct 28 meeting.
- `KXFED-26SEP-T3.75` etc. — upper bound of fed funds target after Sept meeting.
- `KXRATECUT-26DEC31` / `KXRATECUTCOUNT-26DEC31-T0/T1` — any cut / count by Dec 31.
- Polymarket: "Fed rate hike in 2026?" (~0.665), "no Fed rate cuts in 2026?"
  (~0.885), Sept-specific hike/cut markets.

## Analysis checklist for Fed markets

1. Check date vs midterm: is the decision pre- (Sept/Oct) or post- (Dec) election?
2. Ask: could politics push a cut pre-election + hike post-election? If yes,
   "no hike" and "no cut" year-end bets are both exposed.
3. Verify independent prob from Polymarket (global sample) — Kalshi book alone
   is NOT a valid source (VJ rule).
4. Remember NO-side semantics: for a NO buy, approved_price = independent NO prob
   = 1 − indep YES, must be ≥ 0.50 (min_win_prob guard, pre_flight NO branch).
