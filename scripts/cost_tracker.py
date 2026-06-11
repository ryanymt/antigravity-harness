"""Session cost/token ledger — the harness's budget guardrail.

Tracks spend across the orchestrator session, every sub-agent, and every
Gemini call against a per-session budget. The orchestrator logs each
sub-agent's reported token total when it returns, and pauses work when the
ledger hits the budget.

Honesty model:
  - PRECISE: sub-agent token totals (the Agent tool reports them) and Gemini
    usage. Logged as they happen.
  - ESTIMATED: the orchestrator session's own turns (Claude Code does not
    expose them mid-session). Log conservative estimates, then true-up from
    provider metrics (see vertex_meter.py) or billing.
  - AUTHORITATIVE: your cloud bill. This ledger is a conservative running
    guardrail that errs toward pausing early, never a price quote.

Config (env):
  COST_LEDGER          ledger path (default: ./cost_ledger.json)
  SESSION_BUDGET_USD   default budget for `reset` (default: 200)

Usage:
  python scripts/cost_tracker.py reset --budget 200
  python scripts/cost_tracker.py add --model claude-opus-4-8 --in 120000 --out 30000 --label "researcher subagent"
  python scripts/cost_tracker.py add --model claude-opus-4-8 --total 89238 --label "subagent (total -> output-priced, conservative)"
  python scripts/cost_tracker.py add --model gemini-3.1-pro-preview --in 8000 --out 1200 --label "red-team"
  python scripts/cost_tracker.py status

Exit code 2 when cumulative spend >= budget, so shell loops and CI can detect
the pause point:  python scripts/cost_tracker.py status || echo "BUDGET HIT"

Cache-aware true-up trick (Anthropic pricing): effective_input =
input + 1.25 * cache_write + 0.10 * cache_read, logged via --in at the input
rate. Ignoring cache pricing overstates real cost by 5-10x on agentic loads.

EDIT THE PRICING TABLE for your models/contract — rates drift.
"""

import argparse
import datetime
import json
import os
import sys

LEDGER = os.path.abspath(os.environ.get("COST_LEDGER", "cost_ledger.json"))

# (input_rate, output_rate) USD per 1M tokens. Verify against current price lists.
PRICING = {
    # Anthropic (list price; Vertex global endpoint has no premium)
    "claude-fable-5":    (10.0, 50.0),
    "claude-opus-4-8":   (5.0, 25.0),
    "claude-opus-4-7":   (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5":  (1.0, 5.0),
    # Google (verify on your contract/tier; <=200k-context tier shown)
    "gemini-3.1-pro-preview": (2.0, 12.0),
    "gemini-3.5-flash":       (1.50, 9.0),
}
# Models whose rates you haven't verified get a ~ marker in the table.
ESTIMATED_MODELS = {"gemini-3.1-pro-preview", "gemini-3.5-flash"}
DEFAULT_BUDGET = float(os.environ.get("SESSION_BUDGET_USD", "200"))


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def load():
    if not os.path.exists(LEDGER):
        return {"budget_usd": DEFAULT_BUDGET, "created": _now(), "entries": []}
    with open(LEDGER) as fh:
        return json.load(fh)


def save(d):
    os.makedirs(os.path.dirname(LEDGER) or ".", exist_ok=True)
    with open(LEDGER, "w") as fh:
        json.dump(d, fh, indent=2)


def cost_of(model, in_tok, out_tok):
    if model not in PRICING:
        raise SystemExit(f"unknown model '{model}'. Known: {', '.join(sorted(PRICING))}")
    ir, orate = PRICING[model]
    return in_tok / 1e6 * ir + out_tok / 1e6 * orate


def total(d):
    return sum(e["cost_usd"] for e in d["entries"])


def status(d):
    spent = total(d)
    budget = d["budget_usd"]
    print(f"=== Session cost ledger ({LEDGER}) ===")
    print(f"Budget: ${budget:.2f}   Spent: ${spent:.2f}   Remaining: ${budget - spent:.2f}   ({spent/budget*100:.1f}%)")
    if d["entries"]:
        print("-" * 72)
        for e in d["entries"]:
            mark = "~" if e["model"] in ESTIMATED_MODELS else " "
            print(f"  {e['ts'][11:19]} {mark}{e['model']:<24} "
                  f"in={e['in']:>8} out={e['out']:>8}  ${e['cost_usd']:>7.3f}  {e['label']}")
    print("-" * 72)
    if spent >= budget:
        print(f"*** BUDGET REACHED ({spent:.2f} >= {budget:.2f}) — PAUSE ***")
    elif spent >= 0.8 * budget:
        print(f"*** WARNING: {spent/budget*100:.0f}% of budget used ***")
    return spent, budget


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add")
    a.add_argument("--model", required=True)
    a.add_argument("--in", dest="in_tok", type=int, default=0)
    a.add_argument("--out", dest="out_tok", type=int, default=0)
    a.add_argument("--total", type=int, default=0,
                   help="when only a total is known (e.g. a subagent's token count): "
                        "priced at the OUTPUT rate (conservative overestimate)")
    a.add_argument("--label", default="")

    sub.add_parser("status")

    r = sub.add_parser("reset")
    r.add_argument("--budget", type=float, default=DEFAULT_BUDGET)

    args = ap.parse_args()

    if args.cmd == "reset":
        save({"budget_usd": args.budget, "created": _now(), "entries": []})
        print(f"Ledger reset. Budget ${args.budget:.2f}")
        return

    d = load()

    if args.cmd == "status":
        spent, budget = status(d)
        sys.exit(2 if spent >= budget else 0)

    if args.cmd == "add":
        in_tok, out_tok = args.in_tok, args.out_tok
        if args.total:
            out_tok += args.total  # conservative: price unknown-split totals at output rate
        c = cost_of(args.model, in_tok, out_tok)
        d["entries"].append({
            "ts": _now(), "model": args.model, "in": in_tok, "out": out_tok,
            "cost_usd": round(c, 4), "label": args.label,
        })
        save(d)
        spent, budget = status(d)
        sys.exit(2 if spent >= budget else 0)


if __name__ == "__main__":
    main()
