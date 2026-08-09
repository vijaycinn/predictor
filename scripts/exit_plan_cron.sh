#!/usr/bin/env bash
# Cron wrapper for exit_plan.py (rule 6b take-profit exits).
# Watchdog pattern: SILENT when all exits resting; prints only when orders
# placed or errors. Run every 12h via cronjob no_agent.
set -uo pipefail
cd /data/workspace/predictor || exit 1
python3 scripts/exit_plan.py --place --quiet
