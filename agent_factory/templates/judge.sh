#!/bin/bash
# =============================================================================
# judge.sh — fresh-context judgement of an agent commit
# =============================================================================
# Spawned by the calling agent. Reads JUDGE.md from the repo root and runs a
# fresh `claude` subprocess (no inherited context) to evaluate a commit.
#
# Inputs (environment variables):
#   JUDGE_GIT_HASH     commit the agent wants judged (required)
#   JUDGE_INPUT_FILE   path to an agent-written summary of intent + changes
#                      (required)
#   JUDGE_OUTPUT_FILE  where to write the verdict JSON (required)
#   JUDGE_CONTEXT      newline-separated repo-relative paths the judge
#                      should inspect (optional)
#   JUDGE_MODEL        model for the judge subprocess
#                      (default: $AGENT_MODEL or claude-opus-4-6)
#   JUDGE_LOG_DIR      where to write the tee log and JSONL history
#                      (default: /workspace/agent_logs)
#
# Reads from cwd: JUDGE.md (required), verdicts.json (optional).
#
# Output: writes a JSON object to JUDGE_OUTPUT_FILE:
#   { "verdict": "pass" | "fail", "rationale": "...", "concerns": [ ... ] }
# Exit code: 0 on "pass", 1 on "fail", 2 on infrastructure error.
#
# Side-effects (the "visibility layer" — see also `agent-factory judges`):
#   - Writes the full claude judge transcript to
#       $JUDGE_LOG_DIR/<agent>_judge_<short-hash>_<ts>.log
#     so the operator can inspect what the judge actually saw and said.
#   - Appends one JSON line per invocation to
#       $JUDGE_LOG_DIR/judge_history.jsonl
#     with timing, exit code, verdict, and the tee-log path. Single-line
#     atomic append; safe for concurrent agents.
#   - Emits two marker lines on stderr so the agent-factory logs view
#       [JUDGE-START] hash=<short> agent=<id> model=<name> ts=<iso> log=<path>
#       [JUDGE-END]   hash=<short> verdict=<v> exit=<n> duration_ms=<ms> log=<path>
#     can show "judge running" / "judge done" without a separate channel.
# =============================================================================

set -e

: "${JUDGE_GIT_HASH:?JUDGE_GIT_HASH must be set}"
: "${JUDGE_INPUT_FILE:?JUDGE_INPUT_FILE must be set}"
: "${JUDGE_OUTPUT_FILE:?JUDGE_OUTPUT_FILE must be set}"

# Bookkeeping setup. Nanosecond timer for duration; ISO timestamp for
# the JSONL ts field. AGENT_ID defaults to "host" so running judge.sh
# outside a container (manual debugging) still produces a valid record.
JUDGE_START_NS=$(date +%s%N)
TS_ISO=$(date -u +%Y-%m-%dT%H:%M:%SZ)
SHORT="${JUDGE_GIT_HASH:0:8}"
AGENT_ID="${AGENT_ID:-host}"
JUDGE_MODEL="${JUDGE_MODEL:-${AGENT_MODEL:-claude-opus-4-6}}"
LOG_DIR="${JUDGE_LOG_DIR:-/workspace/agent_logs}"
mkdir -p "$LOG_DIR" 2>/dev/null || true
JUDGE_LOG="$LOG_DIR/${AGENT_ID}_judge_${SHORT}_$(date +%s).log"
HISTORY_FILE="$LOG_DIR/judge_history.jsonl"

if [ ! -f JUDGE.md ]; then
    echo "judge.sh: JUDGE.md not found in cwd ($PWD)" >&2
    exit 2
fi

if [ ! -f "$JUDGE_INPUT_FILE" ]; then
    echo "judge.sh: agent summary not found: $JUDGE_INPUT_FILE" >&2
    exit 2
fi

PROMPT_FILE=$(mktemp)
RAW_FILE=$(mktemp)
trap 'rm -f "$PROMPT_FILE" "$RAW_FILE"' EXIT

