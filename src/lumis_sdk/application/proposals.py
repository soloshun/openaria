"""Deterministic proposal evaluation without action execution."""

from datetime import datetime

from lumis_sdk.domain.policy import (
    ActionProposal,
    ApprovalDecisionRecord,
    DecisionStatus,
    EvidenceReference,
    PlaybookDocument,
    PolicyDocument,
    ProposalState,
)
from lumis_sdk.domain.recovery import RiskLevel

_RISK_ORDER = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}


class ProposalPolicyError(ValueError):
    """Raised when an action is not explicitly allowed or fails validation."""


class DecisionConflictError(ValueError):
    """Raised when an idempotency key is reused for a different decision."""


class ProposalService:
    """Create immutable proposal revisions from pinned playbook and policy documents."""

    def __init__(self, playbook: PlaybookDocument, policy: PolicyDocument) -> None:
        self.playbook = playbook
        self.policy = policy

    def propose(
        self,
        *,
        proposal_id: str,
        diagnosis_id: str,
        diagnosis_digest: str,
        evidence: list[EvidenceReference],
        action_name: str,
        parameters: dict[str, str | int | float | bool],
        created_at: datetime,
        expires_at: datetime,
        revision: int = 1,
    ) -> ActionProposal:
        """Validate an allowlisted action and return a recommendation-only proposal."""
        action = next(
            (candidate for candidate in self.playbook.actions if candidate.name == action_name),
            None,
        )
        if action is None:
            raise ProposalPolicyError(f"unknown playbook action {action_name!r}")
        rule = next(
            (
                candidate
                for candidate in self.policy.rules
                if candidate.playbook_name == self.playbook.metadata.name
                and candidate.action_name == action_name
            ),
            None,
        )
        if rule is None:
            raise ProposalPolicyError("no policy rule explicitly allows this playbook action")
        definitions = {definition.name: definition for definition in action.parameters}
        unknown = sorted(set(parameters) - set(definitions))
        if unknown:
            raise ProposalPolicyError(f"unknown action parameters: {', '.join(unknown)}")
        missing = sorted(
            name
            for name, definition in definitions.items()
            if definition.required and name not in parameters
        )
        if missing:
            raise ProposalPolicyError(f"missing required action parameters: {', '.join(missing)}")
        for name, value in parameters.items():
            try:
                definitions[name].validate_value(value)
            except ValueError as error:
                raise ProposalPolicyError(str(error)) from error

        auto_approved = (
            action.risk is not RiskLevel.HIGH
            and not rule.approval_required
            and rule.auto_approve_up_to is not None
            and _RISK_ORDER[action.risk] <= _RISK_ORDER[rule.auto_approve_up_to]
        )
        return ActionProposal(
            proposal_id=proposal_id,
            revision=revision,
            state=ProposalState.APPROVED if auto_approved else ProposalState.PENDING,
            diagnosis_id=diagnosis_id,
            diagnosis_digest=diagnosis_digest,
            evidence=evidence,
            playbook_name=self.playbook.metadata.name,
            playbook_version=self.playbook.metadata.version,
            action_name=action.name,
            policy_name=self.policy.metadata.name,
            policy_version=self.policy.metadata.version,
            risk=action.risk,
            parameters=parameters,
            approval_required=not auto_approved,
            created_at=created_at,
            expires_at=expires_at,
        )


class ApprovalLedger:
    """In-memory reference ledger demonstrating idempotent decision semantics."""

    def __init__(self) -> None:
        self._decisions: dict[str, ApprovalDecisionRecord] = {}

    def apply(
        self,
        proposal: ActionProposal,
        decision: ApprovalDecisionRecord,
        *,
        now: datetime,
    ) -> ActionProposal:
        """Apply one human decision or replay it idempotently."""
        if decision.proposal_id != proposal.proposal_id:
            raise DecisionConflictError("decision proposal_id does not match the proposal")
        if decision.proposal_revision != proposal.revision:
            raise DecisionConflictError("decision targets a different proposal revision")
        existing = self._decisions.get(decision.decision_id)
        if existing is not None:
            if existing != decision:
                raise DecisionConflictError("decision_id already stores a different decision")
        else:
            self._decisions[decision.decision_id] = decision
        if now >= proposal.expires_at:
            return proposal.model_copy(update={"state": ProposalState.EXPIRED})
        if proposal.state not in {ProposalState.PENDING, ProposalState.APPROVED}:
            raise DecisionConflictError(f"cannot decide a {proposal.state.value} proposal")
        state = (
            ProposalState.APPROVED
            if decision.status is DecisionStatus.APPROVED
            else ProposalState.REJECTED
        )
        return proposal.model_copy(update={"state": state})
