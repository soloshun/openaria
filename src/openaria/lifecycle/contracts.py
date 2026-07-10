"""Provider contracts for the OpenARIA framework lifecycle."""

from typing import Protocol

from openaria.lifecycle.models import (
    ActionPlan,
    ApprovalDecision,
    AuditEvent,
    IncidentContext,
    VerificationResult,
)
from openaria.schemas import DiagnosisResult, IncidentInput


class ContextProvider(Protocol):
    """Retrieve bounded evidence for an incident."""

    def get_context(self, incident: IncidentInput) -> IncidentContext:
        """Return context without mutating the incident estate."""
        ...


class PolicyEngine(Protocol):
    """Select a recommendation-only action plan from allowed playbooks."""

    def propose(self, diagnosis: DiagnosisResult, context: IncidentContext) -> ActionPlan:
        """Return an allowlisted action plan without executing it."""
        ...


class ApprovalProvider(Protocol):
    """Record an approval decision for a proposed plan."""

    def request(self, plan: ActionPlan) -> ApprovalDecision:
        """Return an explicit approval state."""
        ...


class Verifier(Protocol):
    """Return a verification result without performing remediation."""

    def verify(self, plan: ActionPlan, approval: ApprovalDecision) -> VerificationResult:
        """Return the result of a bounded verification check."""
        ...


class AuditTrail(Protocol):
    """Record lifecycle transitions for local inspection."""

    def record(self, event: AuditEvent) -> None:
        """Record one audit event."""
        ...
