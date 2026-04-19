#!/bin/bash
# Demo: show what agent-bill-guard does when a session hits its cap
# Requires: python3, curl

set -e

echo "Starting agent-bill-guard with $2 session budget..."
python ../abg.py proxy --config demo-config.yaml &
PROXY_PID=$!
sleep 0.5

echo ""
echo "Making requests... (proxy will block when session hits \$2)"
echo ""

# Simulate 3 requests with a very low session budget
for i in 1 2 3; do
  echo "Request $i:"
  curl -s -X POST http://127.0.0.1:8788/v1/messages \
    -H "Content-Type: application/json" \
    -H "x-api-key: test" \
    -H "x-abg-session-id: demo-session" \
    -d '{"model":"claude-sonnet-4-6","messages":[{"role":"user","content":"hello"}],"max_tokens":10}' \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print('  -> blocked:', d['error']['message'] if 'error' in d else 'allowed')"
  echo ""
done

kill $PROXY_PID 2>/dev/null || true
echo "Done. Check ledger.jsonl for the spend log."
