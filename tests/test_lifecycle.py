"""Tests for the transport-neutral guarded lifecycle framework slice."""

from pathlib import Path

from openaria.incidents import incident_from_log
from openaria.lifecycle import (
    AllowlistedPolicyEngine,
    ApprovalDecision,
    ApprovalStatus,
    InMemoryAuditTrail,
    StaticApprovalProvider,
    StaticVerifier,
    SyntheticFinancialContextProvider,
    run_lifecycle,
)
from openaria.memory import SQLiteIncidentStore
from openaria.schemas import IncidentInput


def _schema_drift_incident() -> IncidentInput:
    return incident_from_log(
        "Pipeline: stock_feature_pipeline\nStep: transform_prices\nKeyError: 'Close'",
        "synthetic.log",
    )


def test_lifecycle_returns_context_plan_approval_verification_and_memory(tmp_path: Path) -> None:
    """One synthetic incident crosses each framework boundary without execution."""
    audit_trail = InMemoryAuditTrail()
    store = SQLiteIncidentStore(tmp_path / "incidents.db")
    result = run_lifecycle(
        _schema_drift_incident(),
        context_provider=SyntheticFinancialContextProvider(),
        policy_engine=AllowlistedPolicyEngine(),
        approval_provider=StaticApprovalProvider(
            ApprovalDecision(
                status=ApprovalStatus.APPROVED,
                approver="demo-engineer",
                reason="Synthetic approval for the paper demo.",
            )
        ),
        verifier=StaticVerifier(),
        audit_trail=audit_trail,
        memory_store=store,
        report_path=tmp_path / "lifecycle-report.md",
    )

    assert len(result.context.items) == 6
    assert result.action_plan.playbook_name == "schema_mismatch_in_dataframe"
    assert result.action_plan.execution_allowed is False
    assert result.approval.status is ApprovalStatus.APPROVED
    assert result.verification.status.value == "not_run"
    assert result.stored_incident_id is not None
    assert store.get(result.stored_incident_id).diagnosis.triage.classification == "schema_change"
    assert [event.event_type for event in result.audit_events] == [
        "context_retrieved",
        "diagnosis_completed",
        "plan_proposed",
        "approval_recorded",
        "verification_recorded",
        "memory_updated",
    ]


def test_rejected_approval_skips_verification() -> None:
    """A rejected plan cannot advance to a simulated recovery result."""
    audit_trail = InMemoryAuditTrail()
    result = run_lifecycle(
        _schema_drift_incident(),
        context_provider=SyntheticFinancialContextProvider(),
        policy_engine=AllowlistedPolicyEngine(),
        approval_provider=StaticApprovalProvider(ApprovalDecision(status=ApprovalStatus.REJECTED)),
        verifier=StaticVerifier(),
        audit_trail=audit_trail,
    )

    assert result.verification.status.value == "skipped"
