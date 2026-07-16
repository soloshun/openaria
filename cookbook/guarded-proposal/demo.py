"""Offline proposal and human-decision demo; it intentionally performs no action."""

from datetime import UTC, datetime, timedelta

from lumis_sdk.application import ApprovalLedger, ProposalService
from lumis_sdk.domain import (
    ApprovalDecisionRecord,
    DecisionStatus,
    DocumentMetadata,
    EvidenceReference,
    ParameterDefinition,
    ParameterType,
    PlaybookAction,
    PlaybookDocument,
    PolicyDocument,
    PolicyRule,
    RiskLevel,
)

now = datetime.now(UTC)
service = ProposalService(
    PlaybookDocument(
        metadata=DocumentMetadata(name="synthetic-worker", version="1"),
        actions=[
            PlaybookAction(
                name="restart",
                summary="Recommend restarting at most two synthetic workers.",
                risk=RiskLevel.HIGH,
                parameters=[
                    ParameterDefinition(
                        name="replicas",
                        type=ParameterType.INTEGER,
                        minimum=1,
                        maximum=2,
                    )
                ],
            )
        ],
    ),
    PolicyDocument(
        metadata=DocumentMetadata(name="synthetic-policy", version="1"),
        rules=[
            PolicyRule(
                playbook_name="synthetic-worker",
                action_name="restart",
                approval_required=True,
            )
        ],
    ),
)
proposal = service.propose(
    proposal_id="proposal-synthetic-1",
    diagnosis_id="diagnosis-synthetic-1",
    diagnosis_digest="a" * 64,
    evidence=[EvidenceReference(id="fixture-log", source="fixture", digest="b" * 64)],
    action_name="restart",
    parameters={"replicas": 1},
    created_at=now,
    expires_at=now + timedelta(minutes=10),
)
decision = ApprovalDecisionRecord(
    decision_id="decision-synthetic-1",
    proposal_id=proposal.proposal_id,
    proposal_revision=proposal.revision,
    status=DecisionStatus.APPROVED,
    actor="synthetic-reviewer",
    reason="Fixture evidence and bounded impact were reviewed.",
    decided_at=now,
)
approved = ApprovalLedger().apply(proposal, decision, now=now)
print(approved.model_dump_json(indent=2))
assert approved.execution_allowed is False
