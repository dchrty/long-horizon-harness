# AGENTS.md — Building the Generalized Async Agent Factory

This document instructs you, a Claude Code agent, how to evolve
[`async_compiler_factory`](https://github.com/vizopsai/async_compiler_factory.git)
into a **general-purpose async agent harness** that drives any
long-running, goal-directed software task — not just a C compiler.

The four goals below describe the target state. Work through them in
order.

---

## Context: What We Are Generalizing From

`async_compiler_factory` spawns N parallel Claude Code agents in Docker
containers, all coordinating through a shared bare git repo
(`upstream.git`). Agents claim tasks via lock files in `current_tasks/`,
push commits frequently, and follow the instructions in `CLAUDE.md` at
the repo root — which today is hard-coded to "build a C compiler" and
includes compiler-specific testing guidance (a `run_tests.sh` script
that diffs `.c` test outputs).

Three things are hard-coded in ways that block generalization:

1. The **task** is "build a C compiler" — encoded in `CLAUDE.md`,
   `init_repo.sh`, the seed `Cargo.toml`, and `src/main.rs`. All of
   the Rust and C-compiler content has to go, including `run_tests.sh`
   and its `.c`-file assumptions.
2. The **orchestration** is bash. We want Python.
3. There is no concept of tasks where correctness requires
   *judgement* rather than a deterministic check.

The agent runtime stays Claude Code (`claude --dangerously-skip-permissions
... --model claude-opus-4-6`). That is intentional — do not generalize
the agent runtime away.

---

## Goal 1 — Generalize Beyond the C Compiler

Strip the compiler-specific content out of the harness. After this goal,
the harness drives whatever the user puts in `GOAL.md`.

`GOAL.md` is the user's file. It is the generalized successor to the
existing `CLAUDE.md` — same role (the agent's instruction file at the
repo root), renamed because the harness is no longer compiler-specific
and the file describes the user's *goal* rather than being a generic
Claude config. The user writes `GOAL.md` themselves; the harness does
not template or generate it.

### What to remove

- All Rust content: `Cargo.toml` and `src/main.rs` literals in
  `init_repo.sh`, `cargo build --release` references in `entrypoint.sh`,
  `run.sh`, `status.sh`, `analytics.sh`. No Rust anywhere in the harness.
- The compiler-specific `CLAUDE.md` baked into the seed repo.
- The C-compiler `DESIGN_DOC.md` literal in `init_repo.sh`.
- `run_tests.sh` and any compiler-specific testing assumptions (`.c`
  files, expected-output diffing). The harness has no opinion on
  testing — whatever testing exists for a project is described in
  that project's `GOAL.md`.
- Cross-compilers and QEMU in the `Dockerfile`.
- The name `ccc-agent` and `RUN_PREFIX=ccc-...`.

### What the new contract looks like

The user supplies a project directory containing a `GOAL.md`. The
harness reads it, copies it into the initial commit of `upstream.git`
as the repo-root instruction file, and launches agents. That's the
entire contract on the user's side for the basic case.

`GOAL.md` is whatever the user wants it to be — what the project is,
how to build and test it, the coordination protocol, when to invoke
`judge.sh` (Goal 3), when to read `verdicts.json` (Goal 4). The harness
does not parse or validate it.

### Test directory

Add a `test/` directory at the harness root for testing the harness
itself against real projects. Each subdirectory is a small example
project (a `GOAL.md` plus whatever starter files that project needs)
that exercises the harness end-to-end.

### Acceptance for Goal 1

- The harness contains no Rust, no C-compiler references, no
  `Cargo.toml`, no `cargo` commands, no `run_tests.sh`.
- A user with only a `GOAL.md` in a directory can point the harness
  at it and get parallel agents working on their task.
- `test/` contains at least one small example proving the
  generalization works.

---

## Goal 2 — Port the Orchestration from Bash to Python

The host-side shell scripts (`run.sh`, `launch.sh`, `init_repo.sh`,
`status.sh`, `analytics.sh`, `timeseries.sh`) become a Python package.
Bash inside the container (`entrypoint.sh`) stays bash — porting it
adds no value.

### Target structure

```
agent_factory/
    __init__.py
    __main__.py          # `python -m agent_factory ...`
    cli.py               # argparse / typer entrypoint
    config.py            # locates GOAL.md, JUDGE.md in project dir
    docker_runner.py     # builds image, launches/stops containers
    repo.py              # bare repo init, seeding, cloning helpers
    status.py            # status snapshot (replaces status.sh)
    analytics.py         # timeseries + plotting
    judge.py             # judge orchestration (Goal 3)
    verdicts.py          # verdicts.json read/write (Goal 4)
    templates/
        entrypoint.sh    # bash, copied into container unchanged
        Dockerfile       # base image
        judge.sh         # default judge script
test/
    ...
pyproject.toml
README.md
```

CLI verbs (parity with current bash, plus the new ones):

- `python -m agent_factory init`     — equivalent of `init_repo.sh`,
  reads `GOAL.md` from the current project directory.
- `python -m agent_factory run [--agents N] [--duration M]` —
  equivalent of `run.sh`.
- `python -m agent_factory status [--short]` — equivalent of `status.sh`.
- `python -m agent_factory analytics` — equivalent of `analytics.sh`.

### Rules for the port

- Standard library plus `docker` (Python SDK) and `click` or `typer`
  for the CLI. Nothing heavier.
- Subprocess for `git` — keep behaviour identical to the current scripts.
- Logging via `logging`, not `print`. Include agent IDs.
- `entrypoint.sh` stays bash.
- Preserve the SIGTERM-saves-uncommitted-work behaviour from the current
  `entrypoint.sh`. That contract is critical.
- macOS and Linux. No Windows paths.

### Acceptance for Goal 2

- `python -m agent_factory run` reproduces `./run.sh` behaviour
  end-to-end on a test project.
- All host-side bash scripts deleted from the harness root.
- `pytest` covers repo init, status, and verdicts I/O. Docker is mocked
  in unit tests.

---

## Goal 3 — Judgement-Based Gating

Some tasks have no deterministic oracle. The driving example: a tool
that parses relationships between parts of COBOL software (`.cpy`,
`.cbl`, copybooks, called programs). There is no canonical "right
answer" to diff against.

For these tasks, the harness provides a new feature: a `judge.sh`
script that spawns a fresh `claude` subprocess to review the agent's
work and return a verdict deterministically. The outer agent reads
the verdict from a file and continues its work.

### `JUDGE.md` — the user's file

`JUDGE.md` is the user's file. It sits next to `GOAL.md` in the
project directory and describes what the judge is looking for —
overfitting concerns, assumptions that must be traced, regression
rules, output format. The harness copies it into the seed commit so
the in-container `judge.sh` can read it. The harness does not parse or
validate it.

The judge does not know the project's layout — paths to corpora,
fixtures, or reference material are passed in as context at invocation
time (see `judge.sh` contract below).

Example `JUDGE.md` (paraphrased from the COBOL case):

> We are building a deterministic tool that parses relationships between
> parts of COBOL software. When a new feature lands, you (the judge)
> must verify:
>
> 1. The change is not overfit to the example corpus (its path will be
>    provided as context when you are invoked). The logic must
>    generalize to any COBOL codebase following standard conventions.
> 2. Any assumption baked into the new code must be traceable to a real
>    COBOL specification or a documented dialect. Cite the source.
> 3. The change doesn't regress any previously captured verdict (read
>    `verdicts.json` before judging).
>
> Output a JSON object: `{ "verdict": "pass" | "fail", "rationale": "...",
> "concerns": ["..."] }`.

