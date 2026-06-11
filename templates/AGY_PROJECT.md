# <PROJECT NAME> — Antigravity Project Guide
<!-- Drop-in AGY_PROJECT.md template for the Antigravity agentic harness.
     Replace <angle-bracket> placeholders; delete sections you don't use. -->

## Model tiers (tokenomics policy — binding)

| Tier | Model | Used for | How |
|---|---|---|---|
| Orchestrator ("main brain") | Claude Fable 5 | Decision-making, synthesis, prompt-writing, reconciliation. ONE session. | main `agy` session |
| Reasoning sub-agents | Claude Opus 4.8 | Multi-step work owned by a persona: implementation, analysis, spec-writing | `invoke_subagent` tool |
| One-shot / validator | Gemini 3.1 Pro | Adversarial review of specs/diffs/designs (independent model family) | `python scripts/gemini_consult.py` |

Rules:
- The orchestrator NEVER does bulk implementation or bulk reading itself — it creates subagents and dispatches personas.
- Every major artifact (spec, diff, study design) gets an External Validator (Gemini) review BEFORE it ships.

## Cost control (binding)

- Session budget: $<N>. Ledger: `python scripts/cost_tracker.py status` (exit 2 = budget hit → STOP and report).
- The orchestrator logs every sub-agent's reported token total and every Gemini call when they return.
- True-up from provider metering when available: `python scripts/vertex_meter.py --hours 6` (cache-aware).

## Dispatch protocol (how work happens)

1. Orchestrator uses `define_subagent` to create personas (e.g. Architect, Engineer).
2. Orchestrator uses `invoke_subagent` to spawn instances of these personas. **CRITICAL:** Use `Workspace: "share"` when launching parallel subagents that will modify code, so they work in isolated worktrees.
3. Subagents receive tasks via `send_message` from the Orchestrator.
4. Orchestrator reconciles results, reviews the diffs from the subagents' workspaces, and merges them.

## Hard rules for all agents

- Log every decision (with rationale) and every execution step.
- An honest negative result is a success condition. Never present in-sample/unverified results as findings.
- Flag blockers instead of guessing across domain boundaries.