# Start marker — goes to stderr, captured by the agent's tee, surfaces
# in `agent-factory logs` so the operator can see judge runs flow by.
echo "[JUDGE-START] hash=$SHORT agent=$AGENT_ID model=$JUDGE_MODEL ts=$TS_ISO log=$JUDGE_LOG" >&2

# ---- Build prompt --------------------------------------------------------
{
    echo "You are a Judge. You have NO prior context from the agent under review."
    echo "Read every section below carefully, then decide whether the commit"
    echo "satisfies the criteria in JUDGE.md."
    echo ""
    echo "================================================================"
    echo "## JUDGE.md (the criteria you must evaluate against)"
    echo "================================================================"
    cat JUDGE.md
    echo ""
    echo "================================================================"
    echo "## Commit under review: ${JUDGE_GIT_HASH}"
    echo "## Diff (git show)"
    echo "================================================================"
    git show "$JUDGE_GIT_HASH" 2>&1 || echo "(git show failed)"
    echo ""
    echo "================================================================"
    echo "## Agent's own summary of intent and changes"
    echo "================================================================"
    cat "$JUDGE_INPUT_FILE"
    echo ""

    if [ -n "${JUDGE_CONTEXT:-}" ]; then
        echo "================================================================"
        echo "## Repo context the agent thinks you should examine"
        echo "================================================================"
        while IFS= read -r relpath; do
            [ -z "$relpath" ] && continue
            echo "----- $relpath -----"
            if [ -d "$relpath" ]; then
                # Inline up to 50 files from the directory, head -200 lines each
                find "$relpath" -type f 2>/dev/null | head -50 | while read -r f; do
                    echo ""
                    echo "  (file: $f)"
                    head -200 "$f" 2>/dev/null | sed 's/^/    /'
                done
            elif [ -f "$relpath" ]; then
                cat "$relpath" 2>/dev/null || true
            else
                echo "(no such path)"
            fi
        done <<< "$JUDGE_CONTEXT"
        echo ""
    fi

    if [ -f verdicts.json ]; then
        echo "================================================================"
        echo "## Prior verdicts (verdicts.json) — institutional memory"
        echo "================================================================"
        cat verdicts.json
        echo ""
    fi

    cat <<'PROMPT_TAIL'
================================================================
## Your task
================================================================
Decide whether this commit passes the criteria in JUDGE.md.

Output EXACTLY ONE JSON object between the markers below.
No prose, no markdown fences, nothing outside the markers.

Schema (exact field names, no extras):
  { "verdict": "pass" | "fail",
    "rationale": "one-paragraph explanation",
    "concerns": [ "short bullet", "short bullet", ... ] }

<<<VERDICT_BEGIN>>>
{ ... your JSON here ... }
<<<VERDICT_END>>>
PROMPT_TAIL
} > "$PROMPT_FILE"

# ---- Run a fresh claude subprocess --------------------------------------

if ! command -v claude >/dev/null 2>&1; then
    echo "judge.sh: claude CLI not found on PATH" >&2
    DURATION_MS=$(( ($(date +%s%N) - JUDGE_START_NS) / 1000000 ))
    echo "[JUDGE-END] hash=$SHORT verdict=infra-error exit=2 duration_ms=$DURATION_MS log=$JUDGE_LOG" >&2
    # Append history even on infra error — operators want to see attempts.
    printf '{"ts":"%s","agent_id":"%s","git_hash":"%s","git_hash_short":"%s","model":"%s","exit_code":2,"verdict":"infra-error","duration_ms":%d,"tee_log":"%s"}\n' \
        "$TS_ISO" "$AGENT_ID" "$JUDGE_GIT_HASH" "$SHORT" "$JUDGE_MODEL" "$DURATION_MS" "$JUDGE_LOG" \
        >> "$HISTORY_FILE" 2>/dev/null || true
    exit 2
fi

