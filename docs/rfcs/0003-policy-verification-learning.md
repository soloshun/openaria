# RFC 0003: guarded proposals, verification, and truth-aware learning

Status: Accepted for Lumis SDK 0.0.8

## Decision

Lumis SDK exposes strict `lumis.dev/v1alpha1` playbook, policy, proposal, approval-decision,
verification, and truth-transition contracts. Core evaluates declarative allowlists and bounded
parameters, but contains no executor and never grants execution authority.

Sprint 4 and Sprint 5 roadmap capabilities ship together in package release `0.0.8`. Roadmap
labels `v0.4` and `v0.5` continue to identify capability milestones, not package versions.

## Proposal boundary

- A playbook names recommendation-only actions, risk, and typed parameter bounds.
- A policy defaults to deny and targets exact playbook/action names.
- A proposal pins diagnosis and evidence digests, playbook and policy revisions, risk, parameters,
  creation time, expiry, identity, and revision.
- High-risk actions always begin pending and cannot be configured for automatic approval.
- Human decisions pin proposal identity/revision and record actor, reason, time, and an idempotency
  key.
- Canonical JSON and SHA-256 helpers support replay and tamper checks.
- Proposal state is explicit: pending, approved, rejected, expired, or superseded.

Approval is not execution. An application may pass an approved proposal to a separately designed
and authorized system, but that authority is outside this SDK milestone.

## Verification and learning boundary

Verification requests pin a proposal revision and declare bounded checks and deadlines. Results
are passed, failed, unknown, or timed out:

- passed requires every recorded check to pass and may promote only an explicit
  `verification_confirmed` resolution;
- failed creates a rejected truth transition and requires escalation;
- unknown and timed-out results require escalation and do not promote memory;
- human-confirmed and verification-confirmed outcomes are the only reusable truth states;
- supersession is explicit and references the newer incident.

Memory adapters persist transition history. Search can request reusable records only, filter by
truth state, and inspect lexical, filter, and truth score components.

## Replay evaluation

The public replay evaluator compares expected and observed diagnosis, escalation, and verification
values over synthetic or public fixtures. It reports exact counts and mismatched case IDs. These
metrics are regression checks, not claims of production efficacy or statistical generalization.

## Compatibility

The original `ActionPlan`, `ApprovalDecision`, `VerificationResult`, and lifecycle ports remain
available. New integrations should use the versioned proposal and verification contracts when
objects must be persisted or exchanged.

The `MemoryStore` contract adds `record_truth_transition`. Independent adapters targeting 0.0.8
must implement it. Official PostgreSQL plugin 0.1.1 implements the expanded contract.
