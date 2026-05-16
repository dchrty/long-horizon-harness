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

## Judgement gating (handled by the harness)

This project's correctness is hard to assert with a fixed oracle — the
example corpus only covers a slice of valid COBOL. Pattern / extractor
changes are gated by a fresh `claude` subprocess that reads `JUDGE.md`
with no context from you.

**You do not invoke the judge.** The harness installs a `pre-receive`
hook in `upstream.git/hooks/` at `agent-factory init` time. The hook
runs on every `git push` and gates any commit whose changes touch a
path listed in `.judge-gates` at the repo root. The commit message is
the judge's input — write a good one and the judge has what it needs.

The gated paths for this project are listed in `.judge-gates`. Edit
that file (and commit the edit) if you add a new domain layer the
judge should evaluate.

### What a good commit message looks like

The judge reads your commit message verbatim as the summary. Write it
like you'd write a code-review note: state intent, cite the spec,
report what tests cover the change, mention any risk you're uncertain
about. A terse "fix call extraction" gets the judge nothing to weigh
against; a well-written message gets the benefit of the doubt.

```
Add EXEC SQL INCLUDE support (closes exec-sql-include)

Recognises COPYBOOK references inside EXEC SQL INCLUDE statements
as a copy edge, not a call edge.

Spec: IBM DB2 Application Programming and SQL Guide §10.4
   (EXEC SQL INCLUDE syntax).

Tests: 14 -> 16 passing (added test_exec_sql_include_basic and
   test_exec_sql_include_with_dclgen).

Risk: assumes INCLUDE is always a copybook reference, not a literal
   SQL include — IBM dialect specific, may not hold on Micro Focus.
```

### When your push is rejected

If the judge returns `fail`, the pre-receive hook rejects the push.
You'll see a rejection message with the rationale. Three options:

1. **Amend the commit** with the spec citation, missing test, or
   tightened logic the judge flagged, then push again.
2. **Roll back** (`git reset --hard HEAD~1`) if the approach was
   wrong and start over with a different design.
3. **Record the lesson** by appending an entry to `verdicts.json`
   before retrying — useful when the failure mode is one a future
   agent might repeat.

The hook also accepts pushes that don't touch any path in
`.judge-gates`. Pure refactors, test-only commits, and doc-only
changes are not gated.

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
