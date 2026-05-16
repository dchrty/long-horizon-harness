# COBOL Relationships Agent Instructions

You are an autonomous agent working on `cobol_rels`, a deterministic
Python tool that walks a directory of COBOL source and emits a JSON
dependency graph between programs (`*.cbl`), copybooks (`*.cpy`), and
called sub-programs. The repo is located at `/workspace/code/`.

You are one of many parallel agents working on the same codebase
simultaneously. Other agents may be pushing changes while you work. You
must coordinate using the task locking protocol described below.

Your goal: produce a tool a maintainer can run on an unfamiliar COBOL
codebase to see "what depends on what" before refactoring. Output must
be deterministic and JSON-serialisable. Correctness is judged by
**agentic judgement**, not by the example corpus alone — see
"Judgement gating" below.

## First Steps (Every Session)

1. Read this `GOAL.md` and `JUDGE.md` (what the judge cares about).
2. Read `verdicts.json` — your institutional memory. Every entry is a
   past failure with a lesson. Skim it before writing any parsing code.
3. Read `README.md` if it exists.
4. List `current_tasks/` to see what other agents are working on.
5. Run `python3 -m pytest -q` to check current test status (the suite
   exists for regressions; it is *not* the oracle).
6. If no `src/cobol_rels/` exists yet, scaffolding it is the next task.

If tests are red on `main`, fixing them is your top priority.

## Task Locking Protocol

This is critical for coordinating with other agents. Follow it
precisely.

### Claiming a Task

Before starting any work:

