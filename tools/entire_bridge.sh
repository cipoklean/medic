#!/usr/bin/env bash
# Entire lifecycle bridge for Hermes.
#
# Hermes shell hooks receive a JSON payload on stdin and must not print anything
# that is not valid JSON on stdout. Each event translates to one Entire CLI
# hook invocation; Entire's own git hooks then turn the result into a
# checkpoint tied to this session.
#
# Event mapping (Hermes -> Entire):
#   on_session_start -> (nothing; Entire learns the session from the prompt)
#   pre_llm_call     -> session-start  (Hermes has no separate UserPromptSubmit;
#                       pre_llm_call fires at exactly the same point)
#   post_tool_call   -> turn-start     (a checkpoint is cut per turn)
#   post_llm_call    -> turn-end
#   on_session_end   -> session-end
set -uo pipefail

HERMES_DIR="${HERMES_HOME:-$HOME/.hermes}"
EVENT="${1:-unknown}"
PAYLOAD="$(cat)"

entire_bin="$(command -v entire || true)"
[ -n "$entire_bin" ] || exit 0

log() { "$HERMES_DIR/entire-bridge.log" 2>/dev/null; printf '%s %s\n' "$(date -Is)" "$*" >> "$HERMES_DIR/entire-bridge.log" 2>/dev/null || true; }

session_id() {
  printf '%s' "$PAYLOAD" \
    | tr ',' '\n' \
    | grep -oE '"session[_a-z]*"[[:space:]]*:[[:space:]]*"[^"]+"' \
    | head -1 \
    | sed -E 's/.*"session[_a-z]*"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/'
}

SID="$(session_id)"
[ -n "$SID" ] || { log "no session_id for $EVENT; skipping"; exit 0; }

case "$EVENT" in
  pre_llm_call)          HOOK="session-start" ;;
  post_tool_call)         HOOK="turn-start" ;;
  post_llm_call)          HOOK="turn-end" ;;
  on_session_end)         HOOK="session-end" ;;
  *)                      log "unmapped event $EVENT"; exit 0 ;;
esac

log "event=$EVENT hook=$HOOK session=$SID"

# Entire tolerates a non-zero exit here, but a silent success would hide a
# broken bridge, so the outcome is recorded either way.
if "$entire_bin" hooks --agent hermes "$HOOK" --payload "$PAYLOAD" >/dev/null 2>&1; then
  log "ok $HOOK"
  printf '{}\n'
  exit 0
fi

# Fall back to the documented stdin form if the flag form is unsupported.
if printf '%s' "$PAYLOAD" | "$entire_bin" hooks --agent hermes "$HOOK" >/dev/null 2>&1; then
  log "ok-stdin $HOOK"
  printf '{}\n'
  exit 0
fi

log "FAIL $HOOK (entire returned non-zero)"
printf '{}\n'
exit 0