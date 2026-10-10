
# entire-agent-hermes

Adapter for Entire (protocol v1). Install:

    cp tools/entire-agent-hermes ~/.local/bin/ && chmod +x ~/.local/bin/entire-agent-hermes
    echo '{"external_agents": true}' > .entire/settings.local.json
    entire enable --agent hermes

Hermes sessions live in ~/.hermes/state.db. The DB is opened read-only.

## Verified

- `entire enable --agent hermes` → registers and enables the agent.
- `entire session attach <hermes-session-id> --agent hermes` → creates a checkpoint
  from the real transcript (verified: session 20261009_191831_9554f70b, 5 turns).
- `entire checkpoint list` → the checkpoint, tied to commit `9eb288b`.
- `entire checkpoint explain <id>` → agent `Hermes`, real session id, real intent.

## Known gap

`entire checkpoint tokens` reports "Token data: unavailable" for Hermes
checkpoints, although `entire-agent-hermes calculate-tokens` returns correct
counts when invoked directly (405,676 input / 109,128 output / 248 API calls).
Entire does not appear to call the `token_calculator` capability during
`session attach`, so the field stays empty. Declared `true` because the
subcommand genuinely works, but the end-to-end number is not yet flowing.
