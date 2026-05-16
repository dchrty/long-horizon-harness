# Goal: a simple, well-tested prime sieve

You are one of several parallel agents working in this shared repo on a
small but real software task. Your collective objective:

> Implement a prime number sieve in Python, with tests, that can list
> all primes up to N for any reasonable N. The implementation should be
> correct, reasonably efficient, and have decent test coverage.

This project exists primarily to exercise the agent-factory harness on a
small, deterministic task. Keep it small. Don't add web servers,
databases, or other scope creep.

## Build / test

There is no toolchain to install — agents run Python 3 directly. To test
your code:

```bash
python3 -m pytest -q
```

## Coordination protocol

Multiple agents are working in parallel on this repo. Use a task lock
file to claim work:

1. Pick a piece of work (see "Where to start" below).
2. Create `current_tasks/<descriptive_name>.txt` with a one-line summary
   and the date as `Started: YYYY-MM-DD`.
3. `git add current_tasks/... && git commit -m "Lock: <name>" && git pull --rebase && git push`.
   If push fails, another agent claimed it; pick something else.
4. Do the work. Push intermediate commits frequently.
5. When done, `git rm current_tasks/<descriptive_name>.txt && git commit
   -m "Remove lock: <name> (done)" && git pull --rebase && git push`.

If you see a lock older than 2 hours (check the `Started:` date), the
owner crashed — you may remove it.

## Where to start

- If there is no `sieve.py` yet: implement one. Start with the
  Sieve of Eratosthenes; sensible function signature `primes_up_to(n)
  -> list[int]`.
- If `sieve.py` exists but there are no tests: add `test_sieve.py`
  exercising small cases, edge cases (`n=0, 1, 2`), and a known result
  (e.g. primes up to 100).
- If tests pass: extend with a segmented sieve for large N, or a
  benchmark, or property-based tests. Don't break existing tests.

## Rules

- One logical change per commit. Always run the tests before pushing.
- Don't add dependencies beyond the Python standard library + pytest.
- Update `README.md` (create one if absent) as the project evolves.
- This GOAL.md is the source of truth. If you find it ambiguous, prefer
  the smaller scope.
