# Goal: a deterministic tool that parses relationships between COBOL files

You are one of several parallel agents working in this shared repo. Your
collective objective:

> Build a Python tool, `cobol_rels`, that walks a directory of COBOL
> source and produces a dependency graph between programs (`*.cbl`),
> copybooks (`*.cpy`), and called sub-programs. The output should be
> deterministic and JSON-serialisable so it can be consumed by other
> tools.

The driving use case: a maintainer hands you an unfamiliar COBOL
codebase and wants to see "what depends on what" before refactoring.

## Build / test

Pure Python. No deps beyond pytest. To check yourself:

```bash
python3 -m pytest -q
python3 -m cobol_rels corpus/sample_cobol > /tmp/graph.json   # smoke test
```

The example corpus lives at `corpus/sample_cobol/`. Use it for
manual sanity checks. **Do not** treat it as the test oracle — it is a
small, narrow sample. See `JUDGE.md`.

## Coordination protocol

Multi-agent, lock-file based:

1. Pick a piece of work.
2. Claim with `current_tasks/<name>.txt` containing one-line summary +
   `Started: YYYY-MM-DD`.
3. `git add ... && git commit -m "Lock: <name>" && git pull --rebase && git push`.
4. Implement, test, push frequently.
5. Run the **judge** (see below) before merging to `main`.

If you see a lock older than 2 hours, the owner crashed — clear it.

## Judgement gating with `judge.sh`

This project's correctness is hard to assert with a fixed test oracle —
the example corpus only covers a slice of valid COBOL. Before pushing
a commit to `main` that introduces or changes parsing logic, you MUST
have it judged.

### When to invoke

Invoke `./judge.sh` after any commit that:

- Adds new parsing logic (regex, lexer, statement detection).
- Changes how a relationship is extracted (CALL, COPY, INCLUDE, etc.).
- Touches handling of dialect-specific syntax.

You do **not** need to invoke the judge for pure refactors, doc-only
changes, or test-suite-only additions.

### How to invoke

1. Commit your change normally. Note the commit hash (e.g. `git rev-parse HEAD`).
2. Write a short summary file at `/tmp/agent_summary_<HASH>.md`:
   - **Intent**: what you were trying to do
   - **What you changed**: which files / functions
   - **How you tested**: what runs you did against the corpus
   - **Why you think this is right**: justification
   - **Risk you're uncertain about**: assumptions you didn't fully verify
3. Identify repo paths that bear on the change. Typical includes:
   - The example corpus (`corpus/sample_cobol/`) so the judge can
     check for overfitting.
   - The files you modified.
   - Any spec docs you cited.
4. Invoke:

   ```bash
   JUDGE_GIT_HASH=$(git rev-parse HEAD) \
   JUDGE_INPUT_FILE=/tmp/agent_summary_$(git rev-parse --short HEAD).md \
   JUDGE_OUTPUT_FILE=/tmp/verdict_$(git rev-parse --short HEAD).json \
   JUDGE_CONTEXT=$'corpus/sample_cobol/\nsrc/cobol_rels/<file_you_changed>.py' \
     ./judge.sh
   ```

5. Read the verdict file. If `verdict == "pass"`, push to `main`.

### On a `fail` verdict

The judge has flagged your change. Do not push it to `main`. Instead:

1. Open `verdicts.json` at the repo root.
2. Compute the next ID: `vNNNN` where N is the current max + 1.
3. Append a new verdict entry capturing:
   - `id`, `timestamp`, `agent_id`, `git_hash`, `git_hash_parent`
   - `intent` (from your own summary above)
   - `what_went_wrong` (your honest reading of why the judge failed it)
   - `judge_rationale` (copied from the verdict JSON's `rationale`)
   - `lesson` (one sentence: what you would tell the next agent)
   - `tags` (short kebab-case labels)
4. Push the failing commit to a preservation ref instead of `main`:

   ```bash
   git push origin <bad_hash>:refs/bad-attempts/v-NNNN-<short-slug>
   ```

5. `git reset --hard HEAD^` and start over with the lesson in hand.

### Always do this at session start

Read `verdicts.json` before doing any parsing work. It is your
institutional memory — your predecessors learned things the hard way.

## Files in this repo

- `GOAL.md` — this file.
- `JUDGE.md` — what the judge cares about. Read it.
- `judge.sh` — judge entry point (shipped by the harness; you may edit
  the prompt if you have a good reason).
- `verdicts.json` — past failures. Read at session start.
- `current_tasks/` — work claim locks.
- `corpus/sample_cobol/` — small example corpus. Useful for sanity
  but biased; do not overfit.

## Rules

- One logical change per commit.
- Pushing parser changes to `main` without a judge "pass" is a bug.
- The example corpus is not a test oracle.
- Cite a COBOL spec or named dialect reference for any syntactic
  assumption. The judge will check.
