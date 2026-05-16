"""Tests for the judges history viewer.

Tests live on the parser/render side because that's the operator-
facing piece. The judge.sh shape is exercised in test_judge_sh_shape
below (grep-style assertions on the template, no bash execution).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_factory import config, judges


def _write_history(layout, lines: list[str]) -> Path:
    """Drop a judge_history.jsonl with the given raw lines into the
    project's agent_logs/. Returns the path."""
    log_dir = layout.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / judges.HISTORY_FILENAME
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _rec(
    ts="2026-05-16T17:00:00Z",
    agent="agent-factory-mfctx-1",
    git_hash="abc1234567890",
    model="claude-opus-4-6",
    exit_code=0,
    verdict="pass",
    duration_ms=12345,
    tee_log="agent-factory-mfctx-1_judge_abc12345_1700000000.log",
) -> str:
    return json.dumps(
        {
            "ts": ts,
            "agent_id": agent,
            "git_hash": git_hash,
            "git_hash_short": git_hash[:8],
            "model": model,
            "exit_code": exit_code,
            "verdict": verdict,
            "duration_ms": duration_ms,
            "tee_log": tee_log,
        }
    )


def test_read_history_returns_empty_when_no_file(project_dir):
    layout = config.discover(project_dir)
    assert judges.read_history(layout) == []


def test_read_history_parses_well_formed_jsonl(project_dir):
    layout = config.discover(project_dir)
    _write_history(layout, [_rec(), _rec(verdict="fail", exit_code=1)])
    records = judges.read_history(layout)
    assert len(records) == 2
    assert records[0].verdict == "pass"
    assert records[1].verdict == "fail"
    assert records[1].exit_code == 1


def test_read_history_skips_malformed_lines(project_dir):
    layout = config.discover(project_dir)
    _write_history(
        layout,
        [
            _rec(verdict="pass"),
            "{ not valid json",  # malformed mid-stream
            _rec(verdict="fail"),
            "",  # empty line
            "[]",  # JSON but not a dict
        ],
    )
    records = judges.read_history(layout)
    # Two valid records survive; the malformed and non-dict lines drop.
    assert len(records) == 2
    assert [r.verdict for r in records] == ["pass", "fail"]


def test_read_history_tolerates_missing_fields(project_dir):
    """Older log lines or partial writes shouldn't crash the viewer."""
    layout = config.discover(project_dir)
    minimal = json.dumps({"ts": "2026-05-16T17:00:00Z"})
    _write_history(layout, [minimal])
    records = judges.read_history(layout)
    assert len(records) == 1
    assert records[0].ts == "2026-05-16T17:00:00Z"
    assert records[0].verdict == "unknown"
    assert records[0].exit_code == -1


def test_filter_records_by_agent(project_dir):
    layout = config.discover(project_dir)
    _write_history(
        layout,
        [
            _rec(agent="agent-factory-mfctx-1"),
            _rec(agent="agent-factory-mfctx-2"),
            _rec(agent="agent-factory-mfctx-1"),
        ],
    )
    records = judges.read_history(layout)
    filtered = judges.filter_records(records, agent="agent-factory-mfctx-1")
    assert len(filtered) == 2
    assert all(r.agent_id == "agent-factory-mfctx-1" for r in filtered)


def test_filter_records_by_verdict(project_dir):
    layout = config.discover(project_dir)
    _write_history(
        layout,
        [_rec(verdict="pass"), _rec(verdict="fail"), _rec(verdict="infra-error")],
    )
    records = judges.read_history(layout)
    assert len(judges.filter_records(records, verdict="fail")) == 1
    assert len(judges.filter_records(records, verdict="pass")) == 1
    assert len(judges.filter_records(records, verdict="infra-error")) == 1


def test_show_with_no_history_reports_clearly(project_dir, capsys):
    layout = config.discover(project_dir)
    judges.show(
        layout,
        follow=False,
        tail=20,
        agent=None,
        verdict=None,
        show_hash=None,
    )
    out = capsys.readouterr().out
    assert "No judge invocations recorded yet" in out


def test_show_with_filter_miss_reports_distinct_message(project_dir, capsys):
    layout = config.discover(project_dir)
    _write_history(layout, [_rec(verdict="pass")])
    judges.show(
        layout,
        follow=False,
        tail=20,
        agent=None,
        verdict="fail",
        show_hash=None,
    )
    out = capsys.readouterr().out
    assert "No judge invocations match the filter" in out
    assert "records total=1" in out


def test_show_renders_table_with_records(project_dir, capsys):
    layout = config.discover(project_dir)
    _write_history(
        layout,
        [_rec(verdict="pass"), _rec(verdict="fail", git_hash="def4567890abc")],
    )
    judges.show(
        layout,
        follow=False,
        tail=20,
        agent=None,
        verdict=None,
        show_hash=None,
    )
    out = capsys.readouterr().out
    assert "abc12345" in out
    assert "def45678" in out
    assert "pass" in out
    assert "fail" in out