# Tee claude's combined stdout+stderr to the host-visible log AND the
# parser temp file. Operator can later `agent-factory judges --show <hash>`
# to inspect the full transcript; the parser only needs RAW_FILE.
# `|| true` matches the prior behavior of tolerating non-zero claude exits;
# the python block below decides the actual verdict.
claude --dangerously-skip-permissions \
       --model "$JUDGE_MODEL" \
       -p "$(cat "$PROMPT_FILE")" \
       2>&1 | tee "$JUDGE_LOG" > "$RAW_FILE" || true

# ---- Extract the verdict JSON -------------------------------------------
# Disable -e so we can capture the python exit code instead of crashing
# on a non-zero. Re-enable after.
set +e
RAW_FILE="$RAW_FILE" VERDICT_OUTPUT="$JUDGE_OUTPUT_FILE" python3 <<'PY'
import json, os, re, sys

raw = open(os.environ["RAW_FILE"], encoding="utf-8", errors="replace").read()

parsed = None

m = re.search(r"<<<VERDICT_BEGIN>>>\s*(\{.*?\})\s*<<<VERDICT_END>>>", raw, re.DOTALL)
if m:
    try:
        parsed = json.loads(m.group(1))
    except json.JSONDecodeError:
        parsed = None

if parsed is None:
    for candidate in reversed(re.findall(r"\{[^{}]*\"verdict\"[^{}]*\}", raw, re.DOTALL)):
        try:
            parsed = json.loads(candidate)
            break
        except json.JSONDecodeError:
            continue

if parsed is None or not isinstance(parsed, dict):
    sys.stderr.write("judge.sh: could not extract verdict JSON from claude output\n")
    sys.stderr.write("--- last 2000 chars of output ---\n")
    sys.stderr.write(raw[-2000:] + "\n")
    sys.exit(2)

parsed.setdefault("rationale", "")
parsed.setdefault("concerns", [])
verdict = parsed.get("verdict", "fail")
if verdict not in ("pass", "fail"):
    verdict = "fail"
parsed["verdict"] = verdict

with open(os.environ["VERDICT_OUTPUT"], "w", encoding="utf-8") as fh:
    json.dump(parsed, fh, indent=2)

sys.exit(0 if verdict == "pass" else 1)
PY
PYTHON_EXIT=$?
set -e

# Read the parsed verdict back so we can include it in the history record.
# Defensive: if the python parser crashed before writing the file, the
# verdict is "infra-error" (matches exit code 2 semantics).
VERDICT_STR="infra-error"
if [ -f "$JUDGE_OUTPUT_FILE" ]; then
    VERDICT_STR=$(python3 -c "import json,sys; print(json.load(open('$JUDGE_OUTPUT_FILE')).get('verdict','unknown'))" 2>/dev/null || echo "infra-error")
fi

DURATION_MS=$(( ($(date +%s%N) - JUDGE_START_NS) / 1000000 ))

# End marker — pairs with [JUDGE-START] in the agent log stream.
echo "[JUDGE-END] hash=$SHORT verdict=$VERDICT_STR exit=$PYTHON_EXIT duration_ms=$DURATION_MS log=$JUDGE_LOG" >&2

# Append one JSON line. printf is safe here because every field is harness-
# controlled (sanitized names, hex hash, ISO timestamp, model alias) and
# the line is well under PIPE_BUF (4096), so O_APPEND writes are atomic
# even with concurrent agents calling judge.sh simultaneously.
printf '{"ts":"%s","agent_id":"%s","git_hash":"%s","git_hash_short":"%s","model":"%s","exit_code":%d,"verdict":"%s","duration_ms":%d,"tee_log":"%s"}\n' \
    "$TS_ISO" "$AGENT_ID" "$JUDGE_GIT_HASH" "$SHORT" "$JUDGE_MODEL" "$PYTHON_EXIT" "$VERDICT_STR" "$DURATION_MS" "$JUDGE_LOG" \
    >> "$HISTORY_FILE" 2>/dev/null || true

exit $PYTHON_EXIT
