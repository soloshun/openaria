"""Synthetic implementations used to exercise framework lifecycle contracts."""

from openaria.lifecycle.models import (
    ActionPlan,
    ApprovalDecision,
    ApprovalStatus,
    AuditEvent,
    ContextItem,
    ContextKind,
    IncidentContext,
    RiskLevel,
    VerificationResult,
    VerificationStatus,
)
from openaria.schemas import DiagnosisResult, IncidentInput


class SyntheticFinancialContextProvider:
    """Return a fixed, clean-room context pack for a schema-drift incident."""

    def get_context(self, incident: IncidentInput) -> IncidentContext:
        """Provide synthetic logs, telemetry, lineage, and operational knowledge."""
        return IncidentContext(
            incident=incident,
            items=[
                ContextItem(
                    id="CTX-LOG-1",
                    kind=ContextKind.LOGS,
                    source="synthetic_pipeline_log",
                    content="transform_prices failed with KeyError: 'Close'",
                ),
                ContextItem(
                    id="CTX-METRIC-1",
                    kind=ContextKind.METRICS,
                    source="synthetic_metrics",
                    content="stock_feature_pipeline failure_count=1; last_success_age_minutes=1440",
                ),
                ContextItem(
                    id="CTX-SCHEMA-1",
                    kind=ContextKind.SCHEMA,
                    source="synthetic_schema_snapshot",
                    content=(
                        "expected: Date, Open, High, Low, Close, Volume; current: Date, Open, "
                        "High, Low, closing_price, Volume"
                    ),
                ),
                ContextItem(
                    id="CTX-LINEAGE-1",
                    kind=ContextKind.LINEAGE,
                    source="synthetic_lineage_snapshot",
                    content=(
                        "upstream: yfinance_extract; downstream: moving_average_features, "
                        "daily_stock_dashboard"
                    ),
                ),
                ContextItem(
                    id="CTX-RUNBOOK-1",
                    kind=ContextKind.RUNBOOK,
                    source="synthetic_runbook",
                    content=(
                        "Compare current schema with the last successful run "
                        "before changing a mapping."
                    ),
                ),
                ContextItem(
                    id="CTX-PLAYBOOK-1",
                    kind=ContextKind.PLAYBOOK,
                    source="synthetic_playbook_library",
                    content=(
                        "schema_mismatch_in_dataframe is recommendation-only and requires approval."
                    ),
                ),
            ],
        )


class AllowlistedPolicyEngine:
    """Map known diagnoses to safe, recommendation-only playbooks."""

    def propose(self, diagnosis: DiagnosisResult, context: IncidentContext) -> ActionPlan:
        """Select only an allowlisted plan; never expose an executable action."""
        if diagnosis.triage.classification == "schema_change":
            return ActionPlan(
                playbook_name="schema_mismatch_in_dataframe",
                risk_level=RiskLevel.MEDIUM,
                approval_required=True,
                summary=(
                    "Review the source-schema change and prepare a mapping update for human review."
                ),
                steps=[
                    "Compare the current schema with the last successful schema.",
                    "Confirm whether closing_price is the intended replacement for Close.",
                    "Prepare a reviewable mapping change if the replacement is confirmed.",
                ],
            )

        return ActionPlan(
            playbook_name="investigate_with_human",
            risk_level=RiskLevel.HIGH,
            approval_required=True,
            summary=(
                "No allowlisted remediation applies; escalate the completed "
                "investigation to a human."
            ),
            steps=["Collect additional context and assign the incident to an engineer."],
        )


class StaticApprovalProvider:
    """Return an explicit fixture decision for tests and future cookbook adapters."""

    def __init__(self, decision: ApprovalDecision) -> None:
        self.decision = decision

    def request(self, plan: ActionPlan) -> ApprovalDecision:
        """Record the supplied fixture decision without changing any system."""
        return self.decision


class StaticVerifier:
    """Return a safe synthetic result because the core has not executed an action."""

    def verify(self, plan: ActionPlan, approval: ApprovalDecision) -> VerificationResult:
        """Make non-execution explicit in the verification record."""
        if approval.status is ApprovalStatus.REJECTED:
            return VerificationResult(
                status=VerificationStatus.SKIPPED,
                checks=["No action was approved."],
                notes="Verification was skipped because the proposed plan was rejected.",
            )
        return VerificationResult(
            status=VerificationStatus.NOT_RUN,
            checks=["No remediation action is available in OpenARIA core."],
            notes=(
                "The plan is recommendation-only; a later adapter may perform guarded verification."
            ),
        )


class InMemoryAuditTrail:
    """Collect audit events for tests and cookbook demonstrations."""

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> None:
        """Store one event in process memory."""
        self.events.append(event)
