# Mando Memory Vault

Long-term memory vault for Mando (Hermes agent) — plain Obsidian markdown, git-synced via the predictor repo.

## What lives here
- **Persona/** — who Mando is, how Mando communicates, standing rules
- **Agent-Behavior/** — working style, model policy, safety bounds
- **Predictor/** — experiment log, per-run notes
- **Kalshi/** — trading learnings, rules reference, session notes
- **LTM/** — VJ profile, memory policy, dream-extracted knowledge
- **REF/** — verified sources, glossary
- **Templates/** — skeletons for new notes
- **Archive/** — superseded notes (never deleted)

## Sync
- Lives at `/data/workspace/predictor/mando-memory/` on the Railway volume.
- Pushed to GitHub (`vijaycinn/predictor`, folder `mando-memory/`) by `auto_sync.sh` every 120m.
- No new sync infra — rides the existing predictor repo cron.

## Mobile access
- Clone the predictor repo (`https://github.com/vijaycinn/predictor.git`).
- Open the `mando-memory/` folder as an Obsidian vault in the app.
- iOS: Working Copy (free pull; Pro for push). Android: Termux + git.
- SINGLE WRITER RULE: server is source of truth. Mobile = pull-then-push. Never edit the same note on two devices at once.

## Writing rules
- One concept per note. Lowercase-kebab filenames. Frontmatter on every note.
- Wikilinks `[[Note Name]]` for cross-refs.
- Update `index.md` when creating notes.
- Never store secrets in this vault.

## Dream
Weekly (Wed 2pm CT) dream run extracts durable facts from past sessions into `LTM/extracted/` and auto-applies low-risk memory-tool edits. See skill `dream`.
