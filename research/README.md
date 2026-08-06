# Research — vendored reference material (2026-08-06)

Assimilated third-party prediction-market research, vendored raw (MIT licensed)
for future reference. Distilled findings + integration decisions live in
`../RESEARCH_FINDINGS.md` (the actionable layer). This folder is the source
material — read it for depth, but the findings doc is the operating manual.

## Contents

| Dir | Source | What it is | Use |
|---|---|---|---|
| `prediction-market-alpha-playbook/` | github.com/AKCodez | 7-file strategy/methodology/antipattern playbook from production bots | **Highest value.** EDGES.md (~20 edge types), ANTIPATTERNS.md (silent failure modes), METHODOLOGY.md (paper→live graduation, Wilson lb95, cohort search), ARCHITECTURE.md, APIS.md, NEG_RISK_NO_CARRY.md |
| `kalshi-trading-bot-cli/` | github.com/OctagonAI | AI terminal: Kelly sizing, 5-gate risk engine, circuit breaker, edge computer, Kalshi API client | Kelly math (`src/risk/kelly.ts`), 5-gate risk (`src/risk/gate.ts`), retry/DLQ pattern (`src/tools/kalshi/api.ts`). NOTE: its `placeOrder` uses deprecated V1 endpoint — see findings doc §12 |
| `PolyKalshi_Client/` | github.com/RohitDayanand | Kalshi+Polymarket WS analytics platform: arb calculator, fee calculator, WS clients | Fee formula (`backend/master_manager/kalshi_fee_calculator.py`), 4-direction arb spreads (`arbitrage_calculator.py`), Kalshi WS mechanics (`kalshi_client/`) |

## Rejected (do not re-add)

`else24/kalshi-market-bot` — MALWARE (C2 beacon + reflective PE loader +
dropper). IoCs in `../RESEARCH_FINDINGS.md`. Clone deleted 2026-08-06.

## Vetting protocol (mandatory before using any external repo)

See `../RESEARCH_FINDINGS.md` security section + live-ops skill
"Supply-chain vetting". Summary: map full tree, read all network/ctypes files,
check for obfuscated endpoints, disabled TLS verification, embedded binaries,
PE-loading primitives. Never run unvetted clones.

## Upstreams (re-verify before trusting stale code)

- playbook: https://github.com/AKCodez/prediction-market-alpha-playbook
- Octagon CLI: https://github.com/OctagonAI/kalshi-trading-bot-cli
- PolyKalshi: https://github.com/RohitDayanand/PolyKalshi_Client