1. Choose a task (see "Choosing What to Work On" below).
2. Create `current_tasks/<descriptive_task_name>.txt` containing:
   - One-line summary of what you're implementing.
   - Files you plan to modify.
   - Current date as `Started: YYYY-MM-DD`.
   - Whether the change will need to go through the judge (parsing
     changes do; pure refactors don't).
3. Commit and push immediately:
   ```
   git add current_tasks/<task_name>.txt
   git commit -m "Lock task: <descriptive task name>"
   git pull --rebase
   git push
   ```
4. If the push fails due to a conflict, another agent claimed something
   at the same time. Pull, check if your task is still available, and
   try again or pick something else.

### Completing a Task

1. Run the judge if required (see "Judgement gating" below).
2. Delete the lock file.
3. Commit everything together:
   ```
   git rm current_tasks/<task_name>.txt
   git add -A
   git commit -m "<concise description> (closes <task_name>)

   <what changed, test results, judge verdict id if applicable>"
   git pull --rebase
   git push
   ```

### Pushing Work In Progress

For longer tasks, push intermediate commits often:

```
git add -A
git commit -m "<incremental description>"
git pull --rebase
git push
```

Your session can be killed at any time — unpushed work is lost forever.

### Stale Lock Cleanup

If you see lock files in `current_tasks/` older than 2 hours (check
the `Started:` date), the owning agent likely crashed. Remove the
stale lock to unblock the task.

## Choosing What to Work On

Check these in priority order:

1. **Test failures**: if `python3 -m pytest -q` is red, fix it first.
2. **No scaffolding yet**: create `src/cobol_rels/` with a CLI entry
   point (`python3 -m cobol_rels <dir>`) that walks a directory and
   prints the graph JSON to stdout.
3. **Open verdicts**: every "fail" entry in `verdicts.json` is a
   missed corner case. Pick one, fix the root cause, regression-test
   it. Reference the verdict id in your commit.
4. **Missing relationship type**: add support for a COBOL statement
   you can cite a spec section for (`CALL`, `COPY`, `EXEC SQL INCLUDE`,
   `CHAIN`, …). Cite the source in the commit message; the judge will
   check.
5. **Dialect handling**: surface dialect-specific differences (IBM
   Enterprise vs Micro Focus vs GnuCOBOL) as documented assumptions.
6. **Determinism / output stability**: sort keys, stable IDs, no
   timestamps embedded in the graph.
7. **Docs**: keep `README.md` in sync with the public CLI / API.

Avoid duplicating another agent's work. Check `current_tasks/` first.

## Judgement gating with `./judge.sh`

This project's correctness is hard to assert with a fixed oracle — the
example corpus only covers a slice of valid COBOL. Before pushing a
commit to `main` that introduces or changes parsing logic, you MUST
have it judged. The judge is a *fresh* `claude` subprocess that reads
`JUDGE.md` and your change with no context from you.

### When to invoke

Invoke `./judge.sh` after any commit that:

- Adds new parsing logic (regex, lexer, statement detection).
- Changes how a relationship is extracted (`CALL`, `COPY`, `INCLUDE`, …).
- Touches handling of dialect-specific syntax.

You do **not** need to invoke the judge for pure refactors, doc-only
changes, or test-suite-only additions.

### How to invoke

1. Commit your change normally. Note the commit hash.
2. Write a short summary at `/tmp/agent_summary_<short_hash>.md`:
   - **Intent**: what you were trying to do.
   - **What you changed**: which files / functions.
   - **How you tested**: what runs you did against the corpus.
   - **Why you think this is right**: spec citations, dialect reasoning.
   - **Risk you're uncertain about**: assumptions you didn't fully
     verify.
3. Identify repo paths the judge should look at. Typically include the
   files you changed and `corpus/sample_cobol/` so the judge can
   inspect for overfitting.
4. Invoke (the judge.sh is at the repo root, seeded by the harness):

   ```bash
   HASH=$(git rev-parse HEAD)
   SHORT=$(git rev-parse --short HEAD)

   JUDGE_GIT_HASH="$HASH" \
   JUDGE_INPUT_FILE="/tmp/agent_summary_${SHORT}.md" \
   JUDGE_OUTPUT_FILE="/tmp/verdict_${SHORT}.json" \
   JUDGE_CONTEXT=$'corpus/sample_cobol/\nsrc/cobol_rels/<file_you_changed>.py' \
     ./judge.sh
   ```

5. Read the verdict file. If `verdict == "pass"`, push to `main`. If
   `fail`, follow the recovery flow below.

### On a `fail` verdict

The judge has flagged your change. Do **not** push it to `main`.
Instead:

1. Open `verdicts.json` at the repo root. Find the max existing
   `v-NNNN` id and pick the next one (or use
   `agent_factory.verdicts.next_id` if available).
2. Append a new entry:
   - `id`, `timestamp` (ISO 8601, UTC, `Z`-suffixed)
   - `agent_id` (your `$AGENT_ID` env var)
   - `git_hash`, `git_hash_parent`
   - `intent` (from your own summary)
   - `what_went_wrong` (your honest read of why the judge failed it)
   - `judge_rationale` (copied from the verdict JSON `rationale`)
   - `lesson` (one sentence; what to tell the next agent)
   - `tags` (short kebab-case labels)
3. Push the failing commit to a preservation ref instead of `main`:

   ```bash
   git push origin "$HASH":refs/bad-attempts/v-NNNN-<short-slug>
   ```

4. `git reset --hard HEAD^`, commit the updated `verdicts.json`, push,
   and start a new attempt with the lesson in hand.

If the judge fails with exit code 2 (infra error), the verdict file
isn't written — re-run; if it keeps failing, file an idea in
`current_tasks/judge_infra_<date>.txt` and pick a different task.

## Testing

```
python3 -m pytest -q
```

The test suite exists for **regression** — once a real-world COBOL
construct is handled correctly, freeze it with a test. It is **not**
the correctness oracle (the judge is). Always run tests before
pushing. Include results in the commit message:

```
14/14 passing (added EXEC SQL INCLUDE; judge v-0023 pass)
```

## Git Workflow

Push frequently. Other agents are working in parallel.

```
git add -A
git commit -m "<concise description>

<detailed explanation if needed>
<test results>
<judge verdict id if applicable>"
git pull --rebase
git push
```

If you hit a merge conflict during rebase:

- Read both sides carefully.
- Integrate both changes, prefer keeping spec citations and verdict
  references.
- `git add <resolved> && git rebase --continue`, then push.

## Documentation

- `README.md` — keep the public CLI/API and supported COBOL constructs
  up to date.
- `verdicts.json` — append-only, ordered by id. Don't rewrite history.
- Each new parsing rule should cite a spec section in either the code
  comment or the commit message.

## Important Rules

- **One logical change per commit.** Don't bundle unrelated fixes.
- **Pushing parser changes to `main` without a `pass` verdict is a
  bug.** The judge is the oracle.
- **The example corpus is not a test oracle.** Passing it means
  nothing on its own; the judge checks for overfitting.
- **Cite a spec.** Every syntactic assumption needs a citation to a
  real COBOL reference (IBM Enterprise, Micro Focus, GnuCOBOL, COBOL
  85/2002/2014/2023) or a named dialect quirk.
- **Determinism.** Stable key order, stable ids, no timestamps in the
  graph output. The judge will reject non-determinism.
- **Document dead ends.** Failed approaches go in the next task lock
  or a new verdict entry — don't make the next agent rediscover them.
- **Push often.** Don't accumulate large unpushed changes.
- **Keep going.** When you finish one task, pick up the next.
