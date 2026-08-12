#!/usr/bin/env python3
"""Run an executable issue-intent acceptance evaluation."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from issue_intent_twin import Decision, IssueIntentTwin, IssueIntentTwinRequest


DEMO = {
    "subject_id": "issue-demo-42",
    "budget": 1.0,
    "intent": {
        "title": "Ship reliable import flow",
        "requirements": [
            {
                "id": "release-ready",
                "path": "release.status",
                "op": "eq",
                "value": "ready",
            },
            {
                "id": "coverage",
                "path": "quality.coverage",
                "op": "gte",
                "value": 0.90,
                "receipt": "coverage-report",
            },
        ],
        "forbidden_conditions": [
            {
                "id": "security-regression",
                "path": "security.regression",
                "op": "truthy",
            }
        ],
        "required_tests": ["unit", "integration"],
        "required_receipts": ["review"],
        "max_cost": 0.75,
    },
    "candidate": {
        "observations": {
            "release": {"status": "ready"},
            "quality": {"coverage": 0.94},
            "security": {"regression": False},
        },
        "tests": {"unit": True, "integration": True},
        "receipts": {
            "coverage-report": "sha256:demo",
            "review": "review-demo",
        },
        "cost": 0.25,
    },
}


def load_input(path: str | None) -> dict:
    if path is None:
        return DEMO
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("input JSON must be an object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate a candidate outcome against executable issue intent"
    )
    parser.add_argument("--input", help="JSON input; built-in demo when omitted")
    parser.add_argument("--output", help="optional receipt output path")
    args = parser.parse_args()

    data = load_input(args.input)
    payload = {
        "intent": data.get("intent", {}),
        "candidate": data.get("candidate", {}),
    }
    if data.get("expected_intent_digest"):
        payload["expected_intent_digest"] = data["expected_intent_digest"]
    request = IssueIntentTwinRequest(
        subject_id=str(data.get("subject_id", "")),
        payload=payload,
        budget=float(data.get("budget", 1.0)),
        grant_id=data.get("grant_id"),
        not_after=data.get("not_after"),
    )
    receipt = IssueIntentTwin().evaluate(request)
    rendered = json.dumps(receipt.as_dict(), indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if receipt.decision is Decision.ALLOW else 2


if __name__ == "__main__":
    raise SystemExit(main())
