# CLAUDE.md

Read **`AGENT.md`** first — it is the cold-start handoff for this project
(current status, architecture, next steps, decisions, gotchas, activity log).

This file exists because Claude Code auto-reads it. The entire-graph guide lives in
`AGENTS.md`; do not confuse the two.

- Never edit Python to "fix the agent". Medic patches `medic.yaml` only.
- Deterministic runs: temperature=0, fixtures only, no network in demo mode.
- Every reported number must be measured, never estimated.