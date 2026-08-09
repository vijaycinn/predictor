#!/usr/bin/env bash
# Auto-backup: sync Hermes trading skills + predictor repo changes to GH.
# Runs from cron (no_agent watchdog): SILENT when nothing changed, prints
# one line when pushed. VJ requirement 2026-08-06 — incremental backup.
set -uo pipefail

REPO="/data/workspace/predictor"
SKILLS_SRC="/data/.hermes/skills/research"
SKILLS_DST="$REPO/skills"

# ---- 1. mirror trading skills ----
for skill in predict prediction-market-live-ops; do
  if [ -d "$SKILLS_SRC/$skill" ]; then
    rm -rf "$SKILLS_DST/$skill"
    cp -r "$SKILLS_SRC/$skill" "$SKILLS_DST/$skill"
    find "$SKILLS_DST/$skill" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
  fi
done

# ---- 1b. mirror hermes config (no secrets) + live-score helper ----
cp /data/.hermes/config.yaml "$REPO/configs/hermes.config.yaml" 2>/dev/null || true
cp /data/.hermes/scripts/espn_live.py "$REPO/scripts/espn_live.py" 2>/dev/null || true

cd "$REPO" || exit 1

# ---- 2. stage everything (skills + tools + config + docs) ----
git add -A

if git diff --cached --quiet; then
  exit 0   # nothing changed — stay silent (watchdog pattern)
fi

# ---- 3. commit + push ----
git commit -q -m "backup: auto-sync $(date -u +%Y-%m-%dT%H:%MZ)

skills mirror (predict, prediction-market-live-ops) + repo changes.
Auto from scripts/auto_sync.sh via cron."
if git push origin master 2>&1; then
  echo "pushed: $(git rev-parse --short HEAD) $(git log -1 --format=%s)"
else
  echo "PUSH FAILED — $(git rev-parse --short HEAD) not on origin"
  exit 1
fi
