# cobol_rels

A deterministic tool that walks a directory of COBOL source and emits a
dependency graph: which programs CALL which, which programs COPY which
copybooks. Output is JSON, designed to be consumed by other tooling.

This repo is currently empty — agents will build it according to
`GOAL.md`. See `JUDGE.md` for the correctness criteria that gate
parser changes.

## Example corpus

`examples/sample_cobol/` contains a small set of COBOL files:

- `PROGA.cbl` → CALLs PROGB, COPYs FOO
- `PROGB.cbl` → CALLs PROGC, COPYs BAR
- `PROGC.cbl` → COPYs BAR
- `FOO.cpy`, `BAR.cpy` — record layouts

This corpus is for **sanity** only. It is narrow and biased. Do not
treat it as a correctness oracle. See `JUDGE.md` for what real
generalisation looks like.
