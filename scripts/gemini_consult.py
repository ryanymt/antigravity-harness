"""Consult a Gemini model on Vertex AI — the harness's one-shot / external-validator tier.

Why this exists: Claude Code orchestrators and sub-agents can shell out to an
INDEPENDENT model family (Google Gemini) for (a) cheap one-shot tasks
(summaries, lookups, web search via grounding) and (b) adversarial review with
no shared blind spots (the "External Validator" persona). A different model
family is a structurally different lens; in practice it catches defects the
resident models agree on.

Config (env):
  GEMINI_VERTEX_PROJECT   GCP project with Vertex AI enabled (required)
  GEMINI_DEFAULT_MODEL    default model id (default: gemini-3.5-flash)

Usage:
  python scripts/gemini_consult.py "prompt text"
  python scripts/gemini_consult.py --model gemini-3.1-pro-preview \
      --system "You are a skeptical reviewer." \
      --file design.md --file src/core.py \
      --max-tokens 16384 "Review the attached for flaws."
  python scripts/gemini_consult.py --search "current SOFR rate"   # web search
  echo "long prompt" | python scripts/gemini_consult.py -

Notes:
  - Auth: gcloud ADC (`gcloud auth print-access-token`).
  - Thinking models spend output budget on reasoning: use --max-tokens >= 16384
    for substantive reviews or the answer gets truncated.
  - Output: model text to stdout; non-zero exit on failure.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

PROJECT = os.environ.get("GEMINI_VERTEX_PROJECT", "")
ENDPOINT = ("https://aiplatform.googleapis.com/v1/projects/{project}/"
            "locations/global/publishers/google/models/{model}:generateContent")
DEFAULT_MODEL = os.environ.get("GEMINI_DEFAULT_MODEL", "gemini-3.5-flash")
RETRIES = 3


def get_token() -> str:
    return subprocess.run(["gcloud", "auth", "print-access-token"],
                          capture_output=True, text=True, check=True).stdout.strip()


def build_payload(prompt: str, system: str | None, files: list[str],
                  max_tokens: int, temperature: float, search: bool = False) -> dict:
    parts = []
    for path in files:
        with open(path, "r", errors="replace") as fh:
            parts.append({"text": f"===== FILE: {path} =====\n{fh.read()}\n===== END FILE =====\n"})
    parts.append({"text": prompt})
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temperature},
    }
    if search:
        # Google Search grounding — the web-search path when the Claude side
        # runs on Vertex (Anthropic server-side web_search is unavailable there).
        payload["tools"] = [{"googleSearch": {}}]
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    return payload


def call(model: str, payload: dict) -> str:
    if not PROJECT:
        raise SystemExit("set GEMINI_VERTEX_PROJECT to a GCP project with Vertex AI enabled")
    url = ENDPOINT.format(project=PROJECT, model=model)
    data = json.dumps(payload).encode()
    last_err = None
    for attempt in range(RETRIES):
        req = urllib.request.Request(url, data=data, method="POST", headers={
            "Authorization": f"Bearer {get_token()}",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                body = json.load(resp)
            texts = []
            for cand in body.get("candidates", []):
                for part in cand.get("content", {}).get("parts", []):
                    if "text" in part:
                        texts.append(part["text"])
            if not texts:
                raise RuntimeError(f"no text in response: {json.dumps(body)[:500]}")
            return "".join(texts)
        except urllib.error.HTTPError as exc:  # retry on transient codes
            last_err = f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:500]}"
            if exc.code not in (429, 500, 502, 503, 504):
                break
        except Exception as exc:  # noqa: BLE001 - report and retry
            last_err = str(exc)
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Gemini call failed after {RETRIES} attempts: {last_err}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Consult Gemini on Vertex AI.")
    ap.add_argument("prompt", help="prompt text, or '-' to read stdin")
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help=f"model id (default: {DEFAULT_MODEL})")
    ap.add_argument("--system", default=None, help="system instruction")
    ap.add_argument("--file", action="append", default=[],
                    help="attach a file's contents (repeatable)")
    ap.add_argument("--max-tokens", type=int, default=8192)
    ap.add_argument("--temperature", type=float, default=0.3)
    ap.add_argument("--search", action="store_true",
                    help="enable Google Search grounding (web search)")
    args = ap.parse_args()

    prompt = sys.stdin.read() if args.prompt == "-" else args.prompt
    print(call(args.model, build_payload(prompt, args.system, args.file,
                                         args.max_tokens, args.temperature, args.search)))


if __name__ == "__main__":
    main()
