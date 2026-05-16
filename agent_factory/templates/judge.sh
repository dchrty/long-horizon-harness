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
#
# Reads from cwd: JUDGE.md (required), verdicts.json (optional).
#
# Output: writes a JSON object to JUDGE_OUTPUT_FILE:
#   { "verdict": "pass" | "fail", "rationale": "...", "concerns": [ ... ] }
# Exit code: 0 on "pass", 1 on "fail", 2 on infrastructure error.
# =============================================================================

set -e

: "${JUDGE_GIT_HASH:?JUDGE_GIT_HASH must be set}"
: "${JUDGE_INPUT_FILE:?JUDGE_INPUT_FILE must be set}"
: "${JUDGE_OUTPUT_FILE:?JUDGE_OUTPUT_FILE must be set}"

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
JUDGE_MODEL="${JUDGE_MODEL:-${AGENT_MODEL:-claude-opus-4-6}}"

if ! command -v claude >/dev/null 2>&1; then
    echo "judge.sh: claude CLI not found on PATH" >&2
    exit 2
fi

claude --dangerously-skip-permissions \
       --model "$JUDGE_MODEL" \
       -p "$(cat "$PROMPT_FILE")" \
       > "$RAW_FILE" 2>&1 || true

# ---- Extract the verdict JSON -------------------------------------------
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
