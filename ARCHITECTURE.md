# Architecture

How the harness is laid out and why. Companion to `AGENTS.md`
(concepts) and `README.md` (user-facing).

## Module layout

```
agent_factory/
  cli.py             # click CLI: init, run, status, analytics, stop
  config.py          # ProjectLayout: discovers GOAL.md, JUDGE.md;
                     # exposes SEED_SKIP_TOP_LEVEL skip list.
  repo.py            # bare-repo init; snapshots the project dir into
                     # the initial commit; subprocess wrappers for git.
  docker_runner.py   # image build, container launch/stop, status queries.
  status.py          # repo + container snapshot, renderer.
  analytics.py       # walk commits, emit CSV / optional matplotlib PNG.
  judge.py           # validators for the verdict JSON shape.
  verdicts.py        # read / append / next_id / reconcile_after_rebase.
  templates/
    Dockerfile       # ubuntu:22.04 + node + claude code + python
    entrypoint.sh    # in-container infinite agent loop (bash, by design)
    judge.sh         # in-container fresh-claude judge subprocess (bash)
    verdicts.empty.json
examples/
  sieve/             # minimal: just a GOAL.md (Python prime sieve)
  cobol-relationships/   # full example: GOAL.md + JUDGE.md + corpus/
tests/               # pytest unit tests; Docker mocked
```

## Process model

For a `run` invocation:

1. **CLI (host, Python)** — `agent_factory.cli` parses args, discovers
   the project layout, builds the Docker image, calls `repo.init_upstream`
   (idempotent against existing `upstream.git`), then `docker_runner.launch_agents`.
2. **Per-agent container (Docker, bash entrypoint)** — each agent runs
   `templates/entrypoint.sh` in a loop:
   - Fresh `git clone /upstream → /workspace/code` per iteration.
   - First-mover stale-lock cleanup (`current_tasks/*.txt`).
   - Spawn `claude --dangerously-skip-permissions -p '...' --model …`,
     which reads `GOAL.md` from the repo root and starts work.
   - On `SIGTERM`: trap commits uncommitted work and pushes before exit
     (`docker stop -t 30`).
3. **Optional judge subprocess** — when an agent invokes `./judge.sh`,
   it spawns a *fresh* `claude` (no inherited context) inside the same
   container. The judge reads `JUDGE.md` + the diff + agent summary +
   listed paths + `verdicts.json`, writes a verdict JSON, and exits 0
   (pass) or non-zero (fail).
4. **Host monitor loop** — every 5 minutes, prints a status line; at
   duration, calls `docker_runner.stop_agents` (graceful SIGTERM with
   30s save grace).

The host's `~/.claude/` is bind-mounted read-only into each container
at `/home/agent/.claude`, so the in-container `claude` uses the host's
existing login. No API key flows through the harness.

## Conventions that aren't obvious

- **`entrypoint.sh` stays bash on purpose.** It runs inside the
  container alongside the `claude` CLI; porting it to Python adds no
  value and inflates the image. Everything *outside* the container is
  Python.
- **`judge.sh` is seeded into the user's repo, not baked into the
  image.** Users can commit edits to their judge prompt without
  rebuilding the image.
- **Each project gets a unique container/image prefix** derived from
  the project directory's basename, so multiple worktrees on the same
  host don't collide.
- **Snapshot, not clone.** `init` reads the project dir's files and
  commits them; it does not inherit the user's git history. The skip
  list (`SEED_SKIP_TOP_LEVEL` in `config.py`) keeps harness state and
  common dev clutter out of the initial commit.
- **Force-pushed history is normal** in the user's `upstream.git` when
  a judge "fail" sends a commit to `refs/bad-attempts/v-NNNN-<slug>`
  and resets `main` to the parent. Agents are expected to do this; the
  harness does not enforce it.

## Stable vs. less-stable contracts

**Stable** (changing these breaks user repos):

- The on-disk contract: project dir contains `GOAL.md`; optional `JUDGE.md`.
- The verdict JSON shape: `{verdict, rationale, concerns}`.
- The `verdicts.json` schema (versioned; bumping requires a migration).
- The judge env-var protocol: `JUDGE_GIT_HASH`, `JUDGE_INPUT_FILE`,
  `JUDGE_OUTPUT_FILE`, `JUDGE_CONTEXT`.

**Less stable** (move freely):

- CLI flags beyond the positional `run NUM_AGENTS DURATION`.
- Internal module boundaries inside `agent_factory/`.
- Prompt text inside `entrypoint.sh` and `judge.sh`.
- The Dockerfile contents.
- The skip list in `SEED_SKIP_TOP_LEVEL`.

## In-container layout

Each running container has:

```
/upstream             # bind-mount of host upstream.git (rw)
/home/agent/.claude   # bind-mount of host ~/.claude (ro) — auth
/workspace/agent_logs # bind-mount of host log dir (rw)
/workspace/code       # ephemeral: fresh clone of /upstream each iteration
```

When the agent commits and pushes, it pushes to `/upstream` directly
over the local filesystem — no network involved.
