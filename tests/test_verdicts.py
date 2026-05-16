import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_factory import verdicts


def _empty(path: Path) -> None:
    path.write_text(json.dumps({"version": 1, "verdicts": []}))


def test_read_returns_empty_when_missing(tmp_path: Path):
    out = verdicts.read(tmp_path / "verdicts.json")
    assert out == {"version": 1, "verdicts": []}


def test_read_rejects_unsupported_version(tmp_path: Path):
    p = tmp_path / "verdicts.json"
    p.write_text(json.dumps({"version": 99, "verdicts": []}))
    with pytest.raises(verdicts.VerdictsError, match="schema version"):
        verdicts.read(p)


def test_read_rejects_malformed_json(tmp_path: Path):
    p = tmp_path / "verdicts.json"
    p.write_text("{ this is not json")
    with pytest.raises(verdicts.VerdictsError, match="malformed JSON"):
        verdicts.read(p)


def test_next_id_starts_at_one(tmp_path: Path):
    p = tmp_path / "verdicts.json"
    _empty(p)
    assert verdicts.next_id(verdicts.read(p)) == "v-0001"


def test_next_id_increments(tmp_path: Path):
    p = tmp_path / "verdicts.json"
    data = {
        "version": 1,
        "verdicts": [
            {"id": "v-0001"},
            {"id": "v-0003"},
            {"id": "v-0007"},
            {"id": "not-a-verdict-id"},
        ],
    }
    p.write_text(json.dumps(data))
    assert verdicts.next_id(verdicts.read(p)) == "v-0008"


def test_append_writes_entry(tmp_path: Path):
    p = tmp_path / "verdicts.json"
    _empty(p)
    fixed = datetime(2026, 1, 15, 14, 22, 9, tzinfo=timezone.utc)
    entry = verdicts.append(
        p,
        agent_id="agent-3",
        git_hash="a1b2c3d",
        git_hash_parent="f0e1d2c",
        intent="parse COBOL COPY statements",
        what_went_wrong="assumed single-line COPY",
        judge_rationale="overfit to corpus",
        lesson="check line continuation",
        tags=["cobol", "parser"],
        now=fixed,
    )
    assert entry.id == "v-0001"
    assert entry.timestamp == "2026-01-15T14:22:09Z"

    data = json.loads(p.read_text())
    assert len(data["verdicts"]) == 1
    written = data["verdicts"][0]
    assert written["agent_id"] == "agent-3"
    assert written["tags"] == ["cobol", "parser"]


def test_append_increments_id_across_calls(tmp_path: Path):
    p = tmp_path / "verdicts.json"
    _empty(p)
    for i in range(3):
        verdicts.append(
            p,
            agent_id=f"agent-{i}",
            git_hash=f"hash{i}",
            git_hash_parent=f"parent{i}",
            intent="",
            what_went_wrong="",
            judge_rationale="",
            lesson="",
        )
    ids = [v["id"] for v in json.loads(p.read_text())["verdicts"]]
    assert ids == ["v-0001", "v-0002", "v-0003"]


def test_reconcile_renumbers_gaps(tmp_path: Path):
    p = tmp_path / "verdicts.json"
    p.write_text(
        json.dumps(
            {
                "version": 1,
                "verdicts": [
                    {"id": "v-0005"},
                    {"id": "v-0007"},
                    {"id": "v-0007"},
                ],
            }
        )
    )
    changed = verdicts.reconcile_after_rebase(p)
    assert changed == 3
    ids = [v["id"] for v in json.loads(p.read_text())["verdicts"]]
    assert ids == ["v-0001", "v-0002", "v-0003"]


def test_write_is_atomic_replace(tmp_path: Path):
    """write() uses rename, so a half-written file shouldn't appear at path."""
    p = tmp_path / "verdicts.json"
    verdicts.write(p, {"version": 1, "verdicts": []})
    assert p.read_text().startswith("{")
    # No leftover tmp file
    assert list(tmp_path.glob("*.tmp")) == []
