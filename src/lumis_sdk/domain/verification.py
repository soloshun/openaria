"""Explicit verification and truth-transition contracts."""

import hashlib
from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from .models import DomainModel, TruthState


class VerificationOutcome(StrEnum):
    """Conservative result of bounded verification."""

    PASSED = "passed"
    FAILED = "failed"
    UNKNOWN = "unknown"
    TIMED_OUT = "timed_out"


class CheckOutcome(StrEnum):
    """Result of one declared verification check."""

    PASSED = "passed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class VerificationRequest(DomainModel):
    """Bounded request pinned to one proposal revision."""

    verification_id: str = Field(min_length=1, max_length=200)
    incident_id: str = Field(min_length=1, max_length=200)
    proposal_id: str = Field(min_length=1, max_length=200)
    proposal_revision: int = Field(ge=1)
    checks: list[str] = Field(min_length=1, max_length=100)
    requested_at: datetime
    deadline: datetime

    @model_validator(mode="after")
    def validate_deadline(self) -> "VerificationRequest":
        if self.deadline <= self.requested_at:
            raise ValueError("verification deadline must be after requested_at")
        if len(self.checks) != len(set(self.checks)):
            raise ValueError("verification check names must be unique")
        return self


class VerificationCheck(DomainModel):
    """One inspectable verification observation."""

    name: str = Field(min_length=1, max_length=200)
    outcome: CheckOutcome
    detail: str = Field(min_length=1, max_length=2_000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)


class VerificationRecord(DomainModel):
    """Persistable verification result with explicit escalation behavior."""

    verification_id: str
    incident_id: str
    proposal_id: str
    proposal_revision: int = Field(ge=1)
    outcome: VerificationOutcome
    checks: list[VerificationCheck] = Field(default_factory=list, max_length=100)
    verifier: str = Field(min_length=1, max_length=200)
    completed_at: datetime
    escalation_required: bool

    @model_validator(mode="after")
    def fail_closed(self) -> "VerificationRecord":
        if self.outcome is VerificationOutcome.PASSED:
            if self.escalation_required:
                raise ValueError("passed verification cannot require escalation")
            if not self.checks or any(
                check.outcome is not CheckOutcome.PASSED for check in self.checks
            ):
                raise ValueError("passed verification requires all declared checks to pass")
        elif not self.escalation_required:
            raise ValueError("failed, unknown, and timed-out verification must escalate")
        return self


class TruthTransition(DomainModel):
    """Auditable idempotent transition for retained operational knowledge."""

    transition_id: str = Field(min_length=1, max_length=200)
    incident_id: str = Field(min_length=1, max_length=200)
    from_state: TruthState
    to_state: TruthState
    actor: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2_000)
    recorded_at: datetime
    verification_id: str | None = None
    supersedes_incident_id: str | None = None

    @model_validator(mode="after")
    def validate_transition(self) -> "TruthTransition":
        allowed = {
            TruthState.UNCONFIRMED_HYPOTHESIS: {
                TruthState.HUMAN_CONFIRMED,
                TruthState.VERIFICATION_CONFIRMED,
                TruthState.REJECTED,
                TruthState.SUPERSEDED,
            },
            TruthState.HUMAN_CONFIRMED: {TruthState.SUPERSEDED},
            TruthState.VERIFICATION_CONFIRMED: {TruthState.SUPERSEDED},
            TruthState.REJECTED: {TruthState.SUPERSEDED},
            TruthState.SUPERSEDED: set(),
        }
        if self.to_state not in allowed[self.from_state]:
            raise ValueError(
                f"invalid truth transition: {self.from_state.value} -> {self.to_state.value}"
            )
        if self.to_state is TruthState.VERIFICATION_CONFIRMED and not self.verification_id:
            raise ValueError("verification-confirmed truth requires verification_id")
        if self.to_state is TruthState.SUPERSEDED and not self.supersedes_incident_id:
            raise ValueError("superseded truth requires supersedes_incident_id")
        return self

    @classmethod
    def for_verification(
        cls,
        record: VerificationRecord,
        *,
        from_state: TruthState,
    ) -> "TruthTransition | None":
        """Map verification to truth conservatively; unknown outcomes remain unconfirmed."""
        if record.outcome in {VerificationOutcome.UNKNOWN, VerificationOutcome.TIMED_OUT}:
            return None
        to_state = (
            TruthState.VERIFICATION_CONFIRMED
            if record.outcome is VerificationOutcome.PASSED
            else TruthState.REJECTED
        )
        identity = (
            f"{record.verification_id}:{record.incident_id}:{from_state.value}:{to_state.value}"
        )
        transition_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        return cls(
            transition_id=transition_id,
            incident_id=record.incident_id,
            from_state=from_state,
            to_state=to_state,
            actor=record.verifier,
            reason=f"verification outcome: {record.outcome.value}",
            recorded_at=record.completed_at,
            verification_id=record.verification_id,
        )

    @classmethod
    def for_resolution(cls, resolution_id: str, *, resolution: object) -> "TruthTransition":
        """Build the audit transition represented by a validated confirmed resolution."""
        from .models import ConfirmedResolution

        if not isinstance(resolution, ConfirmedResolution):
            raise TypeError("resolution must be a ConfirmedResolution")
        from_state = TruthState.UNCONFIRMED_HYPOTHESIS
        identity = (
            f"{resolution_id}:{resolution.incident_id}:{from_state.value}:"
            f"{resolution.truth_state.value}"
        )
        return cls(
            transition_id=hashlib.sha256(identity.encode("utf-8")).hexdigest(),
            incident_id=str(resolution.incident_id),
            from_state=from_state,
            to_state=resolution.truth_state,
            actor=resolution.confirmed_by,
            reason=f"explicit confirmed resolution: {resolution.outcome}",
            recorded_at=resolution.confirmed_at,
            verification_id=resolution.verification_id,
        )
