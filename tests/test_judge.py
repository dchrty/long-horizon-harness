import json
from pathlib import Path

import pytest

from agent_factory import judge


def test_validate_verdict_pass():
    payload = {"verdict": "pass", "rationale": "ok", "concerns": []}
    assert judge.validate_verdict_payload(payload) is payload


def test_validate_verdict_fail():
    payload = {"verdict": "fail", "rationale": "bad", "concerns": ["x"]}
    assert judge.validate_verdict_payload(payload) is payload


def test_validate_rejects_unknown_verdict():
    with pytest.raises(judge.JudgeProtocolError, match="verdict must be one of"):
        judge.validate_verdict_payload({"verdict": "maybe", "rationale": "x", "concerns": []})


def test_validate_rejects_missing_field():
    with pytest.raises(judge.JudgeProtocolError, match="missing field"):
        judge.validate_verdict_payload({"verdict": "pass", "rationale": "x"})


def test_validate_rejects_non_list_concerns():
    with pytest.raises(judge.JudgeProtocolError, match="concerns"):
        judge.validate_verdict_payload({"verdict": "pass", "rationale": "x", "concerns": "nope"})


def test_validate_rejects_non_string_rationale():
    with pytest.raises(judge.JudgeProtocolError, match="rationale"):
        judge.validate_verdict_payload({"verdict": "pass", "rationale": 7, "concerns": []})


def test_validate_rejects_non_object():
    with pytest.raises(judge.JudgeProtocolError, match="must be an object"):
        judge.validate_verdict_payload(["fail"])


def test_read_verdict_file(tmp_path: Path):
    p = tmp_path / "v.json"
    p.write_text(json.dumps({"verdict": "fail", "rationale": "x", "concerns": ["c"]}))
    out = judge.read_verdict_file(p)
    assert out["verdict"] == "fail"


def test_read_verdict_file_missing(tmp_path: Path):
    with pytest.raises(judge.JudgeProtocolError, match="not found"):
        judge.read_verdict_file(tmp_path / "nope.json")


def test_read_verdict_file_invalid_json(tmp_path: Path):
    p = tmp_path / "v.json"
    p.write_text("not json{{")
    with pytest.raises(judge.JudgeProtocolError, match="invalid JSON"):
        judge.read_verdict_file(p)
