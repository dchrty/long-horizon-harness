"""verdicts.json — institutional memory of judge "fail" decisions.

Schema:
    {
        "version": 1,
        "verdicts": [
            {
                "id": "v-0001",
                "timestamp": "2026-01-15T14:22:09Z",
                "agent_id": "...",
                "git_hash": "...",
                "git_hash_parent": "...",
                "intent": "...",
                "what_went_wrong": "...",
                "judge_rationale": "...",
                "lesson": "...",
                "tags": [ ... ]
            }
        ]
    }

These helpers run on the host (and could also be invoked from inside the
container by an agent that imports the module). Concurrent writes are
handled by the agent's normal git rebase cycle — verdicts.json is just a
file, and `id` ordering survives rebase because IDs are picked at write
time relative to the file's current state.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1


@dataclass
class Verdict:
    id: str
    timestamp: str
    agent_id: str
    git_hash: str
    git_hash_parent: str
    intent: str
    what_went_wrong: str
    judge_rationale: str
    lesson: str
    tags: list[str] = field(default_factory=list)


class VerdictsError(RuntimeError):
    pass


def read(path: Path) -> dict:
    """Read verdicts.json; return {version, verdicts} (empty if missing)."""
    if not path.is_file():
        return {"version": SCHEMA_VERSION, "verdicts": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise VerdictsError(f"{path}: malformed JSON: {e}") from e

    if not isinstance(data, dict) or "verdicts" not in data:
        raise VerdictsError(f"{path}: missing 'verdicts' array")
    if data.get("version") != SCHEMA_VERSION:
        raise VerdictsError(
            f"{path}: unsupported schema version {data.get('version')!r} "
            f"(expected {SCHEMA_VERSION})"
        )
    if not isinstance(data["verdicts"], list):
        raise VerdictsError(f"{path}: 'verdicts' must be a list")
    return data


def write(path: Path, data: dict) -> None:
    """Write verdicts.json atomically (write-then-rename)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def next_id(data: dict) -> str:
    """Compute the next v-NNNN id given existing verdicts. Stable across rebase
    because the agent recomputes against the current file at commit time."""
    max_n = 0
    for v in data.get("verdicts", []):
        vid = v.get("id", "")
        if vid.startswith("v-"):
            try:
                n = int(vid[2:])
            except ValueError:
                continue
            max_n = max(max_n, n)
    return f"v-{max_n + 1:04d}"


def append(
    path: Path,
    *,
    agent_id: str,
    git_hash: str,
    git_hash_parent: str,
    intent: str,
    what_went_wrong: str,
    judge_rationale: str,
    lesson: str,
    tags: Iterable[str] = (),
    now: datetime | None = None,
) -> Verdict:
    """Append a new verdict to verdicts.json. Returns the entry written.

    The caller is expected to commit the change. Conflict resolution on
    rebase is the agent's job — they should re-read, re-pick `id`, and
    re-append.
    """
    data = read(path)
    when = (now or datetime.now(tz=timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = Verdict(
        id=next_id(data),
        timestamp=when,
        agent_id=agent_id,
        git_hash=git_hash,
        git_hash_parent=git_hash_parent,
        intent=intent,
        what_went_wrong=what_went_wrong,
        judge_rationale=judge_rationale,
        lesson=lesson,
        tags=list(tags),
    )
    data["verdicts"].append(asdict(entry))
    write(path, data)
    return entry


def reconcile_after_rebase(path: Path) -> int:
    """Renumber verdicts to be monotonically increasing v-0001, v-0002, ...

    Useful after a merge introduces gaps or duplicate IDs. Returns the
    number of entries renumbered. Preserves order as currently in the file.
    """
    data = read(path)
    changed = 0
    for i, entry in enumerate(data["verdicts"], start=1):
        new_id = f"v-{i:04d}"
        if entry.get("id") != new_id:
            entry["id"] = new_id
            changed += 1
    if changed:
        write(path, data)
    return changed
