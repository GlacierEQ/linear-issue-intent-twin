from __future__ import annotations

import pytest

from issue_intent_twin import (
    Decision,
    IntentSchemaError,
    IssueIntentTwin,
    IssueIntentTwinRequest,
)


NOW = 1_800_000_000.0


def _evaluate(intent, candidate):
    return IssueIntentTwin().evaluate(
        IssueIntentTwinRequest(
            subject_id="issue",
            payload={"intent": intent, "candidate": candidate},
            budget=1.0,
        ),
        now=NOW,
    )


def test_empty_intent_cannot_approve_anything() -> None:
    receipt = _evaluate({}, {"observations": {}, "tests": {}, "receipts": {}})
    assert receipt.decision is Decision.REFUSE
    assert "intent_has_no_acceptance_conditions" in receipt.reasons


def test_missing_observation_does_not_compare_as_none_success() -> None:
    intent = {
        "requirements": [
            {"id": "missing", "path": "never.present", "op": "eq", "value": None}
        ]
    }
    receipt = _evaluate(
        intent,
        {"observations": {}, "tests": {}, "receipts": {}, "cost": 0},
    )
    assert receipt.decision is Decision.REFUSE
    assert "requirement_failed:missing" in receipt.reasons


def test_predicate_evidence_cannot_be_omitted() -> None:
    intent = {
        "requirements": [
            {
                "id": "verified",
                "path": "result.ok",
                "op": "truthy",
                "receipt": "runtime-proof",
            }
        ]
    }
    receipt = _evaluate(
        intent,
        {
            "observations": {"result": {"ok": True}},
            "tests": {},
            "receipts": {},
            "cost": 0,
        },
    )
    assert receipt.decision is Decision.REFUSE
    assert "predicate_receipt_missing:runtime-proof" in receipt.reasons


def test_regex_predicate_handles_invalid_pattern_without_crash_open() -> None:
    intent = {
        "requirements": [
            {"id": "pattern", "path": "value", "op": "matches", "value": "["}
        ]
    }
    receipt = _evaluate(
        intent,
        {"observations": {"value": "anything"}, "tests": {}, "receipts": {}, "cost": 0},
    )
    assert receipt.decision is Decision.REFUSE
    assert "requirement_failed:pattern" in receipt.reasons


def test_duplicate_predicate_ids_are_rejected() -> None:
    with pytest.raises(IntentSchemaError, match="duplicate"):
        IssueIntentTwin.compile_intent(
            {
                "requirements": [
                    {"id": "same", "path": "a", "op": "truthy"},
                    {"id": "same", "path": "b", "op": "truthy"},
                ]
            }
        )


def test_negative_candidate_cost_refuses() -> None:
    receipt = _evaluate(
        {"required_tests": ["unit"]},
        {"observations": {}, "tests": {"unit": True}, "receipts": {}, "cost": -1},
    )
    assert receipt.decision is Decision.REFUSE
    assert "candidate_cost_negative" in receipt.reasons


def test_non_object_candidate_surfaces_fail_closed() -> None:
    receipt = _evaluate(
        {"required_tests": ["unit"]},
        {"observations": [], "tests": [], "receipts": [], "cost": 0},
    )
    assert receipt.decision is Decision.REFUSE
    assert "candidate_observations_not_object" in receipt.reasons
    assert "candidate_tests_not_object" in receipt.reasons
    assert "candidate_receipts_not_object" in receipt.reasons
