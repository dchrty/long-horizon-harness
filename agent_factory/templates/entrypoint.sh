#!/bin/bash
# =============================================================================
# Agent Factory — in-container loop
# =============================================================================
# Each iteration:
#   1. Fresh clone from /upstream
#   2. Clear stale task locks under current_tasks/ (best-effort; first agent
#      to push wins).
#   3. Run Claude Code with a generic kickoff prompt that points it at GOAL.md.
#      The repo's GOAL.md tells the agent everything else: what to build, how
#      to coordinate, whether to invoke judge.sh, when to read verdicts.json.
#   4. Loop.
#
# On SIGTERM (docker stop), saves any uncommitted work before exiting.
# =============================================================================

AGENT_ID="${AGENT_ID:-agent-unknown}"
AGENT_MODEL="${AGENT_MODEL:-claude-opus-4-6}"
LOG_DIR="/workspace/agent_logs"
CLAUDE_PID=""

mkdir -p "$LOG_DIR"

save_work() {
    echo "[$AGENT_ID] Caught shutdown signal, saving uncommitted work..."
    if [ -n "$CLAUDE_PID" ]; then
        kill "$CLAUDE_PID" 2>/dev/null
        wait "$CLAUDE_PID" 2>/dev/null
    fi
    if [ -d /workspace/code/.git ]; then
        cd /workspace/code
        if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
            git add -A 2>/dev/null
            git commit -m "WIP: auto-save uncommitted work from ${AGENT_ID}

Co-Authored-By: ${AGENT_MODEL} <noreply@anthropic.com>" 2>/dev/null
            git pull --rebase 2>/dev/null || true
            git push 2>/dev/null && echo "[$AGENT_ID] Work saved successfully." \
                                 || echo "[$AGENT_ID] Failed to push saved work."
        else
            echo "[$AGENT_ID] No uncommitted changes to save."
        fi
    fi
    exit 0
}

trap save_work SIGTERM SIGINT

echo "[$AGENT_ID] Starting agent loop at $(date -u)"
echo "[$AGENT_ID] Model: $AGENT_MODEL"

while true; do
    echo "[$AGENT_ID] === New iteration at $(date -u) ==="

    rm -rf /workspace/code
    git clone /upstream /workspace/code 2>/dev/null
    cd /workspace/code

    COMMIT=$(git rev-parse --short=6 HEAD 2>/dev/null || echo "empty")
    LOGFILE="$LOG_DIR/${AGENT_ID}_${COMMIT}_$(date +%s).log"

    # First agent in a run clears stale task locks. Race; only the first
    # successful push wins, others rebase to the cleared state.
    if ls current_tasks/*.txt 1>/dev/null 2>&1; then
        LOCK_COUNT=$(ls current_tasks/*.txt 2>/dev/null | wc -l)
        echo "[$AGENT_ID] Found $LOCK_COUNT stale task locks, attempting to clear..."
        git rm current_tasks/*.txt 2>/dev/null || true
        git commit -m "Starting new run; clearing task locks" 2>/dev/null || true
        git push 2>/dev/null || {
            echo "[$AGENT_ID] Another agent already cleared locks, pulling..."
            git pull --rebase 2>/dev/null || true
        }
    fi

    echo "[$AGENT_ID] Running Claude Code session (HEAD: $COMMIT)..."

    claude --dangerously-skip-permissions \
           -p "You are autonomous agent ${AGENT_ID}. Read GOAL.md at the repo root for your full instructions, then start working. Keep going until your session ends.

CRITICAL: You MUST push your work frequently. After creating or modifying each file, do: git add -A && git commit -m \"description\" && git pull --rebase && git push. Do NOT wait until everything is done. Push after every meaningful change. Your session can be killed at any time and unpushed work is lost forever." \
           --model "$AGENT_MODEL" \
           2>&1 | tee "$LOGFILE" &
    CLAUDE_PID=$!
    wait $CLAUDE_PID
    CLAUDE_PID=""

    echo "[$AGENT_ID] Session ended, restarting loop..."
    sleep 5
done
