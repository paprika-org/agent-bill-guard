# Using agent-bill-guard with Claude Code

## Basic setup

1. Start the proxy in one terminal:
```bash
python abg.py proxy
```

2. In another terminal, set `ANTHROPIC_BASE_URL` and start Claude Code:
```bash
ANTHROPIC_BASE_URL=http://127.0.0.1:8788 claude
```

## Session tagging

To get per-session spend attribution, pass the session ID via the `x-abg-session-id` header. The cleanest way is a shell wrapper:

```bash
# ~/.local/bin/claude-session (make executable)
#!/bin/bash
SESSION_ID="${1:-$(date +%Y%m%d-%H%M%S)}"
shift
exec env \
  ANTHROPIC_BASE_URL=http://127.0.0.1:8788 \
  claude "$@"
# Note: header injection requires a wrapper that modifies requests
# or set ABG_SESSION_ID and configure abg to pick it up (roadmap)
```

For now, the simplest approach is to run one proxy instance per session, each with its own config:

```bash
# Session 1: $5 budget
python abg.py proxy --port 8788 --config session1.yaml

# Session 2: $10 budget  
python abg.py proxy --port 8789 --config session2.yaml
```

## Warn-only mode

To see spend without blocking, set `block_on_limit: false` in `agentbillguard.yaml`. You'll see warnings in the proxy log but requests will still go through.

## Checking spend

```bash
# While proxy is running
curl http://127.0.0.1:8788/abg/status

# From the ledger
python abg.py status
```
