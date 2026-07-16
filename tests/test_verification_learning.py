"""Tests for conservative verification, truth transitions, and replay evaluation."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from lumis_sdk.adapters.sqlite import SQLiteMemoryStore
from lumis_sdk.application import learn_from_verification
from lumis_sdk.domain import (
    CheckOutcome,
    ConfirmedResolution,
    TruthState,
    VerificationCheck,
    VerificationOutcome,
    VerificationRecord,
)
from lumis_sdk.evaluation import ReplayCase, evaluate_replay
from lumis_sdk.ports import MemoryQuery
from lumis_sdk.testkit import make_test_episode


def _record(outcome: VerificationOutcome) -> VerificationRecord:
    check_outcome = {
        VerificationOutcome.PASSED: CheckOutcome.PASSED,
        VerificationOutcome.FAILED: CheckOutcome.FAILED,
        VerificationOutcome.UNKNOWN: CheckOutcome.UNKNOWN,
        VerificationOutcome.TIMED_OUT: CheckOutcome.UNKNOWN,
    }[outcome]
    return VerificationRecord(
        verification_id=f"verification-{outcome.value}",
        incident_id="11111111-1111-4111-8111-111111111111",
        proposal_id="proposal-1",
        proposal_revision=1,
        outcome=outcome,
        checks=[
            VerificationCheck(
                name="pipeline-health",
                outcome=check_outcome,
                detail=f"Synthetic {outcome.value} result.",
            )
        ],
        verifier="fixture-verifier",
        completed_at=datetime(2026, 7, 16, tzinfo=UTC),
        escalation_required=outcome is not VerificationOutcome.PASSED,
    )


def test_passed_verification_promotes_only_an_explicit_resolution(tmp_path: Path) -> None:
    async def exercise() -> None:
        store = SQLiteMemoryStore(tmp_path / "memory.db")
        await store.save_incident(make_test_episode())
        record = _record(VerificationOutcome.PASSED)
        resolution = ConfirmedResolution(
            incident_id=UUID(record.incident_id),
            confirmed_root_cause="Synthetic dependency failure.",
            action_taken="Recommended bounded restart was performed externally.",
            outcome="Health check passed.",
            verified=True,
            confirmed_by="fixture-verifier",
            confirmed_at=record.completed_at,
            truth_state=TruthState.VERIFICATION_CONFIRMED,
            verification_id=record.verification_id,
        )
        result = await learn_from_verification(
            store,
            record,
            current_state=TruthState.UNCONFIRMED_HYPOTHESIS,
            resolution=resolution,
        )
        assert result.reusable is True
        matches = await store.search(MemoryQuery(text="health", reusable_only=True))
        assert matches[0].episode.truth_state is TruthState.VERIFICATION_CONFIRMED

    asyncio.run(exercise())


def test_failed_verification_is_rejected_and_unknown_is_not_promoted(tmp_path: Path) -> None:
    async def exercise() -> None:
        failed_store = SQLiteMemoryStore(tmp_path / "failed.db")
        await failed_store.save_incident(make_test_episode())
        failed = await learn_from_verification(
            failed_store,
            _record(VerificationOutcome.FAILED),
            current_state=TruthState.UNCONFIRMED_HYPOTHESIS,
        )
        assert failed.truth_state is TruthState.REJECTED
        assert (
            await failed_store.search(MemoryQuery(text="TESTKIT_SIGNATURE", reusable_only=True))
            == []
        )

        unknown_store = SQLiteMemoryStore(tmp_path / "unknown.db")
        await unknown_store.save_incident(make_test_episode())
        unknown = await learn_from_verification(
            unknown_store,
            _record(VerificationOutcome.UNKNOWN),
            current_state=TruthState.UNCONFIRMED_HYPOTHESIS,
        )
        assert unknown.truth_state is TruthState.UNCONFIRMED_HYPOTHESIS
        assert unknown.escalation_required is True

    asyncio.run(exercise())


def test_replay_metrics_are_exact_and_deterministic() -> None:
    metrics = evaluate_replay(
        [
            ReplayCase(
                id="case-pass",
                expected_diagnosis="schema_drift",
                observed_diagnosis="schema_drift",
                expected_escalation=False,
                observed_escalation=False,
                expected_verification="passed",
                observed_verification="passed",
            ),
            ReplayCase(
                id="case-mismatch",
                expected_diagnosis="dependency_failure",
                observed_diagnosis="unknown",
                expected_escalation=True,
                observed_escalation=True,
                expected_verification="unknown",
                observed_verification="unknown",
            ),
        ]
    )
    assert metrics.total == 2
    assert metrics.fully_matching_cases == 1
    assert metrics.mismatched_case_ids == ["case-mismatch"]