### `judge.sh` — shipped by the harness

`judge.sh` is shipped by the harness in `agent_factory/templates/` and
copied into the repo on init. It is invoked by the agent — when, is
decided by the user's `GOAL.md`, which mentions `judge.sh` explicitly
where appropriate.

`judge.sh`:

1. Reads `JUDGE.md` from the repo root.
2. Receives via env vars:
   - `JUDGE_GIT_HASH` — the commit the agent wants judged.
   - `JUDGE_INPUT_FILE` — path to an agent-written summary of what
     changed and why.
   - `JUDGE_OUTPUT_FILE` — where the verdict JSON is written.
   - `JUDGE_CONTEXT` — newline-separated list of paths within the repo
     the judge should examine (corpora, fixtures, reference material).
     The agent populates this based on what the change touches and what
     `JUDGE.md` says it cares about. The judge does not know the
     project layout otherwise.
3. Spawns a fresh `claude` subprocess with `JUDGE.md` + the diff at
   `JUDGE_GIT_HASH` + the agent's summary + the paths in
   `JUDGE_CONTEXT` + the current `verdicts.json`. No inherited context
   from the calling agent.
4. Writes the verdict JSON to `JUDGE_OUTPUT_FILE`.
5. Exits 0 on `"verdict": "pass"`, non-zero on `"fail"`.

