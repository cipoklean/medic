
# entire-agent-hermes

Adapter for Entire (protocol v1). Install:

    cp tools/entire-agent-hermes ~/.local/bin/ && chmod +x ~/.local/bin/entire-agent-hermes
    echo  > .entire/settings.local.json   # {"external_agents": true}
    entire enable --agent hermes

Hermes sessions live in ~/.hermes/state.db. The DB is opened read-only.
