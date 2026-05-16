# AGENTS.md

Notes for agents (and humans) working **on** this repo. For end-user
docs — installing, running on your own project — see `README.md`. For
the module layout and process model, see [`ARCHITECTURE.md`](ARCHITECTURE.md).

## What this is

A general-purpose async harness for long-horizon, goal-directed software
tasks. Spawns N parallel Claude Code agents in Docker containers,
coordinating through a shared git repo (`upstream.git`). Each run
is driven by a user-supplied `GOAL.md`; the harness itself has no
opinion about what's being built.

Lineage: Python rewrite and generalisation of
[`vizopsai/async_compiler_factory`](https://github.com/vizopsai/async_compiler_factory),
the bash scaffolding that reproduces Anthropic's
[Building a C Compiler with Claude Agent Teams](https://www.anthropic.com/engineering/building-c-compiler)
experiment. This version drives any task and adds judgement gating +
institutional memory for tasks without a deterministic oracle.

## Core abstractions

| File / dir          | Owner    | Role                                                                |
| ------------------- | -------- | ------------------------------------------------------------------- |
| `GOAL.md`           | user     | What the agents are working on. In the project dir, seeded as-is.   |
| `JUDGE.md`          | user     | Optional. Criteria a judge subprocess evaluates a commit against.   |
| `judge.sh`          | harness  | Seeded if `JUDGE.md` exists. Spawns a fresh `claude` for judgement. |
| `verdicts.json`     | harness  | Seeded if `JUDGE.md` exists. Append-only log of failed verdicts.    |
| `current_tasks/`    | agents   | Lock files for in-flight work. Stale locks cleared each run.        |
| `upstream.git`      | harness  | Bare git repo every agent mounts and pushes into.                   |

Beyond `GOAL.md` and `JUDGE.md`, the user's project directory is just a
directory — everything in it gets snapshotted into the initial commit,
modulo the skip list of harness state and dev clutter. There is no
separate "seed" concept.

The harness is unopinionated about:

- **Build tooling** — agents `apt-get install` whatever they need.
- **Testing** — the test command lives in `GOAL.md`, not the harness.
- **Coordination protocol** — `current_tasks/` is a convention `GOAL.md`
  can opt into; it's not enforced.
- **What "done" looks like** — that's `GOAL.md`'s problem (and, for
  judgement-gated tasks, `JUDGE.md`'s).

## Why a judge subprocess

For tasks where there's no fixed oracle (parsers over messy real-world
inputs, research synthesis, design proposals), a separate `claude`
subprocess evaluates the agent's commit. It runs with **no inherited
context** from the calling agent, so it can't rationalise alongside
whoever wrote the code. Every "fail" verdict is appended to
`verdicts.json`, which is read at every session start — so a repeat
mistake gets caught faster the second time.

## Working in this repo

The project uses `uv` for env + lockfile, `ruff` for lint + format,
`pytest` for tests:

```bash
uv sync --group dev
uv run pytest -q          # 41 tests, ~4s, Docker mocked
uv run ruff check .
uv run ruff format .
uv run agent-factory --help
```

Update dependencies: edit `pyproject.toml`, then `uv lock`. Commit
`uv.lock`.

## When working as an agent on this repo

- Trust the existing test suite. Run it on every change.
- Don't introduce a goal-specific assumption back into the harness —
  the whole point is generality. If something feels goal-specific, it
  belongs in `GOAL.md` or `examples/`, not in `agent_factory/`.
- The `examples/` projects are smoke tests, not unit tests. Don't
  break them, but don't treat them as the spec either.
- When in doubt about scope, prefer "less in the harness, more in
  `GOAL.md`."
- See [`ARCHITECTURE.md`](ARCHITECTURE.md) before changing how the
  harness invokes containers, where things get bind-mounted, or how
  the in-container loop and judge interact.
