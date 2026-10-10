#!/usr/bin/env bash
# Create a checkpoint from the CURRENT Hermes session, on demand.
#
# Why this exists: `entire session attach` needs a session id, and the long
# build session's id predates the hackathon window (it started 2026-10-09
# 19:18 UTC; the window opened 2026-10-10 07:00 UTC). Every COMMIT is inside
# the window, but the session that produced the checkpoint is not, and that
# distinction should never have to be argued about.
#
# Usage:  scripts/entire_checkpoint.sh [commit-message]
# Prints: the checkpoint id, ready to paste as an `Entire-Checkpoint:` trailer.
set -uo pipefail

export PATH="$HOME/.local/bin:$PATH"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1

MSG="${1:-Session checkpoint}"

if ! command -v entire >/dev/null 2>&1; then
  echo "entire CLI not on PATH" >&2
  exit 1
fi
if ! command -v entire-agent-hermes >/dev/null 2>&1; then
  echo "entire-agent-hermes not on PATH — cp tools/entire-agent-hermes ~/.local/bin/" >&2
  exit 1
fi

# The most recently updated Hermes session is the one being worked in.
SID="$(entire-agent-hermes _latest 2>/dev/null || true)"
if [ -z "$SID" ]; then
  SID="$(.venv/bin/python - <<'PY'
import sqlite3
c = sqlite3.connect("file:/home/ubuntu/.hermes/state.db?mode=ro", uri=True)
r = c.execute("SELECT id FROM sessions ORDER BY COALESCE(last_activity_at, started_at) DESC LIMIT 1").fetchone()
print(r[0] if r else "")
PY
)"
fi

if [ -z "$SID" ]; then
  echo "no Hermes session found" >&2
  exit 1
fi

OUT="$(entire session attach "$SID" --agent hermes 2>&1)"
CP="$(printf '%s\n' "$OUT" | grep -oE '[A-Z0-9]{26}' | head -1)"

if [ -z "$CP" ]; then
  echo "$OUT" >&2
  echo "could not create a checkpoint" >&2
  exit 1
fi

git commit -q --allow-empty -m "$MSG

Entire-Checkpoint: $CP"

echo "session:    $SID"
echo "checkpoint: $CP"
echo "url:        https://entire.io/gh/cipoklean/medic/commit/$(git rev-parse HEAD)"
echo "started:    $(date -u '+%Y-%m-%d %H:%M:%S UTC') (window opened 2026-10-10 07:00 UTC)"