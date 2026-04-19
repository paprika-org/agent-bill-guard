# agent-bill-guard

**Hard budget limits for AI coding agent sessions.**

A lightweight local proxy that sits in front of Claude Code, Codex CLI, and other AI coding agents. When a session hits your spend cap, the next request is blocked — not warned about after the fact.

```
[Claude Code] → [agent-bill-guard :8788] → [Anthropic API]
                      ↓
               blocks at $5.00/session
               warns at $4.00
               writes ledger.jsonl
```

No gateway setup. No vendor account. No dashboard. Just a Python script you run locally.

---

## The problem

Workspace spend limits on Claude.ai and the Anthropic console apply monthly, at the org level. They don't stop one developer from burning $40 in a runaway session before anyone notices. They don't give you per-session attribution. They don't let you set different caps for different agents.

`agent-bill-guard` fills that gap: **per-session circuit breaker, local, zero infrastructure**.

---

## Quick start

```bash
# Clone
git clone https://github.com/paprika-org/agent-bill-guard
cd agent-bill-guard

# Copy config
cp agentbillguard.yaml.example agentbillguard.yaml
# Edit: set session_budget_usd and daily_budget_usd

# Start proxy
python abg.py proxy
# [abg] agent-bill-guard proxy listening on http://127.0.0.1:8788
# [abg] session budget: $5.00  daily budget: $20.00
```

Point Claude Code at the proxy:

```bash
# In a new terminal, set Claude Code to route through proxy
ANTHROPIC_BASE_URL=http://127.0.0.1:8788 claude

# Or for Codex CLI
OPENAI_BASE_URL=http://127.0.0.1:8788 codex
```

Tag sessions to get per-session attribution:

```bash
# Export session ID for this coding session
export ABG_SESSION_ID=feature-auth-rewrite

# Pass it through to the proxy
ANTHROPIC_BASE_URL=http://127.0.0.1:8788 \
  ABG_SESSION_ID=$ABG_SESSION_ID \
  claude
```

> **Note:** Set `x-abg-session-id` header in your wrapper, or use a shell alias — see [docs/claude-code.md](docs/claude-code.md).

---

## What happens when you hit the cap

```
[abg] ALLOW session=feature-auth-rewrite model=claude-sonnet-4-6 cost=$0.008421 session_total=$4.12
[abg] WARN  session=feature-auth-rewrite cost=$0.006200 session_total=$4.73 | Budget warning: session=$4.73/5.00
[abg] BLOCKED session=feature-auth-rewrite | Session budget exhausted: $5.14 >= $5.00
```

The blocked request returns HTTP 429:

```json
{
  "error": {
    "type": "budget_exceeded",
    "message": "Session budget exhausted: $5.14 >= $5.00"
  }
}
```

---

## The ledger

Every request is logged to `ledger.jsonl`:

```jsonl
{"ts":"2026-04-19T14:22:01Z","date":"2026-04-19","session_id":"feature-auth-rewrite","model":"claude-sonnet-4-6","input_tokens":4821,"output_tokens":312,"cost_usd":0.019125,"session_total_usd":4.12,"action":"allow"}
{"ts":"2026-04-19T14:24:18Z","date":"2026-04-19","session_id":"feature-auth-rewrite","model":"claude-sonnet-4-6","input_tokens":6102,"output_tokens":289,"cost_usd":0.022635,"session_total_usd":4.73,"action":"warn"}
```

Run `python abg.py status` to see current totals.

---

## Configuration

```yaml
# agentbillguard.yaml
session_budget_usd: 5.0   # cap per coding session
daily_budget_usd: 20.0    # cap across all sessions per day
warn_at: 0.8              # warn at 80% of budget
block_on_limit: true      # false = warn-only mode
port: 8788
ledger_file: ledger.jsonl
```

---

## Comparison

| Feature | agent-bill-guard | LiteLLM | Portkey | Provider console |
|---------|-----------------|---------|---------|-----------------|
| Per-session hard cap | ✅ | ❌ (per-key/user) | ❌ (per-key/user) | ❌ (monthly) |
| Local, zero infra | ✅ | ❌ requires server | ❌ requires server | N/A |
| Per-request JSONL log | ✅ | ❌ dashboard | ❌ dashboard | ❌ |
| Setup time | ~2 min | ~30 min | ~30 min | immediate |
| Cost | free | free/paid | free/paid | included |
| Multi-model routing | ❌ | ✅ | ✅ | ❌ |
| Team auth / virtual keys | ❌ | ✅ | ✅ | ✅ |

**Use LiteLLM or Portkey** if you need org-wide routing, virtual keys, or a shared team proxy.  
**Use agent-bill-guard** if you need a per-session kill switch you can run locally in under 2 minutes.

---

## Status endpoint

While the proxy is running:

```bash
curl http://127.0.0.1:8788/abg/status
# {
#   "sessions": {
#     "feature-auth-rewrite": 4.73,
#     "bugfix-login": 1.22
#   },
#   "today_total_usd": 5.95
# }
```

---

## Supported models (pricing built-in)

- Claude: Opus 4.6, Sonnet 4.6, Haiku 4.5, Claude 3.5 Sonnet, Claude 3 Opus
- OpenAI: GPT-4o, GPT-4o-mini, o1, o3-mini
- Unknown models fall back to Sonnet-3.5 pricing ($3/$15 per 1M tokens)

---

## Requirements

- Python 3.8+
- No external dependencies (stdlib only)

---

## Roadmap

- [ ] Per-tool/MCP-call budget tracking (via wrapper hooks)
- [ ] `abg run --session <id> -- <command>` wrapper
- [ ] Session persistence across restarts
- [ ] Config reload without proxy restart

---

## Contributing

Issues and PRs welcome. This is early/experimental — if you try it and hit a problem, please open an issue.

---

## Why does this exist?

I was running Claude Code on a feature branch and a context-window loop burned $12 before I noticed. Workspace spending limits don't help with that. I wanted a simple local kill switch, not a full LLM gateway deployment.

`agent-bill-guard` is that kill switch.

---

*Built by [paprika-org](https://github.com/paprika-org). MIT license.*
