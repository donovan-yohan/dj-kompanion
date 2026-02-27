#!/bin/bash
# Ralph Loop Runner — runs a claude -p session in a loop until completion
# Usage: ./scripts/ralph-run.sh <phase-name> <prompt-file> <completion-file> [max-iterations]

set -euo pipefail

PHASE_NAME="${1:?Usage: ralph-run.sh <phase-name> <prompt-file> <completion-file> [max-iterations]}"
PROMPT_FILE="${2:?Missing prompt file}"
COMPLETION_FILE="${3:?Missing completion file}"
MAX_ITERATIONS="${4:-10}"

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

# Unset CLAUDECODE to allow launching claude CLI from within a claude session
unset CLAUDECODE

LOG_FILE=".claude/ralph-${PHASE_NAME}.log"
mkdir -p .claude

echo "[$PHASE_NAME] Starting ralph loop (max $MAX_ITERATIONS iterations)" | tee "$LOG_FILE"
echo "[$PHASE_NAME] Prompt: $PROMPT_FILE" | tee -a "$LOG_FILE"
echo "[$PHASE_NAME] Completion marker: $COMPLETION_FILE" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

ITERATION=0

while [ ! -f "$COMPLETION_FILE" ] && [ "$ITERATION" -lt "$MAX_ITERATIONS" ]; do
  ITERATION=$((ITERATION + 1))
  echo "[$PHASE_NAME] === Iteration $ITERATION / $MAX_ITERATIONS ===" | tee -a "$LOG_FILE"
  echo "[$PHASE_NAME] Started at $(date)" | tee -a "$LOG_FILE"

  # Run claude with the prompt file
  PROMPT_CONTENT="$(cat "$PROMPT_FILE")"

  if claude -p "$PROMPT_CONTENT" --dangerously-skip-permissions --model sonnet >> "$LOG_FILE" 2>&1; then
    echo "[$PHASE_NAME] Iteration $ITERATION completed successfully" | tee -a "$LOG_FILE"
  else
    echo "[$PHASE_NAME] Iteration $ITERATION exited with error (will retry)" | tee -a "$LOG_FILE"
  fi

  # Check if completion marker was created
  if [ -f "$COMPLETION_FILE" ]; then
    echo "[$PHASE_NAME] COMPLETE! Marker file found after iteration $ITERATION" | tee -a "$LOG_FILE"
    break
  fi

  echo "[$PHASE_NAME] Not yet complete, looping..." | tee -a "$LOG_FILE"
  echo "" | tee -a "$LOG_FILE"
done

if [ -f "$COMPLETION_FILE" ]; then
  echo "[$PHASE_NAME] SUCCESS — completed in $ITERATION iteration(s)" | tee -a "$LOG_FILE"
  exit 0
else
  echo "[$PHASE_NAME] INCOMPLETE — hit max iterations ($MAX_ITERATIONS)" | tee -a "$LOG_FILE"
  exit 1
fi
