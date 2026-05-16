# Prime Sieve Agent Instructions

You are an autonomous agent working on `sieve`, a small Python library
that exposes `primes_up_to(n: int) -> list[int]` returning every prime
≤ N. The repo is located at `/workspace/code/`.

You are one of many parallel agents working on the same codebase
simultaneously. Other agents may be pushing changes while you work. You
must coordinate using the task locking protocol described below.

Your goal: deliver a correct, well-tested prime sieve, fast enough to
handle reasonably large N. Start with a clean Sieve of Eratosthenes,
add edge-case coverage, then segmented or property-based variants once
the basics are solid. Break work into small, focused changes and keep
going until you run out of things to do.

This project exercises the harness on a small, deterministic task —
keep scope tight. Don't add web servers, databases, async, or other
creep. Stdlib + pytest only.

## First Steps (Every Session)

1. Read this `GOAL.md` to refresh context.
2. Read `README.md` if it exists (one may have been created by an
   earlier agent).
3. List `current_tasks/` to see what other agents are currently
   working on. Don't pick something already claimed.
4. Run `python3 -m pytest -q` to see current pass rate.
5. If `sieve.py` doesn't exist yet, creating it is the next task.

If tests are failing on `main`, fixing them is your top priority.

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

After your change is working and tested:

1. Delete the lock file.
2. Commit everything together:
   ```
   git rm current_tasks/<task_name>.txt
   git add -A
   git commit -m "<concise description> (closes <task_name>)

   <what changed, test results>"
   git pull --rebase
   git push
   ```

### Pushing Work In Progress

For longer tasks, push intermediate progress frequently:

```
git add -A
git commit -m "<incremental change description>"
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
2. **No `sieve.py` yet**: write a clean Sieve of Eratosthenes with
   signature `primes_up_to(n: int) -> list[int]`.
3. **No tests yet**: add `test_sieve.py` covering small cases, edge
   cases (`n = 0, 1, 2`), and a known reference (primes up to 100).
4. **Missing edge cases**: negative inputs, very small `n`,
   `n = 10**6` as a stress check.
5. **Performance**: profile `n = 10**7`; consider bit-array tricks,
   wheel factorisation, or a segmented sieve. No numpy.
6. **Variants**: property-based tests hand-rolled in stdlib (no
   `hypothesis` dep), or a generator API alongside the list one.
7. **Docs**: keep `README.md` in sync as the public API grows.

Avoid duplicating another agent's work. Check `current_tasks/` before
committing to a task.

## Testing

Single tier — there is no test farm to babysit:

```
python3 -m pytest -q
```

Always run before pushing. Include the result in your commit message:

```
17/17 passing (added segmented sieve for n > 1e6, ~3x faster)
```

If you add a new test file, name it in the commit message so reviewers
can find it quickly.

## Git Workflow

Push frequently. Other agents are working in parallel.

```
git add -A
git commit -m "<concise description>

<detailed explanation if needed>
<test results>"
git pull --rebase
git push
```

If you hit a merge conflict during rebase:

- Read both sides of the conflict carefully.
- Integrate both changes rather than picking a side.
- `git add <resolved files> && git rebase --continue`, then push.

## Documentation

- Keep `README.md` updated as the public API evolves (create one if
  none exists).
- A short docstring on every public function is enough; no need for
  separate API docs.

## Important Rules

- **One logical change per commit.** Don't bundle unrelated fixes.
- **Test before pushing.** Never push code that breaks the suite.
- **Detailed commit messages.** Include what you changed, why, and
  test results.
- **No new dependencies.** Stdlib + pytest only.
- **Document dead ends.** If an approach didn't work, put a note in
  the next task lock so the next agent doesn't repeat it.
- **Push often.** Don't accumulate large unpushed changes.
- **Keep going.** When you finish one task, pick up the next.
