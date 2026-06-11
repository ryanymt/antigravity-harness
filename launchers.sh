# Antigravity provider/model launchers — source from ~/.bashrc or ~/.zshrc:
#   source /path/to/antigravity-harness/launchers.sh
#
# Configure once:
export CLAUDE_HARNESS_VERTEX_PROJECT="${CLAUDE_HARNESS_VERTEX_PROJECT:-your-gcp-project}"
export GEMINI_VERTEX_PROJECT="${GEMINI_VERTEX_PROJECT:-$CLAUDE_HARNESS_VERTEX_PROJECT}"
export VERTEX_METER_PROJECT="${VERTEX_METER_PROJECT:-$CLAUDE_HARNESS_VERTEX_PROJECT}"

# Orchestrator session on Vertex: Fable 5 main brain
agy-fable-vertex() {
  AGY_PROVIDER=vertex \
  AGY_VERTEX_PROJECT_ID="$CLAUDE_HARNESS_VERTEX_PROJECT" \
  AGY_VERTEX_REGION=global \
  AGY_MODEL="claude-fable-5" \
  command agy "$@"
}

# Subagent default for Opus
export AGY_DEFAULT_SUBAGENT_MODEL="claude-opus-4-8"
