#!/usr/bin/env bash
# Medic, the live heal, from a fresh terminal.
#
#   bash run.sh reset    # restore the buggy parse_error config
#   bash run.sh before   # the failing run (frame 1)
#   bash run.sh heal     # the full heal (frames 2-6)
#
# Nothing is written to medic.yaml: the patch is applied to a COPY and only
# reaches medic.yaml with --apply. So a bad take cannot corrupt the config, and
# `bash run.sh reset` always returns you to the same starting state.
set -euo pipefail
cd "$(dirname "$0")"

# .env wins over anything already exported in your shell. Without this, a stale
# LLM_MODEL in your environment silently overrides the file.
set -a && . ./.env && set +a

# Patient: nova-micro on Bedrock. Medic: claude-sonnet-4.6 (the role default).
# This one variable is the only thing separating them; without it both roles
# resolve to the same model and the heal is attributed to the wrong one.
export LLM_MODEL_LITELLM_PATIENT=nova-micro

PY=.venv/bin/python
[ -x "$PY" ] || { echo "no venv, run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"; exit 1; }

cmd="${1:-help}"
case "$cmd" in
  reset)
    echo "→ restoring the buggy parse_error config"
    "$PY" cli.py reset
    ;;
  before)
    echo "→ patient run on the buggy config (expect FAIL)"
    "$PY" cli.py run --bug parse_error --llm real
    ;;
  heal)
    echo "→ diagnose → diff → rerun → held-out → verdict"
    echo "  patient: nova-micro (Bedrock)   medic: claude-sonnet-4.6 (Bedrock)"
    echo
    "$PY" cli.py heal --bug parse_error --llm real
    ;;
  check)
    # Free, offline. Confirms the roles resolved correctly BEFORE you spend tokens.
    "$PY" -c "
from patient.config import load_env; load_env()
from medic import providers as p
print('patient →', p.chain(role='patient')[0].label())
print('medic   →', p.chain(role='medic')[0].label())
"
    ;;
  *)
    echo "usage: bash run.sh {reset|before|heal|check}"
    ;;
esac
