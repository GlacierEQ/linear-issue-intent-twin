# Issue Intent Twin

Independent GlacierEQ portfolio implementation aligned to public Linear operating themes. This repository is not affiliated with or endorsed by Linear.

## Purpose

Keep the original product intent executable while issues, pull requests, and agent-generated implementations evolve.

The twin converts an issue's acceptance model into deterministic machine-readable conditions and evaluates a candidate outcome before merge. It answers a concrete question: **does the implementation still satisfy what the issue actually asked for?**

## Capabilities

The engine supports:

- nested acceptance predicates over structured observations
- equality, ordering, containment, existence, truthiness, membership, and regex predicates
- forbidden conditions that block merge when they become true
- predicate-specific evidence receipts
- named required tests
- named required receipts
- candidate cost against request and issue budgets
- optional freshness / expiry
- deterministic intent and candidate digests
- expected-intent digest checks to detect intent mutation
- deterministic merge-blocking evaluation receipts

A candidate is allowed only when every material acceptance condition succeeds.

## Predicate example

```json
{
  "id": "coverage",
  "path": "quality.coverage",
  "op": "gte",
  "value": 0.9,
  "receipt": "coverage-report"
}
```

The path is resolved against `candidate.observations`. If the value passes but the named receipt is absent, the requirement still fails. Silent success is not evidence.

## Run it

```bash
python scripts/operate.py
```

The built-in example compiles intent, evaluates a candidate, checks tests and evidence, and prints the receipt.

For your own input:

```bash
python scripts/operate.py --input request.json --output receipt.json
```

Input shape:

```json
{
  "subject_id": "issue-42",
  "budget": 1.0,
  "intent": {
    "requirements": [
      {"id": "ready", "path": "release.status", "op": "eq", "value": "ready"}
    ],
    "forbidden_conditions": [
      {"id": "regression", "path": "security.regression", "op": "truthy"}
    ],
    "required_tests": ["unit", "integration"],
    "required_receipts": ["review"],
    "max_cost": 0.75
  },
  "candidate": {
    "observations": {
      "release": {"status": "ready"},
      "security": {"regression": false}
    },
    "tests": {"unit": true, "integration": true},
    "receipts": {"review": "review-42"},
    "cost": 0.2
  }
}
```

## Intent drift

`compile_intent()` returns an `intent_digest`. A caller can persist that digest with the issue and later pass it as `expected_intent_digest`. If the acceptance model changes silently, evaluation refuses with `intent_digest_mismatch`.

## Verify behavior

```bash
python -m pytest -q
```

Tests cover complete acceptance, requirement failure, forbidden conditions, evidence requirements, test failure, deterministic intent compilation, drift detection, budget, expiry, malformed intent, invalid regex, duplicate predicates, and fail-closed missing data.

## Boundary

This is a vendor-neutral intent evaluation library and CLI. It does not claim a Linear API integration or hosted deployment. A Linear/GitHub integration can consume the deterministic receipt at the merge boundary without changing the central acceptance model.