### Why the judge is a separate subprocess

The judge must not share the agent's context window — otherwise it will
rationalize alongside the agent. A fresh `claude` invocation gives us
isolation for free.

### Worked example: agent invokes the judge

This is what one judge round-trip looks like in the COBOL case. The
agent has just committed a parser change and wants it judged before
pushing to `main`.

**1. Agent writes a summary of what it tried to do.**

`/tmp/agent_summary_a1b2c3d.md`:

```markdown
## Intent
Extract included copybook names from COPY statements so we can build
a dependency graph between .cbl programs and their .cpy includes.

## What I changed
- Added `src/cobol/copy_parser.py`
- New regex `^\s*COPY\s+([A-Z0-9-]+)\s*\.` matched line-by-line
- Wired into the existing relationship walker at
  `src/cobol/walker.py:122`

## How I tested
- Ran the parser over the example corpus
- All 47 COPY statements in the corpus matched
- Spot-checked 5 against the expected dependency graph

## Why I think this is right
The COPY syntax in the corpus is consistent. The regex handles the
forms I observed.

## Risk I'm uncertain about
I assumed COPY statements are single-line. The corpus didn't have
counter-examples but I haven't checked the spec.
```

**2. Agent invokes `judge.sh` with context.**

```bash
JUDGE_GIT_HASH=a1b2c3d \
JUDGE_INPUT_FILE=/tmp/agent_summary_a1b2c3d.md \
JUDGE_OUTPUT_FILE=/tmp/verdict_a1b2c3d.json \
JUDGE_CONTEXT=$'examples/sample_cobol/\nsrc/cobol/copy_parser.py\nsrc/cobol/walker.py' \
  ./judge.sh
```

The agent chose what to put in `JUDGE_CONTEXT` based on what the
change touched (`copy_parser.py`, `walker.py`) and what `JUDGE.md`
says it cares about (the corpus path, so the judge can check for
overfitting).

**3. `judge.sh` spawns a fresh `claude` subprocess.**

The subprocess has no shared state with the calling agent — new
process, new conversation. It receives a prompt assembled from:

- The contents of `JUDGE.md`
- `git show a1b2c3d` (the diff being judged)
- The agent's summary from `JUDGE_INPUT_FILE`
- The files/directories listed in `JUDGE_CONTEXT`
- The current `verdicts.json`

The subprocess is instructed to write a single JSON object to
`JUDGE_OUTPUT_FILE` and exit.

**4. Judge writes a verdict.**

`/tmp/verdict_a1b2c3d.json`:

```json
{
  "verdict": "fail",
  "rationale": "The regex assumes COPY statements are single-line. The IBM Enterprise COBOL Reference §6.2 documents line continuation via column 7 = '-'. The sample corpus happens to have no multi-line COPY statements, so the test pass rate is misleading. This is overfitting to the corpus, which JUDGE.md explicitly forbids.",
  "concerns": [
    "Single-line assumption not traceable to a spec",
    "Test corpus does not exercise line continuation",
    "verdicts.json has no prior entry on this pattern; first occurrence"
  ]
}
```