def test_show_tail_truncates_to_last_n(project_dir, capsys):
    layout = config.discover(project_dir)
    lines = [_rec(git_hash=f"{'a' * 4}{i:04d}{'0' * 4}") for i in range(5)]
    _write_history(layout, lines)
    judges.show(
        layout,
        follow=False,
        tail=2,
        agent=None,
        verdict=None,
        show_hash=None,
    )
    out = capsys.readouterr().out
    # Only the last two short hashes should appear.
    assert "aaaa0003" in out
    assert "aaaa0004" in out
    assert "aaaa0000" not in out


def test_show_hash_dumps_tee_log(project_dir, capsys):
    layout = config.discover(project_dir)
    tee_log_name = "agent-factory-mfctx-1_judge_abc12345_1700000000.log"
    # Put a real tee log file in agent_logs/ so the show path can read it.
    layout.log_dir.mkdir(parents=True, exist_ok=True)
    (layout.log_dir / tee_log_name).write_text(
        "claude (judge) full output here\nverdict was good\n", encoding="utf-8"
    )
    # Record references it by container-absolute path; show() should
    # remap to host-side via log_dir.
    _write_history(
        layout,
        [_rec(git_hash="abc1234567890", tee_log=f"/workspace/agent_logs/{tee_log_name}")],
    )
    judges.show(
        layout,
        follow=False,
        tail=20,
        agent=None,
        verdict=None,
        show_hash="abc1234",
    )
    out = capsys.readouterr().out
    assert "claude (judge) full output here" in out
    assert "verdict was good" in out


def test_show_hash_reports_ambiguous_prefix(project_dir, capsys):
    layout = config.discover(project_dir)
    _write_history(
        layout,
        [
            _rec(git_hash="abc1234500000"),
            _rec(git_hash="abc1234999999"),
        ],
    )
    judges.show(
        layout,
        follow=False,
        tail=20,
        agent=None,
        verdict=None,
        show_hash="abc1",
    )
    out = capsys.readouterr().out
    assert "matches 2 invocations" in out
    assert "Use a longer prefix" in out


def test_show_hash_reports_no_match(project_dir, capsys):
    layout = config.discover(project_dir)
    _write_history(layout, [_rec()])
    judges.show(
        layout,
        follow=False,
        tail=20,
        agent=None,
        verdict=None,
        show_hash="zzzzzzz",
    )
    out = capsys.readouterr().out
    assert "No judge invocation found with hash prefix" in out


def test_follow_picks_up_new_records(project_dir, capsys):
    """Follow mode should detect lines appended after we start watching."""
    layout = config.discover(project_dir)
    _write_history(layout, [_rec(git_hash="aaaa0000abcdef")])

    # Append once during the first sleep, then raise KeyboardInterrupt
    # so the follow loop exits cleanly.
    appended: list[bool] = [False]

    def fake_sleep(_seconds):
        if not appended[0]:
            path = judges.history_path(layout)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(_rec(git_hash="bbbb1111abcdef") + "\n")
            appended[0] = True
            return
        raise KeyboardInterrupt()

    with patch("agent_factory.judges.time.sleep", side_effect=fake_sleep):
        judges.show(
            layout,
            follow=True,
            tail=20,
            agent=None,
            verdict=None,
            show_hash=None,
        )

    out = capsys.readouterr().out
    # Initial record appears in the snapshot pass; new record appears
    # in the tail pass; both must be visible.
    assert "aaaa0000" in out
    assert "bbbb1111" in out
    assert "Stopping follow" in out


# ---------------------------------------------------------------------------
# judge.sh shape — grep-style assertions on the template so behavioural
# contracts surface as a unit test rather than a runtime surprise.
# ---------------------------------------------------------------------------


@pytest.fixture
def judge_sh_text() -> str:
    template_path = (
        Path(__file__).resolve().parent.parent
        / "agent_factory"
        / "templates"
        / "judge.sh"
    )
    return template_path.read_text(encoding="utf-8")


def test_judge_sh_has_start_marker(judge_sh_text):
    assert "[JUDGE-START]" in judge_sh_text
    # Start marker should include hash, agent, model, ts, log fields.
    assert "hash=$SHORT" in judge_sh_text
    assert "agent=$AGENT_ID" in judge_sh_text


def test_judge_sh_has_end_marker(judge_sh_text):
    assert "[JUDGE-END]" in judge_sh_text
    assert "verdict=$VERDICT_STR" in judge_sh_text
    assert "duration_ms=$DURATION_MS" in judge_sh_text


def test_judge_sh_tees_claude_output(judge_sh_text):
    """Claude output must hit BOTH the parser tempfile AND the host-
    visible log file so the operator can inspect transcripts later."""
    assert 'tee "$JUDGE_LOG"' in judge_sh_text
    assert "$RAW_FILE" in judge_sh_text


def test_judge_sh_appends_jsonl_record(judge_sh_text):
    """Every invocation should append a JSON line for the judges view."""
    assert "judge_history.jsonl" in judge_sh_text
    assert ">> \"$HISTORY_FILE\"" in judge_sh_text
    # Schema fields the viewer relies on must be present in the printf.
    for field in (
        '"ts":"%s"',
        '"agent_id":"%s"',
        '"git_hash":"%s"',
        '"git_hash_short":"%s"',
        '"verdict":"%s"',
        '"exit_code":%d',
        '"duration_ms":%d',
        '"tee_log":"%s"',
    ):
        assert field in judge_sh_text, f"judge.sh JSONL printf is missing {field}"
