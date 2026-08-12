"""Executable issue-intent twin.

An issue intent is compiled into deterministic acceptance predicates, required
tests, required evidence receipts, budget limits, and optional freshness. A
candidate implementation is then evaluated against that frozen intent. The
result is a merge-blocking receipt, not a decorative policy label.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


class Decision(str, Enum):
    ALLOW = "ALLOW"
    REFUSE = "REFUSE"


@dataclass(frozen=True)
class IssueIntentTwinRequest:
    subject_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    budget: float = 1.0
    grant_id: str | None = None
    not_after: float | None = None


@dataclass(frozen=True)
class IssueIntentTwinReceipt:
    decision: Decision
    reasons: tuple[str, ...]
    digest: str
    metrics: dict[str, Any] = field(default_factory=dict)
    intent_digest: str | None = None
    candidate_digest: str | None = None
    merge_blocked: bool = True
    predicate_results: tuple[dict[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "reasons": list(self.reasons),
            "digest": self.digest,
            "metrics": self.metrics,
            "intent_digest": self.intent_digest,
            "candidate_digest": self.candidate_digest,
            "merge_blocked": self.merge_blocked,
            "predicate_results": list(self.predicate_results),
        }


class IntentSchemaError(ValueError):
    pass


class IssueIntentTwin:
    """Compile issue intent and evaluate candidate outcomes against it."""

    MIN_BUDGET = 0.0
    OPS = {
        "eq",
        "ne",
        "gt",
        "gte",
        "lt",
        "lte",
        "contains",
        "not_contains",
        "in",
        "exists",
        "truthy",
        "falsy",
        "matches",
    }

    @staticmethod
    def _normalize_name_list(value: Any, field_name: str) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise IntentSchemaError(f"{field_name}_not_list")
        names: list[str] = []
        seen: set[str] = set()
        for raw in value:
            name = str(raw).strip()
            if not name:
                raise IntentSchemaError(f"{field_name}_contains_empty_name")
            if name in seen:
                continue
            seen.add(name)
            names.append(name)
        return sorted(names)

    @classmethod
    def _normalize_predicates(cls, value: Any, field_name: str) -> list[dict[str, Any]]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise IntentSchemaError(f"{field_name}_not_list")
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, raw in enumerate(value):
            if not isinstance(raw, dict):
                raise IntentSchemaError(f"{field_name}_{index}_not_object")
            predicate_id = str(raw.get("id", "")).strip()
            path = str(raw.get("path", "")).strip()
            op = str(raw.get("op", "eq")).strip().lower()
            if not predicate_id:
                raise IntentSchemaError(f"{field_name}_{index}_id_missing")
            if predicate_id in seen:
                raise IntentSchemaError(f"{field_name}_{predicate_id}_duplicate")
            if not path:
                raise IntentSchemaError(f"{field_name}_{predicate_id}_path_missing")
            if op not in cls.OPS:
                raise IntentSchemaError(f"{field_name}_{predicate_id}_op_unknown")
            if op not in {"exists", "truthy", "falsy"} and "value" not in raw:
                raise IntentSchemaError(f"{field_name}_{predicate_id}_value_missing")
            predicate = {
                "id": predicate_id,
                "path": path,
                "op": op,
            }
            if "value" in raw:
                predicate["value"] = raw["value"]
            evidence = str(raw.get("receipt", "")).strip()
            if evidence:
                predicate["receipt"] = evidence
            description = str(raw.get("description", "")).strip()
            if description:
                predicate["description"] = description
            normalized.append(predicate)
            seen.add(predicate_id)
        return sorted(normalized, key=lambda item: item["id"])

    @classmethod
    def compile_intent(cls, intent: dict[str, Any]) -> dict[str, Any]:
        """Validate and canonicalize a machine-readable issue intent."""
        if not isinstance(intent, dict):
            raise IntentSchemaError("intent_not_object")
        requirements = cls._normalize_predicates(intent.get("requirements"), "requirements")
        forbidden = cls._normalize_predicates(
            intent.get("forbidden_conditions"),
            "forbidden_conditions",
        )
        required_tests = cls._normalize_name_list(intent.get("required_tests"), "required_tests")
        required_receipts = cls._normalize_name_list(
            intent.get("required_receipts"),
            "required_receipts",
        )
        if not requirements and not required_tests and not required_receipts:
            raise IntentSchemaError("intent_has_no_acceptance_conditions")

        compiled: dict[str, Any] = {
            "schema": "glaciereq.issue-intent.v1",
            "requirements": requirements,
            "forbidden_conditions": forbidden,
            "required_tests": required_tests,
            "required_receipts": required_receipts,
        }
        title = str(intent.get("title", "")).strip()
        if title:
            compiled["title"] = title
        if intent.get("max_cost") is not None:
            try:
                max_cost = float(intent["max_cost"])
            except (TypeError, ValueError) as exc:
                raise IntentSchemaError("max_cost_invalid") from exc
            if max_cost < 0:
                raise IntentSchemaError("max_cost_negative")
            compiled["max_cost"] = max_cost
        if intent.get("not_after") is not None:
            try:
                compiled["not_after"] = float(intent["not_after"])
            except (TypeError, ValueError) as exc:
                raise IntentSchemaError("not_after_invalid") from exc
        compiled["intent_digest"] = _digest(compiled)
        return compiled

    @staticmethod
    def _get_path(root: Any, path: str) -> tuple[bool, Any]:
        current = root
        for raw_part in path.split("."):
            part = raw_part.strip()
            if not part:
                return False, None
            if isinstance(current, dict):
                if part not in current:
                    return False, None
                current = current[part]
            elif isinstance(current, (list, tuple)) and part.isdigit():
                index = int(part)
                if index >= len(current):
                    return False, None
                current = current[index]
            else:
                return False, None
        return True, current

    @staticmethod
    def _ordered_compare(actual: Any, expected: Any, op: str) -> bool:
        try:
            if op == "gt":
                return actual > expected
            if op == "gte":
                return actual >= expected
            if op == "lt":
                return actual < expected
            return actual <= expected
        except TypeError:
            return False

    @classmethod
    def _predicate_matches(cls, predicate: dict[str, Any], observations: Any) -> tuple[bool, Any]:
        exists, actual = cls._get_path(observations, predicate["path"])
        op = predicate["op"]
        expected = predicate.get("value")
        if op == "exists":
            return exists, actual
        if op == "truthy":
            return exists and bool(actual), actual
        if op == "falsy":
            return exists and not bool(actual), actual
        if not exists:
            return False, None
        if op == "eq":
            return actual == expected, actual
        if op == "ne":
            return actual != expected, actual
        if op in {"gt", "gte", "lt", "lte"}:
            return cls._ordered_compare(actual, expected, op), actual
        if op == "contains":
            try:
                return expected in actual, actual
            except TypeError:
                return False, actual
        if op == "not_contains":
            try:
                return expected not in actual, actual
            except TypeError:
                return False, actual
        if op == "in":
            try:
                return actual in expected, actual
            except TypeError:
                return False, actual
        if op == "matches":
            try:
                return re.search(str(expected), str(actual)) is not None, actual
            except re.error:
                return False, actual
        return False, actual

    def evaluate(
        self,
        req: IssueIntentTwinRequest,
        *,
        now: float | None = None,
    ) -> IssueIntentTwinReceipt:
        reasons: list[str] = []
        if not str(req.subject_id or "").strip():
            reasons.append("subject_id_missing")
        if req.budget <= self.MIN_BUDGET:
            reasons.append("budget_non_positive")
        payload = req.payload if isinstance(req.payload, dict) else {}
        if not isinstance(req.payload, dict):
            reasons.append("payload_not_object")

        compiled: dict[str, Any] | None = None
        try:
            compiled = self.compile_intent(payload.get("intent", {}))
        except IntentSchemaError as exc:
            reasons.append(str(exc))

        candidate = payload.get("candidate")
        if not isinstance(candidate, dict):
            reasons.append("candidate_not_object")
            candidate = {}
        observations = candidate.get("observations")
        if not isinstance(observations, dict):
            reasons.append("candidate_observations_not_object")
            observations = {}
        tests = candidate.get("tests")
        if not isinstance(tests, dict):
            reasons.append("candidate_tests_not_object")
            tests = {}
        receipts = candidate.get("receipts")
        if not isinstance(receipts, dict):
            reasons.append("candidate_receipts_not_object")
            receipts = {}

        candidate_digest = _digest(candidate) if candidate else None
        predicate_results: list[dict[str, Any]] = []
        satisfied_count = 0
        at = time.time() if now is None else float(now)

        if compiled is not None:
            expected_digest = str(payload.get("expected_intent_digest", "")).strip()
            if expected_digest and expected_digest != compiled["intent_digest"]:
                reasons.append("intent_digest_mismatch")

            expiries = [value for value in (req.not_after, compiled.get("not_after")) if value is not None]
            if expiries and at > min(float(value) for value in expiries):
                reasons.append("intent_expired")

            try:
                candidate_cost = float(candidate.get("cost", 0.0))
            except (TypeError, ValueError):
                candidate_cost = 0.0
                reasons.append("candidate_cost_invalid")
            if candidate_cost < 0:
                reasons.append("candidate_cost_negative")
            max_cost = min(req.budget, float(compiled.get("max_cost", req.budget)))
            if candidate_cost > max_cost:
                reasons.append("budget_exceeded")

            for predicate in compiled["requirements"]:
                matched, actual = self._predicate_matches(predicate, observations)
                receipt_name = predicate.get("receipt")
                evidence_ok = not receipt_name or bool(receipts.get(receipt_name))
                passed = bool(matched and evidence_ok)
                predicate_results.append(
                    {
                        "id": predicate["id"],
                        "kind": "requirement",
                        "passed": passed,
                        "actual": actual,
                        "evidence_ok": evidence_ok,
                    }
                )
                if passed:
                    satisfied_count += 1
                else:
                    reasons.append(f"requirement_failed:{predicate['id']}")
                    if receipt_name and not evidence_ok:
                        reasons.append(f"predicate_receipt_missing:{receipt_name}")

            for predicate in compiled["forbidden_conditions"]:
                matched, actual = self._predicate_matches(predicate, observations)
                predicate_results.append(
                    {
                        "id": predicate["id"],
                        "kind": "forbidden",
                        "passed": not matched,
                        "actual": actual,
                        "evidence_ok": True,
                    }
                )
                if matched:
                    reasons.append(f"forbidden_condition_matched:{predicate['id']}")
                else:
                    satisfied_count += 1

            for test_name in compiled["required_tests"]:
                if tests.get(test_name) is not True:
                    reasons.append(f"test_failed_or_missing:{test_name}")
                else:
                    satisfied_count += 1
            for receipt_name in compiled["required_receipts"]:
                if not receipts.get(receipt_name):
                    reasons.append(f"receipt_missing:{receipt_name}")
                else:
                    satisfied_count += 1

        decision = Decision.REFUSE if reasons else Decision.ALLOW
        if not reasons:
            reasons = ["intent_satisfied"]
        total_conditions = 0
        intent_digest = None
        if compiled is not None:
            intent_digest = compiled["intent_digest"]
            total_conditions = (
                len(compiled["requirements"])
                + len(compiled["forbidden_conditions"])
                + len(compiled["required_tests"])
                + len(compiled["required_receipts"])
            )
        body = {
            "schema": "glaciereq.issue-intent-evaluation.v1",
            "subject_id": req.subject_id,
            "intent_digest": intent_digest,
            "candidate_digest": candidate_digest,
            "decision": decision.value,
            "reasons": reasons,
            "predicate_results": predicate_results,
        }
        return IssueIntentTwinReceipt(
            decision=decision,
            reasons=tuple(reasons),
            digest=_digest(body),
            metrics={
                "condition_count": total_conditions,
                "satisfied_count": satisfied_count,
                "violation_count": 0 if decision is Decision.ALLOW else len(reasons),
                "budget": req.budget,
            },
            intent_digest=intent_digest,
            candidate_digest=candidate_digest,
            merge_blocked=decision is Decision.REFUSE,
            predicate_results=tuple(predicate_results),
        )


Mechanism = IssueIntentTwin
