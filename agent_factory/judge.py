"""Host-side helpers for the judge contract.

The judge itself (a fresh `claude` subprocess) runs inside the container
via templates/judge.sh. The host's role is limited to:

  * seeding judge.sh into the repo (handled in repo.py)
  * exposing a validator for verdict JSON the in-container judge writes
  * providing a small helper to read a verdict file produced by the judge

These functions exist so unit tests can verify the shape contract without
spinning up Docker.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REQUIRED_VERDICT_FIELDS = ("verdict", "rationale", "concerns")
ALLOWED_VERDICTS = ("pass", "fail")


class JudgeProtocolError(ValueError):
    pass


def validate_verdict_payload(payload: Any) -> dict:
    """Check the shape of a verdict JSON object as written by judge.sh.

    Returns the normalised dict. Raises JudgeProtocolError on violation.
    """
    if not isinstance(payload, dict):
        raise JudgeProtocolError(f"verdict payload must be an object, got {type(payload).__name__}")
    for field_name in REQUIRED_VERDICT_FIELDS:
        if field_name not in payload:
            raise JudgeProtocolError(f"verdict payload missing field: {field_name!r}")
    if payload["verdict"] not in ALLOWED_VERDICTS:
        raise JudgeProtocolError(
            f"verdict must be one of {ALLOWED_VERDICTS}, got {payload['verdict']!r}"
        )
    if not isinstance(payload["rationale"], str):
        raise JudgeProtocolError("rationale must be a string")
    if not isinstance(payload["concerns"], list):
        raise JudgeProtocolError("concerns must be a list")
    return payload


def read_verdict_file(path: Path) -> dict:
    """Read and validate a verdict JSON file produced by judge.sh."""
    if not path.is_file():
        raise JudgeProtocolError(f"verdict file not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise JudgeProtocolError(f"{path}: invalid JSON: {e}") from e
    return validate_verdict_payload(payload)
