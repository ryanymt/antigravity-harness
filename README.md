# Antigravity Agentic Harness — Multi-Model Orchestration for `agy`

A field-tested pattern for running **Antigravity (`agy` CLI)** as a multi-model, multi-persona agent system with a hard budget. It allows you to use the most capable model for thinking, mid-tier models for doing the work, and a *different vendor's* model to red-team everything, while a ledger stops the session before your bill surprises you.

This port adapts the Claude Agentic Harness to take advantage of **Antigravity 2.0's native features**, specifically:
*   Native asynchronous `invoke_subagent` and `define_subagent` (replacing rigid markdown persona files).
*   Native Git workspace branching (`Workspace: "share"`) to ensure disjoint write-sets for parallel subagents.
*   Running Claude natively via the Google Cloud Vertex AI API.

## The idea: match the model to the job

```
                       ┌─────────────────────────────────────────┐
 you (the owner) ←───→ │  ORCHESTRATOR — Claude Fable 5          │  one session
                       │  decides, defines subagents, dispatches │  "main brain"
                       │  work, reviews diffs. Doesn't bulk-work.│
                       └───────┬─────────────────┬───────────────┘
                               │ agy: invoke_subagent            │
              ┌────────────────┴───────┐   ┌─────┴──────────────────────┐
              │ PERSONA SUB-AGENTS     │   │ ONE-SHOT TIER (Gemini)     │
              │ Claude Opus 4.8        │   │ 3.1 Pro: adversarial review │
              │ multi-step reasoning:  │   │ of specs/diffs/designs      │
              │ implement, analyze,    │   │ 3.5 Flash: summaries,       │
              │ spec, research         │   │ lookups, web search         │
              └────────────────────────┘   └────────────────────────────┘
```

Why this split pays:

- **Tokenomics.** Burning an expensive model on file reading and boilerplate is waste. Reserving it for decisions and dispatch means the expensive context window holds only the distilled state. Sub-agents return conclusions, not transcripts.
- **Quality.** The single highest-value pattern is dispatching three personas at the same problem in parallel and treating independent convergence as evidence.
- **No shared blind spots.** A Gemini reviewer is a structurally different lens compared to Claude. It catches errors before work is committed.

## Quick start

**Prereqs:** Antigravity 2.0 (`agy`), a GCP project with Vertex AI enabled, and Claude/Gemini models enabled in Vertex Model Garden.

```bash
git clone <this-repo> ~/antigravity-harness

# 1. Configure + load the launchers
export CLAUDE_HARNESS_VERTEX_PROJECT=your-gcp-project
source ~/antigravity-harness/launchers.sh      # add to ~/.bashrc

# 2. Seed your project
cd your-project
cp ~/antigravity-harness/templates/AGY_PROJECT.md ./AGY_PROJECT.md
mkdir -p scripts
cp ~/antigravity-harness/scripts/* scripts/

# 3. Set the budget and launch the brain
python scripts/cost_tracker.py reset --budget 200
agy-fable-vertex        # Launches Fable 5 orchestrator via Vertex
```

## The Protocol (Antigravity Edition)

1. **Subagents via `define_subagent`:** Instead of creating static markdown persona files, the Orchestrator uses Antigravity's `define_subagent` API. The persona's identity, role, and validation matrix are injected directly into the subagent's system prompt.
2. **Disjoint Write-Sets via Workspace Branching:** Parallel subagents run with `Workspace: "share"`, giving each an isolated git worktree. They modify files and commit safely. The Orchestrator reviews the diffs and merges them.
3. **External Validation:** Load-bearing artifacts go through the Gemini reviewer *before* they ship (`scripts/gemini_consult.py`). Findings are advisory.
4. **Budget:** The orchestrator logs sub-agent token totals and Gemini calls into `cost_tracker.py`. On Vertex, `vertex_meter.py` true-ups the ledger from server-side metering.

## Cost monitoring that's actually honest

| Layer | Source | Precision |
|---|---|---|
| Ledger (`cost_tracker.py`) | sub-agent token totals + Gemini usage | precise for subagents |
| Metering (`vertex_meter.py`) | Vertex `token_count` monitoring metric | authoritative counts; cache-aware |
| Billing | your cloud bill | the only real number |

## Repo layout

```
launchers.sh                      # aliases for agy-fable-vertex, etc.
scripts/
  gemini_consult.py               # one-shot tier: review, summarize, --search
  cost_tracker.py                 # budget ledger; exit 2 at cap
  vertex_meter.py                 # cache-aware true-up from Vertex metering
templates/
  AGY_PROJECT.md                  # drop-in project guide
```

## License

MIT
