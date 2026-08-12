from __future__ import annotations

from issue_intent_twin import Decision, IssueIntentTwin, IssueIntentTwinRequest


NOW = 1_800_000_000.0


def _intent(**overrides):
    value = {
        "title": "Ship reliable import flow",
        "requirements": [
            {"id": "status-ready", "path": "release.status", "op": "eq", "value": "ready"},
            {
                "id": "coverage",
                "path": "quality.coverage",
                "op": "gte",
                "value": 0.90,
                "receipt": "coverage-report",
            },
        ],
        "forbidden_conditions": [
            {"id": "security-regression", "path": "security.regression", "op": "truthy"}
        ],
        "required_tests": ["unit", "integration"],
        "required_receipts": ["review"],
        "max_cost": 0.75,
        "not_after": NOW + 100,
    }
    value.update(overrides)
    return value


def _candidate(**overrides):
    value = {
        "observations": {
            "release": {"status": "ready"},
            "quality": {"coverage": 0.94},
            "security": {"regression": False},
        },
        "tests": {"unit": True, "integration": True},
        "receipts": {"coverage-report": "sha256:abc", "review": "review-42"},
        "cost": 0.25,
    }
    value.update(overrides)
    return value


def _request(intent=None, candidate=None, **kwargs):
    return IssueIntentTwinRequest(
        subject_id="issue-42",
        payload={"intent": intent or _intent(), "candidate": candidate or _candidate()},
        budget=1.0,
        **kwargs,
    )


def test_all_acceptance_conditions_allow_merge() -> None:
    receipt = IssueIntentTwin().evaluate(_request(), now=NOW)

    assert receipt.decision is Decision.ALLOW
    assert receipt.merge_blocked is False
    assert receipt.reasons == ("intent_satisfied",)
    assert receipt.metrics["condition_count"] == 6
    assert receipt.metrics["satisfied_count"] == 6
    assert len(receipt.intent_digest or "") == 64
    assert len(receipt.candidate_digest or "") == 64
    assert len(receipt.digest) == 64


def test_failed_requirement_blocks_merge() -> None:
    candidate = _candidate()
    candidate["observations"]["quality"]["coverage"] = 0.70
    receipt = IssueIntentTwin().evaluate(_request(candidate=candidate), now=NOW)

    assert receipt.decision is Decision.REFUSE
    assert receipt.merge_blocked is True
    assert "requirement_failed:coverage" in receipt.reasons


def test_forbidden_condition_blocks_merge() -> None:
    candidate = _candidate()
    candidate["observations"]["security"]["regression"] = True
    receipt = IssueIntentTwin().evaluate(_request(candidate=candidate), now=NOW)

    assert receipt.decision is Decision.REFUSE
    assert "forbidden_condition_matched:security-regression" in receipt.reasons


def test_required_test_and_receipt_are_real_acceptance_conditions() -> None:
    candidate = _candidate()
    candidate["tests"]["integration"] = False
    candidate["receipts"].pop("review")
    receipt = IssueIntentTwin().evaluate(_request(candidate=candidate), now=NOW)

    assert receipt.decision is Decision.REFUSE
    assert "test_failed_or_missing:integration" in receipt.reasons
    assert "receipt_missing:review" in receipt.reasons


def test_intent_digest_is_deterministic_across_predicate_order() -> None:
    twin = IssueIntentTwin()
    first = _intent()
    second = _intent()
    second["requirements"] = list(reversed(second["requirements"]))

    assert twin.compile_intent(first)["intent_digest"] == twin.compile_intent(second)["intent_digest"]


def test_expected_intent_digest_detects_drift() -> None:
    twin = IssueIntentTwin()
    digest = twin.compile_intent(_intent())["intent_digest"]
    changed = _intent(max_cost=0.50)
    req = _request(intent=changed)
    req = IssueIntentTwinRequest(
        subject_id=req.subject_id,
        payload={**req.payload, "expected_intent_digest": digest},
        budget=req.budget,
    )
    receipt = twin.evaluate(req, now=NOW)

    assert receipt.decision is Decision.REFUSE
    assert "intent_digest_mismatch" in receipt.reasons


def test_budget_and_expiry_fail_closed() -> None:
    expensive = _candidate(cost=0.80)
    over_budget = IssueIntentTwin().evaluate(_request(candidate=expensive), now=NOW)
    expired = IssueIntentTwin().evaluate(_request(), now=NOW + 101)

    assert over_budget.decision is Decision.REFUSE
    assert "budget_exceeded" in over_budget.reasons
    assert expired.decision is Decision.REFUSE
    assert "intent_expired" in expired.reasons
