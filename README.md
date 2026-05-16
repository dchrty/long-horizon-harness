# agent-factory — long-horizon harness

A generalised, async, multi-agent harness for long-running software
tasks. Spawns N parallel Claude Code agents in Docker containers,
coordinating through a shared git repo.

**Extends and generalises** Anthropic's
[Building a C Compiler with Claude Agent Teams](https://www.anthropic.com/engineering/building-c-compiler)
experiment, built on the bash scaffolding at
[`vizopsai/async_compiler_factory`](https://github.com/vizopsai/async_compiler_factory).

Long-running agent systems traditionally work under constraints that
require a known-good implementation and a deterministic test suite —
the C compiler experiment is the canonical example, where every change
is validated against a passing test suite. But many real tasks have no
such oracle: parsing messy real-world inputs (COBOL, legacy log
formats), research synthesis, design proposals, schema extraction. For
those, you need *agentic judgement* in the loop. This harness supports
both modes.

Two files drive a run:

- **`GOAL.md`** — what you want the agents to do: the task, the
  build/test commands, the coordination protocol. You write it; the
  harness doesn't parse it.
- **`JUDGE.md`** *(optional)* — for tasks with no fixed oracle, the
  criteria a separate `claude` subprocess uses to evaluate each commit
  before it lands. `GOAL.md` tells agents *what to build* and *when to
  ask for judgement*; `JUDGE.md` tells the judge *what to look for*.
  Every "fail" verdict is captured in `verdicts.json` so future agents
  start with their predecessors' lessons in hand.

Authentication runs through the **Claude Code CLI** on your host
(Max / Pro / OAuth) — no `ANTHROPIC_API_KEY` required. API-key auth may
return as an option in a future version.

## Prerequisites

- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** —
  Python env + lockfile manager. Used to install the harness and run
  tests.
- **[Docker](https://www.docker.com/products/docker-desktop/)** —
  each agent runs in its own container. Docker Desktop on macOS /
  Windows, the daemon on Linux.
- **[Claude Code CLI](https://docs.claude.com/en/docs/claude-code/setup)**
  installed and logged in on the host. The agents inherit this login
  by bind-mounting `~/.claude/` read-only into each container — no
  `ANTHROPIC_API_KEY` is required. Verify with `claude --version`.

## Quick start — using the harness

You have a directory somewhere on disk with a `GOAL.md` you wrote, and
you want agents to work on it. See `examples/` for templates.

```bash
# Install the CLI globally from a clone of this repo
git clone https://github.com/dchrty/long-horizon-harness.git
cd long-horizon-harness
uv tool install .            # `agent-factory` is now on your PATH

# Go to your own project, anywhere on disk
cd ~/path/to/my-project      # must contain a GOAL.md you wrote

agent-factory init           # snapshots project dir into ./upstream.git

# Positional: NUM_AGENTS DURATION_MIN
agent-factory run 1 10       # 1 agent, 10 min  (test run)
agent-factory run 2 60       # 2 agents, 1 hour
agent-factory run 4 120      # 4 agents, 2 hours

agent-factory status         # full snapshot: commits, file stats, live agent work
agent-factory status --short # commit count + lines only
agent-factory stop           # SIGTERM all agents (graceful: they push WIP before exit)
agent-factory analytics --csv timeseries.csv
```

All commands accept `--project DIR` if you'd rather invoke them from
elsewhere instead of `cd`-ing in.

`agent-factory run` builds the Docker image, initialises the repo
(if `upstream.git` doesn't already exist), launches agents, prints
progress every 5 minutes, and stops when time is up. All state lives
in `upstream.git/` inside the project directory — delete it to start
fresh, keep it to resume.

Each agent container bind-mounts your host `~/.claude/` read-only at
`/home/agent/.claude`, so the in-container `claude` inherits your login.
Override the source path with `--claude-config /path/to/dir` if you
keep claude config somewhere non-default.

> **Tradeoff:** mounting claude credentials into the container means an
> agent that goes off-script could read them. The filesystem sandbox is
> intact (containers can't reach your other host files), but if that
> exposure isn't acceptable for your account, run inside a throwaway VM
> or use an API-key-only sub-account.

To upgrade later: `cd long-horizon-harness && git pull && uv tool install . --reinstall`.

## Building & contributing

```bash
git clone https://github.com/dchrty/long-horizon-harness.git
cd long-horizon-harness

uv sync --group dev          # creates .venv, installs runtime + dev deps from uv.lock

uv run pytest -q             # 41 unit tests, ~4s, Docker mocked
uv run ruff check .          # lint
uv run ruff format .         # format
uv run agent-factory --help  # exercise the CLI without installing globally
```

`uv run <cmd>` executes inside the project's `.venv` without needing
you to activate it. If you prefer, `uv venv` + `source .venv/bin/activate`
(or the Windows equivalent) works the same way.

Lint config lives in `[tool.ruff]` in `pyproject.toml` (rules:
E/W/F/I/B/UP/SIM/RUF, line length 100). Unit tests live in `tests/` and
mock Docker; integration smoke runs use `examples/sieve` or
`examples/cobol-relationships` against a real Docker daemon.

Updating dependencies: edit `pyproject.toml`, then `uv lock` to
regenerate `uv.lock`. Use `uv lock --upgrade` to bump every dep to its
latest matching version. Commit `uv.lock` so everyone resolves the same
versions.

## More on judgement gating

Use this when your task is non-deterministic: there is no known-good
output, no fixed oracle, no diff-against-expected to assert correctness.
The driving examples are things like research summarisation, schema or
relationship extraction over messy real-world inputs, design proposals,
or any task where "did this work?" is itself a judgement call. Instead
of writing a test harness that can't actually decide, you let an agent
evaluate the output.

Drop a `JUDGE.md` next to your `GOAL.md`. The harness ships a
`judge.sh` that spawns a **fresh** `claude` subprocess — no inherited
context from the agent that produced the work, so the judge cannot
rationalise alongside the author. Your `GOAL.md` decides when agents
invoke it (typically: before pushing risky changes to `main`).

The judge writes a verdict JSON:

```json
{ "verdict": "pass" | "fail", "rationale": "...", "concerns": [ "..." ] }
```

…and exits 0 for pass, non-zero for fail.

On a `fail`, your `GOAL.md` should instruct agents to append the
failure to `verdicts.json` (the institutional memory) and push the
failing commit to `refs/bad-attempts/v-NNNN-<slug>` for forensics
before retrying.

`agent_factory.verdicts` provides helpers (`read`, `append`, `next_id`,
`reconcile_after_rebase`) for the host; agents in-container can shell
out to git or use the same module if installed.

## Example projects

`examples/` ships small projects you can use as templates. Read them
before writing your own `GOAL.md` / `JUDGE.md` — they're the best
reference for what the harness expects.

- **[`examples/sieve/GOAL.md`](examples/sieve/GOAL.md)** — minimal
  template. Just a `GOAL.md` (no judge), task is a Python prime sieve.
  Shows the basic shape: what to build, how to test, the lock-file
  coordination protocol.
- **[`examples/cobol-relationships/`](examples/cobol-relationships/)** —
  full judgement-gated example. Has `GOAL.md` (calls out when to invoke
  the judge), `JUDGE.md` (overfitting + spec-traceability +
  verdict-regression checks), and a small COBOL corpus under `corpus/`.

Try the sieve example:

```bash
uv run agent-factory init       --project examples/sieve
uv run agent-factory run 2 30   --project examples/sieve
```
