"""Typed, transport-neutral models for an OpenARIA incident lifecycle."""

from enum import StrEnum

from pydantic import BaseModel, Field

from openaria.schemas import DiagnosisResult, IncidentInput


class ContextKind(StrEnum):
    """The categories of evidence a context provider may expose."""

    LOGS = "logs"
    METRICS = "metrics"
    LINEAGE = "lineage"
    SCHEMA = "schema"
    RUNBOOK = "runbook"
    PLAYBOOK = "playbook"


class ContextItem(BaseModel):
    """One bounded piece of context for an incident."""

    id: str
    kind: ContextKind
    source: str
    content: str


class IncidentContext(BaseModel):
    """The evidence returned by a context provider for one incident."""

    incident: IncidentInput
    items: list[ContextItem] = Field(default_factory=list)


class RiskLevel(StrEnum):
    """The risk tier assigned to a proposed action."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ActionPlan(BaseModel):
    """A recommendation-only plan selected from an allowlisted playbook."""

    playbook_name: str
    risk_level: RiskLevel
    approval_required: bool
    summary: str
    steps: list[str] = Field(default_factory=list)
    execution_allowed: bool = False


class ApprovalStatus(StrEnum):
    """The result of an explicit approval decision."""

    APPROVED = "approved"
    REJECTED = "rejected"
    PENDING = "pending"


class ApprovalDecision(BaseModel):
    """A recorded approval decision for a proposed action plan."""

    status: ApprovalStatus
    approver: str | None = None
    reason: str | None = None


class VerificationStatus(StrEnum):
    """The state of a verification check."""

    NOT_RUN = "not_run"
    SKIPPED = "skipped"
    PASSED = "passed"
    FAILED = "failed"


class VerificationResult(BaseModel):
    """A bounded result from a verification provider."""

    status: VerificationStatus
    checks: list[str] = Field(default_factory=list)
    notes: str


class AuditEvent(BaseModel):
    """A local, inspectable record of one lifecycle transition."""

    event_type: str
    detail: str


class LifecycleResult(BaseModel):
    """The complete output of one non-executing OpenARIA lifecycle run."""

    incident: IncidentInput
    context: IncidentContext
    diagnosis: DiagnosisResult
    action_plan: ActionPlan
    approval: ApprovalDecision
    verification: VerificationResult
    audit_events: list[AuditEvent] = Field(default_factory=list)
    stored_incident_id: str | None = None
