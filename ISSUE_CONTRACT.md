# Issue contract — Issue Intent Twin

## Problem
Agent-written issue/PR loops lose the original product intent.

## Desired outcome
A bounded, open, testable implementation of **Issue Intent Twin** that demonstrates Twin each issue with acceptance predicates and block merges that violate them.

## Non-goals
- Linear affiliation or proprietary integration
- Portfolio-wide scale/performance claims
- UI marketing site

## Acceptance
1. Mechanism module implements allow + refuse with structured receipts
2. pytest behavioral suite green
3. operate.py cold-start produces JSON receipt
4. Non-affiliation disclaimer preserved
