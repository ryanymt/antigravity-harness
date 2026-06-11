"""Pull authoritative token counts from Vertex AI monitoring — ledger true-up.

The cost ledger's weak spot is the orchestrator's own turns (not observable
mid-session). Vertex AI meters every request server-side; this script reads
`aiplatform.googleapis.com/publisher/online_serving/token_count` per model and
token type, prices it CACHE-AWARE, and prints both raw counts and a cost
summary you can write back into the ledger as a "METERED" true-up entry.

Cache-aware pricing (Anthropic): cache reads bill at 0.10x the input rate and
cache writes at 1.25x. On agentic workloads cache reads dominate (often >90%
of input tokens), so naive input-rate pricing overstates cost by 5-10x.

Config (env):
  VERTEX_METER_PROJECT   GCP project to read metrics from (required)

Usage:
  python scripts/vertex_meter.py --since 2026-06-11T10:00:00Z
  python scripts/vertex_meter.py --hours 6
"""

import argparse
import collections
import datetime
import json
import os
import subprocess
import urllib.parse
import urllib.request

PROJECT = os.environ.get("VERTEX_METER_PROJECT", "")

# USD per 1M tokens: (input, output). Cache multipliers applied to input rate.
RATES = {
    "claude-fable-5":    (10.0, 50.0),
    "claude-opus-4-8":   (5.0, 25.0),
    "claude-opus-4-7":   (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5":  (1.0, 5.0),
    "gemini-3.1-pro-preview": (2.0, 12.0),
    "gemini-3.5-flash":       (1.50, 9.0),
}
CACHE_READ_MULT = 0.10
CACHE_WRITE_MULT = 1.25


def token() -> str:
    return subprocess.run(["gcloud", "auth", "print-access-token"],
                          capture_output=True, text=True, check=True).stdout.strip()


def fetch(start: str, end: str) -> dict:
    params = urllib.parse.urlencode({
        "filter": 'metric.type="aiplatform.googleapis.com/publisher/online_serving/token_count"',
        "interval.startTime": start,
        "interval.endTime": end,
        "aggregation.alignmentPeriod": "86400s",
        "aggregation.perSeriesAligner": "ALIGN_SUM",
    })
    url = f"https://monitoring.googleapis.com/v3/projects/{PROJECT}/timeSeries?{params}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token()}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def main() -> None:
    if not PROJECT:
        raise SystemExit("set VERTEX_METER_PROJECT")
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--since", help="ISO start time, e.g. 2026-06-11T10:00:00Z")
    g.add_argument("--hours", type=float, help="lookback window in hours")
    args = ap.parse_args()

    end = datetime.datetime.now(datetime.timezone.utc)
    start = (args.since if args.since
             else (end - datetime.timedelta(hours=args.hours)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    d = fetch(start, end.strftime("%Y-%m-%dT%H:%M:%SZ"))
    if "error" in d:
        raise SystemExit(f"monitoring API error: {d['error'].get('message', '')[:300]}")

    agg = collections.defaultdict(int)
    for ts in d.get("timeSeries", []):
        labels = {**ts.get("resource", {}).get("labels", {}),
                  **ts.get("metric", {}).get("labels", {})}
        model = labels.get("model_user_id", "?")
        ttype = labels.get("type") or labels.get("token_type", "?")
        agg[(model, ttype)] += sum(int(p["value"].get("int64Value", 0))
                                   for p in ts.get("points", []))

    print(f"{'model':<26}{'type':<24}{'tokens':>14}")
    per_model_cost = collections.defaultdict(float)
    for (model, ttype), n in sorted(agg.items()):
        print(f"{model:<26}{ttype:<24}{n:>14,}")
        r = RATES.get(model)
        if not r:
            continue
        in_rate, out_rate = r
        t = ttype.lower()
        if "cache_read" in t:
            per_model_cost[model] += n / 1e6 * in_rate * CACHE_READ_MULT
        elif "cache_write" in t:
            per_model_cost[model] += n / 1e6 * in_rate * CACHE_WRITE_MULT
        elif "input" in t:
            per_model_cost[model] += n / 1e6 * in_rate
        elif "output" in t:
            per_model_cost[model] += n / 1e6 * out_rate

    print("-" * 64)
    total = 0.0
    for model, c in sorted(per_model_cost.items()):
        print(f"{model:<26}cache-aware cost ≈ ${c:,.2f}")
        total += c
    print(f"{'TOTAL':<26}≈ ${total:,.2f}  (since {start}; billing remains authoritative)")


if __name__ == "__main__":
    main()
