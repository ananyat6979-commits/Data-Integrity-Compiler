import json

import pytest

from experiments.m2a.development_ledger import execute_or_resume


def test_resume_reuses_intact_evidence_and_recovers_incomplete_tail(tmp_path):
    workspace = tmp_path / "attempts"
    journal = tmp_path / "ledger.jsonl"
    identity = {"case": "duplicate-ingestion", "source_sha256": "source-a"}
    attempts = []

    def run_case(attempt):
        attempts.append(attempt)
        evidence = attempt / "execution" / "report.json"
        evidence.parent.mkdir(parents=True)
        evidence.write_text('{"status":"passed"}', encoding="utf-8")
        private = attempt / "evaluator"
        private.mkdir()
        (private / "ground_truth.json").write_text("private", encoding="utf-8")
        return {"attempt_number": len(attempts)}

    assert execute_or_resume(workspace, journal, identity, run_case) == {"attempt_number": 1}
    complete = journal.read_bytes()
    assert "evaluator" not in json.loads(complete)["record"]["artifacts"]
    assert b"ground_truth" not in complete

    journal.write_bytes(complete + b'{"record":')
    assert execute_or_resume(workspace, journal, identity, run_case) == {"attempt_number": 1}
    assert journal.read_bytes() == complete

    (attempts[0] / "execution/report.json").write_text("tampered", encoding="utf-8")
    assert execute_or_resume(workspace, journal, identity, run_case) == {"attempt_number": 2}
    assert execute_or_resume(workspace, journal, {**identity, "source_sha256": "source-b"}, run_case) == {
        "attempt_number": 3
    }
    assert len(journal.read_bytes().splitlines()) == 3

    journal.write_bytes(b"damaged\n" + complete)
    with pytest.raises(ValueError, match="at byte 0"):
        execute_or_resume(workspace, journal, identity, run_case)


def test_failed_attempt_is_retried_without_recording_it(tmp_path):
    workspace = tmp_path / "attempts"
    journal = tmp_path / "ledger.jsonl"
    attempts = []

    def run_case(attempt):
        attempts.append(attempt)
        evidence = attempt / "execution" / "report.json"
        evidence.parent.mkdir(parents=True)
        evidence.write_text("evidence", encoding="utf-8")
        if len(attempts) == 1:
            raise RuntimeError("interrupted")
        return {"done": True}

    with pytest.raises(RuntimeError, match="interrupted"):
        execute_or_resume(workspace, journal, {"case": "cleaning"}, run_case)
    assert journal.read_bytes() == b""
    assert execute_or_resume(workspace, journal, {"case": "cleaning"}, run_case) == {"done": True}
    assert attempts[0] != attempts[1]
    assert len(journal.read_bytes().splitlines()) == 1
