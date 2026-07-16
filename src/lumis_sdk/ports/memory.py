"""Incident-memory port independent of SQLite, Postgres, or hosted products."""

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from lumis_sdk.domain import (
    ConfirmedResolution,
    DiagnosisResult,
    IncidentInput,
    TruthState,
    TruthTransition,
)


class MemoryConflictError(Exception):
    """Raised when an idempotency key is reused for different memory content."""


class MemoryIncidentNotFoundError(Exception):
    """Raised when a resolution targets an incident absent from memory."""


class MemoryPortModel(BaseModel):
    """Strict base for memory contracts."""

    model_config = ConfigDict(extra="forbid")


class IncidentEpisode(MemoryPortModel):
    """Portable memory record with an explicit truth state."""

    incident_id: str
    incident: IncidentInput
    diagnosis: DiagnosisResult
    truth_state: TruthState = TruthState.UNCONFIRMED_HYPOTHESIS
    resolution: ConfirmedResolution | None = None
    truth_transitions: list[TruthTransition] = Field(default_factory=list)
    superseded_by_incident_id: str | None = None

    @model_validator(mode="after")
    def require_consistent_explicit_truth(self) -> "IncidentEpisode":
        if self.resolution is None:
            if self.truth_state in {
                TruthState.HUMAN_CONFIRMED,
                TruthState.VERIFICATION_CONFIRMED,
            }:
                raise ValueError("a confirmed truth state requires an explicit resolution")
        else:
            if str(self.resolution.incident_id) != self.incident_id:
                raise ValueError("resolution incident_id must match the episode incident_id")
            resolution_may_be_superseded = (
                self.truth_state is TruthState.SUPERSEDED
                and self.resolution.truth_state
                in {TruthState.HUMAN_CONFIRMED, TruthState.VERIFICATION_CONFIRMED}
            )
            if self.resolution.truth_state != self.truth_state and not resolution_may_be_superseded:
                raise ValueError("resolution and episode truth states must match")
        if self.truth_transitions:
            if any(
                transition.incident_id != self.incident_id for transition in self.truth_transitions
            ):
                raise ValueError("truth transitions must target the episode incident_id")
            if self.truth_transitions[-1].to_state != self.truth_state:
                raise ValueError("latest truth transition must match the episode truth state")
        if self.truth_state is TruthState.SUPERSEDED and not self.superseded_by_incident_id:
            raise ValueError("superseded episodes require superseded_by_incident_id")
        return self


class MemoryQuery(MemoryPortModel):
    """Transparent structured and lexical memory query."""

    text: str
    classification: str | None = None
    pipeline_name: str | None = None
    truth_states: list[TruthState] = Field(default_factory=list)
    reusable_only: bool = False
    limit: int = Field(default=10, ge=1, le=100)


class MemoryMatch(MemoryPortModel):
    """A ranked memory result with human-readable scoring reasons."""

    episode: IncidentEpisode
    score: float = Field(ge=0)
    reasons: list[str] = Field(default_factory=list)
    score_components: dict[str, float] = Field(default_factory=dict)


class MemoryStore(Protocol):
    """Persist and retrieve incident knowledge behind a replaceable adapter."""

    async def save_incident(self, incident: IncidentEpisode) -> None:
        """Store one incident episode without changing its truth state."""
        ...

    async def record_resolution(self, resolution: ConfirmedResolution) -> None:
        """Record an explicitly confirmed resolution."""
        ...

    async def record_truth_transition(self, transition: TruthTransition) -> None:
        """Persist an explicit rejection or supersession idempotently."""
        ...

    async def search(self, query: MemoryQuery) -> list[MemoryMatch]:
        """Return ranked matches with transparent reasons."""
        ...