`judge.sh` exits non-zero because `verdict == "fail"`.

**5. Agent reads the verdict and handles it.**

The agent does not push `a1b2c3d` to `main`. It:

- Reads `verdict_a1b2c3d.json`
- Reads `verdicts.json`, finds max ID, picks `v-0007`
- Appends a new entry (see Goal 4 for the full schema) with `intent`
  from its own summary and `judge_rationale` from the verdict
- Pushes `a1b2c3d` to `refs/bad-attempts/v-0007-cobol-copy-singleline`
- Resets `main` to the parent
- Starts a new attempt with the lesson in hand

### Acceptance for Goal 3

- A working COBOL example under `test/cobol-relationships/` with a
  user-written `GOAL.md` (that explicitly mentions `judge.sh`), a
  user-written `JUDGE.md`, and a small COBOL corpus.
- An end-to-end run on the COBOL example shows agents invoking
  `judge.sh`, getting "fail" verdicts at least sometimes, and iterating.

---

## Goal 4 — `verdicts.json`: Lessons From Bad Judgement

Every "fail" verdict from `judge.sh` is captured in `verdicts.json` in
the repo root. This file is the harness's institutional memory: it
teaches future agents what mistakes to avoid.

### Schema

```json
{
  "version": 1,
  "verdicts": [
    {
      "id": "v-0001",
      "timestamp": "2026-01-15T14:22:09Z",
      "agent_id": "agent-3",
      "git_hash": "a1b2c3d",
      "git_hash_parent": "f0e1d2c",
      "intent": "Added regex-based parser for COBOL COPY statements to extract included copybook names.",
      "what_went_wrong": "Regex assumed COPY statements always end on the same line. COBOL allows continuation across lines using the '-' indicator in column 7. The parser silently dropped multi-line COPY statements.",
      "judge_rationale": "Assumption about single-line COPY is not traceable to any COBOL spec. The IBM Enterprise COBOL Reference §6.2 documents line continuation. The change overfit to the sample corpus.",
      "lesson": "When parsing COBOL syntax, always check for line continuation (column 7 = '-') before assuming a statement is single-line. Cite a spec section in the commit message for any syntactic assumption.",
      "tags": ["cobol", "parser", "overfitting", "specification-traceability"]
    }
  ]
}
```

### How verdicts get written

- The agent writes the entry — it has the full intent context. The
  judge's output JSON sources the `judge_rationale` field.
- The agent commits the updated `verdicts.json` in the commit series
  that revises the bad change.
- IDs are monotonically increasing (`v-0001`, `v-0002`, ...). Agents
  read the existing file, find max ID, increment. Concurrent writes
  resolve on rebase like any other file.

### How verdicts get read

- At session start, every agent reads `verdicts.json` (the user's
  `GOAL.md` instructs this when judgement gating is in use).
- The judge is given `verdicts.json` on every call, so a repeat
  mistake is caught faster the second time.

### Preserving the bad commit

When a verdict fails, keep the failed work for forensics. The agent:

1. Notes the failing commit hash in the verdict entry.
2. Pushes the failing commit to a `bad-attempts/` ref
   (`refs/bad-attempts/v-0001-cobol-copy-singleline`) instead of `main`.
3. Resets `main` to the parent and starts over with the lesson in hand.

### Acceptance for Goal 4

- `verdicts.py` provides `read()`, `append(entry)`, `next_id()`, and
  rebase-friendly conflict handling.
- The COBOL example, run long enough, accumulates verdicts a human
  reviewer would call sensible.
- A later agent picking up the same example demonstrably changes
  behaviour based on prior verdicts (references them in commit
  messages or task locks).

---

## Order of Operations

1. **Goal 1**: rip out the Rust and C compiler content. Get the harness
   running on a generic user-supplied `GOAL.md`.
2. **Goal 2**: port the host scripts to Python.
3. **Goals 3 and 4 together**: judge contract and verdicts schema are
   coupled. Build the COBOL example as the driving use case.
