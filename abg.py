#!/usr/bin/env python3
"""
agent-bill-guard (abg) — hard budget limits for AI coding agent sessions.
A local HTTP proxy that intercepts Anthropic/OpenAI requests and enforces
per-session and daily spend caps.

Usage:
    python abg.py proxy                    # Start proxy (default port 8788)
    python abg.py proxy --port 9000        # Custom port
    python abg.py status                   # Show current spend
    python abg.py reset --session <id>     # Reset session spend
"""
import argparse
import json
import os
import sys
import time
import threading
import urllib.request
import urllib.error
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# ── Model pricing ($ per 1M tokens) ──────────────────────────────────────────
PRICES = {
    "claude-opus-4-6":     {"input": 15.0,  "output": 75.0},
    "claude-sonnet-4-6":   {"input": 3.0,   "output": 15.0},
    "claude-haiku-4-5":    {"input": 0.8,   "output": 4.0},
    "claude-3-5-sonnet":   {"input": 3.0,   "output": 15.0},
    "claude-3-opus":       {"input": 15.0,  "output": 75.0},
    "gpt-4o":              {"input": 2.5,   "output": 10.0},
    "gpt-4o-mini":         {"input": 0.15,  "output": 0.6},
    "o1":                  {"input": 15.0,  "output": 60.0},
    "o3-mini":             {"input": 1.1,   "output": 4.4},
}
DEFAULT_PRICE = {"input": 3.0, "output": 15.0}  # fallback

# ── Config loading ────────────────────────────────────────────────────────────
def load_config(path="agentbillguard.yaml"):
    cfg = {
        "session_budget_usd": 5.0,
        "daily_budget_usd": 20.0,
        "warn_at": 0.8,           # warn at 80% of budget
        "block_on_limit": True,
        "upstream_anthropic": "https://api.anthropic.com",
        "upstream_openai":    "https://api.openai.com",
        "ledger_file":        "ledger.jsonl",
        "port": 8788,
    }
    if os.path.exists(path):
        try:
            import yaml
            with open(path) as f:
                cfg.update(yaml.safe_load(f) or {})
        except ImportError:
            # fallback: simple key: value parser (no yaml dep required)
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and ":" in line:
                        k, _, v = line.partition(":")
                        v = v.strip()
                        try:
                            cfg[k.strip()] = float(v) if "." in v else int(v) if v.isdigit() else (True if v == "true" else False if v == "false" else v)
                        except ValueError:
                            cfg[k.strip()] = v
    return cfg

