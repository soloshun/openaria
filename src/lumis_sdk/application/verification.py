"""Verification-aware learning services with conservative truth promotion."""

from dataclasses import dataclass

from lumis_sdk.domain import ConfirmedResolution, TruthState
from lumis_sdk.domain.verification import TruthTransition, VerificationOutcome, VerificationRecord
from lumis_sdk.ports.memory import MemoryStore


@dataclass(frozen=True)
class LearningResult:
    """Outcome of applying one verification record to operational memory."""

    truth_state: TruthState
    reusable: bool
    escalation_required: bool


async def learn_from_verification(
    store: MemoryStore,
    record: VerificationRecord,
    *,
    current_state: TruthState,
    resolution: ConfirmedResolution | None = None,
) -> LearningResult:
    """Persist verified truth, reject failed claims, and never promote unknown outcomes."""
    transition = TruthTransition.for_verification(record, from_state=current_state)
    if record.outcome is VerificationOutcome.PASSED:
        if resolution is None:
            raise ValueError("passed verification requires an explicit confirmed resolution")
        if not resolution.verified:
            raise ValueError("verification-confirmed resolution must set verified=true")
        if resolution.truth_state is not TruthState.VERIFICATION_CONFIRMED:
            raise ValueError("passed verification requires verification_confirmed truth")
        if str(resolution.incident_id) != record.incident_id:
            raise ValueError("resolution incident_id must match verification incident_id")
        await store.record_resolution(resolution)
        return LearningResult(TruthState.VERIFICATION_CONFIRMED, True, False)
    if transition is not None:
        await store.record_truth_transition(transition)
        return LearningResult(transition.to_state, False, True)
    return LearningResult(current_state, False, True)
