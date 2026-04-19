# How agent-bill-guard works

## Architecture

```
Your AI coding agent (Claude Code, Codex, etc.)
         |
         | HTTP requests to Anthropic/OpenAI API
         v
agent-bill-guard proxy (localhost:8788)
         |
         | [budget check]
         | - read session spend from ledger
         | - if over cap: return 429, don't forward
         | - if under cap: forward request
         v
Anthropic API / OpenAI API
         |
         | response
         v
agent-bill-guard proxy
         |
         | [cost tracking]
         | - parse usage from response (input_tokens, output_tokens)
         | - estimate cost using model pricing table
         | - append to ledger.jsonl
         v
Your AI coding agent
```

## Cost estimation

Token counts come from the API response's `usage` field:
- Anthropic: `usage.input_tokens` + `usage.output_tokens`
- OpenAI: `usage.prompt_tokens` + `usage.completion_tokens`

Cost is calculated from a built-in pricing table (`PRICES` in `abg.py`). Unknown models fall back to Sonnet-3.5 rates.

## Ledger format

Each request appends one JSON line to `ledger.jsonl`:

```json
{
  "ts": "2026-04-19T14:22:01Z",
  "date": "2026-04-19",
  "session_id": "default",
  "model": "claude-sonnet-4-6",
  "input_tokens": 4821,
  "output_tokens": 312,
  "cost_usd": 0.019125,
  "session_total_usd": 4.12,
  "action": "allow"
}
```

Actions: `allow`, `warn`, `block`.

## Limitations

- **No streaming support yet.** Streaming responses don't include full token counts in the final chunk in all cases. The proxy works but cost estimation may be less accurate for streamed requests.
- **No session persistence across restarts.** Spend counters are in-memory, loaded from the ledger file at startup. If you restart the proxy mid-session, the ledger is replayed so spend is preserved.
- **Single-process.** The proxy handles requests sequentially (Python's GIL). Fine for local dev; not designed for team-shared deployment.