# ── Ledger ────────────────────────────────────────────────────────────────────
class Ledger:
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self._session_spend = {}
        self._daily_spend = {}
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return
        today = str(date.today())
        with open(self.path) as f:
            for line in f:
                try:
                    e = json.loads(line)
                    sid = e.get("session_id", "default")
                    cost = e.get("cost_usd", 0)
                    self._session_spend[sid] = self._session_spend.get(sid, 0) + cost
                    if e.get("date") == today:
                        self._daily_spend[today] = self._daily_spend.get(today, 0) + cost
                except Exception:
                    pass

    def record(self, session_id, model, input_tokens, output_tokens, cost_usd, action):
        today = str(date.today())
        entry = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "date": today,
            "session_id": session_id,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost_usd, 6),
            "session_total_usd": round(self._session_spend.get(session_id, 0) + cost_usd, 6),
            "action": action,
        }
        with self._lock:
            self._session_spend[session_id] = self._session_spend.get(session_id, 0) + cost_usd
            self._daily_spend[today] = self._daily_spend.get(today, 0) + cost_usd
            with open(self.path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        return entry

    def session_total(self, session_id):
        return self._session_spend.get(session_id, 0)

    def daily_total(self):
        return self._daily_spend.get(str(date.today()), 0)

    def reset_session(self, session_id):
        with self._lock:
            self._session_spend[session_id] = 0

    def status(self):
        today = str(date.today())
        return {
            "sessions": dict(self._session_spend),
            "today_total_usd": round(self._daily_spend.get(today, 0), 6),
        }

# ── Cost estimation ───────────────────────────────────────────────────────────
def estimate_cost(model, input_tokens, output_tokens):
    prices = PRICES.get(model)
    if not prices:
        for k in PRICES:
            if k in model:
                prices = PRICES[k]
                break
        else:
            prices = DEFAULT_PRICE
    return (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000

# ── Proxy handler ─────────────────────────────────────────────────────────────
def make_handler(cfg, ledger):
    class ProxyHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # suppress default request logs

        def _get_session_id(self):
            return self.headers.get("x-abg-session-id", "default")

        def _budget_check(self, session_id):
            s_total = ledger.session_total(session_id)
            d_total = ledger.daily_total()
            s_budget = cfg["session_budget_usd"]
            d_budget = cfg["daily_budget_usd"]
            warn_threshold = cfg["warn_at"]
            if cfg["block_on_limit"]:
                if s_total >= s_budget:
                    return "block", f"Session budget exhausted: ${s_total:.4f} >= ${s_budget:.2f}"
                if d_total >= d_budget:
                    return "block", f"Daily budget exhausted: ${d_total:.4f} >= ${d_budget:.2f}"
            if s_total >= s_budget * warn_threshold or d_total >= d_budget * warn_threshold:
                return "warn", f"Budget warning: session=${s_total:.4f}/{s_budget:.2f}, day=${d_total:.4f}/{d_budget:.2f}"
            return "allow", None

        def do_POST(self):
            session_id = self._get_session_id()
            action, reason = self._budget_check(session_id)
            if action == "block":
                self.send_response(429)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "error": {"type": "budget_exceeded", "message": reason}
                }).encode())
                print(f"[abg] BLOCKED session={session_id} | {reason}", flush=True)
                return

            # Forward request to upstream
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length else b""

            # Determine upstream URL
            if "anthropic" in self.path or "messages" in self.path:
                upstream = cfg["upstream_anthropic"] + self.path
            else:
                upstream = cfg["upstream_openai"] + self.path

            req_headers = {k: v for k, v in self.headers.items()
                           if k.lower() not in ("host", "x-abg-session-id", "content-length")}

            try:
                req = urllib.request.Request(upstream, data=body, headers=req_headers, method="POST")
                with urllib.request.urlopen(req, timeout=120) as resp:
                    resp_body = resp.read()
                    status = resp.status
                    resp_headers = list(resp.headers.items())
            except urllib.error.HTTPError as e:
                resp_body = e.read()
                status = e.code
                resp_headers = list(e.headers.items())
            except Exception as e:
                self.send_response(502)
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
                return

            # Extract token usage from response
            input_tokens = output_tokens = 0
            model = "unknown"
            try:
                resp_json = json.loads(resp_body)
                model = resp_json.get("model", "unknown")
                usage = resp_json.get("usage", {})
                input_tokens = usage.get("input_tokens", usage.get("prompt_tokens", 0))
                output_tokens = usage.get("output_tokens", usage.get("completion_tokens", 0))
            except Exception:
                pass

            cost = estimate_cost(model, input_tokens, output_tokens)
            entry = ledger.record(session_id, model, input_tokens, output_tokens, cost, action)

            if action == "warn":
                print(f"[abg] WARN  session={session_id} cost=${cost:.6f} session_total=${entry['session_total_usd']:.4f} | {reason}", flush=True)
            else:
                print(f"[abg] ALLOW session={session_id} model={model} cost=${cost:.6f} session_total=${entry['session_total_usd']:.4f}", flush=True)

            # Forward response back
            self.send_response(status)
            skip_headers = {"transfer-encoding", "connection", "content-length"}
            for k, v in resp_headers:
                if k.lower() not in skip_headers:
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(resp_body)))
            self.end_headers()
            self.wfile.write(resp_body)

        def do_GET(self):
            if self.path == "/abg/status":
                status = ledger.status()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(status, indent=2).encode())
            else:
                self.send_response(404)
                self.end_headers()

    return ProxyHandler

# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="agent-bill-guard: hard budget limits for AI coding agent sessions")
    sub = parser.add_subparsers(dest="cmd")

    p_proxy = sub.add_parser("proxy", help="Start the budget-enforcement proxy")
    p_proxy.add_argument("--port", type=int, default=None)
    p_proxy.add_argument("--config", default="agentbillguard.yaml")

    p_status = sub.add_parser("status", help="Show current spend totals")
    p_status.add_argument("--config", default="agentbillguard.yaml")

    p_reset = sub.add_parser("reset", help="Reset a session's spend counter")
    p_reset.add_argument("--session", required=True)
    p_reset.add_argument("--config", default="agentbillguard.yaml")

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(1)

    cfg = load_config(args.config)
    if hasattr(args, "port") and args.port:
        cfg["port"] = args.port

    ledger = Ledger(cfg["ledger_file"])

    if args.cmd == "proxy":
        port = cfg["port"]
        handler = make_handler(cfg, ledger)
        server = HTTPServer(("127.0.0.1", port), handler)
        print(f"[abg] agent-bill-guard proxy listening on http://127.0.0.1:{port}", flush=True)
        print(f"[abg] session budget: ${cfg['session_budget_usd']:.2f}  daily budget: ${cfg['daily_budget_usd']:.2f}", flush=True)
        print(f"[abg] ledger: {cfg['ledger_file']}", flush=True)
        print(f"[abg] status: http://127.0.0.1:{port}/abg/status", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\n[abg] Stopped.", flush=True)

    elif args.cmd == "status":
        status = ledger.status()
        print(json.dumps(status, indent=2))

    elif args.cmd == "reset":
        ledger.reset_session(args.session)
        print(f"[abg] Reset session '{args.session}'")

if __name__ == "__main__":
    main()
