#!/usr/bin/env bash
# Sync trading skills (predict + live-ops) from Hermes skills dir into the
# predictor repo, then commit + push. Run after skill_manage patches so the
# GH repo stays in sync with skill upgrades (VJ requirement 2026-08-06).
set -euo pipefail

REPO="/data/workspace/predictor"
SKILLS_SRC="/data/.hermes/skills/research"
SKILLS_DST="$REPO/skills"

for skill in predict prediction-market-live-ops; do
  if [ -d "$SKILLS_SRC/$skill" ]; then
    rm -rf "$SKILLS_DST/$skill"
    cp -r "$SKILLS_SRC/$skill" "$SKILLS_DST/$skill"
    find "$SKILLS_DST/$skill" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
    echo "synced: $skill"
  else
    echo "WARN: skill dir missing: $SKILLS_SRC/$skill"
  fi
done

cd "$REPO"
git add skills/
if git diff --cached --quiet; then
  echo "no changes — skills already in sync"
  exit 0
fi
git commit -m "sync: skills → repo (predict + prediction-market-live-ops)

Auto-mirror of Hermes skills dir (SKILL.md + references + scripts).
Run scripts/sync_skills.sh after skill_manage patches." | tail -2
git push origin master 2>&1 | tail -2
echo "pushed."
