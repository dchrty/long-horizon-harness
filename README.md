# agent-factory — long-horizon harness

A generalised, async, multi-agent harness for long-running software
tasks. Spawns N parallel Claude Code agents in Docker containers,
coordinating through a shared bare git repo. Each run is driven by a
user-supplied `GOAL.md` — the harness has no opinion about what you're
building.

This is a **Python rewrite and generalisation** of
[`vizopsai/async_compiler_factory`](https://github.com/vizopsai/async_compiler_factory),
the bash scaffolding that reproduces Anthropic's
[Building a C Compiler with Claude Agent Teams](https://www.anthropic.com/engineering/building-c-compiler)
experiment. Where the original was hard-coded to "build a C compiler"
and orchestrated by shell scripts, this version:

- Replaces the bash orchestration (`run.sh`, `init_repo.sh`,
  `launch.sh`, `status.sh`, `analytics.sh`) with a Python package
  (`agent_factory/`) and a single `agent-factory` CLI.
- Drops every C-compiler assumption. Drive any goal-directed task by
  writing a `GOAL.md`.
- Adds **judgement gating**: an optional `JUDGE.md` + `judge.sh` that
  spawns a fresh `claude` subprocess to evaluate non-deterministic work
  (research, parsing, schema extraction — anything without a clean
  oracle).
- Adds **`verdicts.json`** as institutional memory: every "fail"
  verdict is captured so future agents start with their predecessors'
  lessons in hand.
- Uses your host Claude Code login (Max / Pro / OAuth) by bind-mounting
  `~/.claude/` into each agent, so no separate `ANTHROPIC_API_KEY` is
  needed.

Source: <https://github.com/dchrty/long-horizon-harness>.

## Quick start — using the harness

You have a directory somewhere on disk with a `GOAL.md` you wrote, and
you want agents to work on it.

```bash
# 1. Install uv if you don't have it
#    https://docs.astral.sh/uv/getting-started/installation/

# 2. Install agent-factory as a global tool from a clone of this repo
git clone https://github.com/dchrty/long-horizon-harness.git long-horizon-harness
cd long-horizon-harness
uv tool install .            # `agent-factory` is now on your PATH globally

# 3. Make sure your host Claude Code is logged in
#    The agents will use whichever account `claude` on your machine uses
#    (Max plan, Pro, OAuth, or an API key already saved in ~/.claude/).
#    No ANTHROPIC_API_KEY env var needed.
claude --version             # sanity check
# If you've never logged in:  claude   (run once, follow the prompts)

# 4. Go to your own project, anywhere on disk
cd ~/path/to/my-project      # must contain a GOAL.md you wrote

agent-factory init           # creates ./upstream.git, seeds GOAL.md (+ JUDGE.md, seed/)

# Same shape as the original ./run.sh — positional N_AGENTS DURATION_MIN
agent-factory run 1 10       # 1 agent, 10 min  (test run, ~$5-15)
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

### How the agents authenticate

Each agent container bind-mounts your host `~/.claude/` directory
read-only at `/home/agent/.claude`, so the in-container `claude`
inherits your login. Whatever account/plan you use for `claude` on the
host is the same one your N parallel agents use — no separate API key
required. Override the source path with `--claude-config /path/to/dir`
if you keep claude config somewhere non-default.

> **Tradeoff:** mounting your claude credentials into the container
> means an agent that goes off-script could read them. The filesystem
> sandbox is intact (containers can't reach your other host files), but
> if that exposure isn't acceptable for your account, run inside a
> throwaway VM or use an API-key-only sub-account.

To upgrade later: `cd long-horizon-harness && git pull && uv tool install . --reinstall`.

## The contract

The user supplies a directory containing at least:

- `GOAL.md` — the instruction file copied into the initial commit of
  the shared repo. Tells the agents what to build, how to coordinate,
  how to test, and (optionally) when to invoke the judge.

Optional:

- `JUDGE.md` — enables judgement gating (Goal 3 below). If present,
  the harness also seeds `judge.sh` and an empty `verdicts.json`.
- `seed/` — a directory whose contents are copied into the initial
  commit. Use this for example corpora, starter source, fixtures.

That's the whole contract on the user's side. The harness does not parse
or template `GOAL.md`.

## What's in the repo at agent runtime

After `init`, the shared bare repo (`upstream.git`) and every agent's
working copy contains:

```
GOAL.md                # your instruction file (required)
JUDGE.md               # if you supplied one
judge.sh               # if JUDGE.md is present — fresh-context judge
verdicts.json          # if JUDGE.md is present — institutional memory
current_tasks/         # lock-file dir for agent coordination
<seed contents...>     # whatever was in your project's seed/
```

## CLI verbs

- `agent-factory init` — create `upstream.git` and seed it.
- `agent-factory run` — build image (unless `--no-build`), launch agents,
  monitor every 5 minutes, then stop with SIGTERM (graceful save).
- `agent-factory status [--short]` — running agents, repo state,
  file-count breakdown by extension, active task locks, live agent work.
- `agent-factory analytics [--csv path] [--plot path]` — walk every
  commit, emit a CSV table of files/lines over time. PNG plot requires
  the `[plot]` extra.
- `agent-factory stop` — SIGTERM all agents for this project (each
  agent traps and pushes uncommitted work before exiting).

All verbs accept `--project DIR` (defaults to cwd) and `-v` for debug
logging.

## Judgement gating (optional)

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

`examples/` ships small projects exercising the harness end-to-end:

- `examples/sieve/` — minimal: a Python prime sieve. Just a `GOAL.md`;
  proves the harness works on something that isn't a C compiler.
- `examples/cobol-relationships/` — full example with `GOAL.md`,
  `JUDGE.md`, and a small COBOL corpus under `seed/`. Exercises the
  judge contract and `verdicts.json`.

To run the sieve example:

```bash
uv run agent-factory init  --project examples/sieve
uv run agent-factory run 2 30  --project examples/sieve
```

## Architecture

```
agent_factory/
  cli.py            # click-based entrypoint (`agent-factory ...`)
  config.py         # ProjectLayout: discovers GOAL.md, JUDGE.md, seed/
  repo.py           # bare-repo init + seed; subprocess wrappers for git
  docker_runner.py  # image build, container launch/stop, status
  status.py         # repo + container snapshot, renderer
  analytics.py      # walk commits, emit CSV / optional matplotlib PNG
  judge.py          # validators for the judge protocol
  verdicts.py       # read / append / next_id / reconcile
  templates/
    Dockerfile      # ubuntu:22.04 + node + claude code + python
    entrypoint.sh   # in-container infinite agent loop (bash, by design)
    judge.sh        # in-container fresh-claude judge subprocess (bash)
    verdicts.empty.json
```

`entrypoint.sh` stays bash deliberately — it runs inside the container
calling the `claude` CLI; porting it to Python would add no value and
inflate the image.

## Quick start — building & contributing

You want to change the harness itself (the `agent_factory/` package, the
templates, the docs).

```bash
git clone https://github.com/dchrty/long-horizon-harness.git long-horizon-harness
cd long-horizon-harness

uv sync --group dev          # creates .venv, installs runtime + dev deps from uv.lock

uv run pytest -q             # 40 unit tests, ~4s, Docker mocked
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

## Notes / design

- Each agent runs in its own container with
  `claude --dangerously-skip-permissions`. The Docker sandbox is the
  reason this is safe.
- Agents push frequently. The host's `upstream.git` is the only durable
  artifact. Delete it to start a run fresh; keep it to resume.
- SIGTERM (`docker stop`) is graceful: the in-container trap commits and
  pushes uncommitted work before exiting. The host gives 30 seconds for
  this to complete.
- The harness has no opinion on testing, building, or task structure.
  That all lives in `GOAL.md`.
