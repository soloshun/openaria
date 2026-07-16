"""Deterministic synthetic replay evaluation for public SDK behavior."""

from pydantic import Field

from lumis_sdk.domain.models import DomainModel


class ReplayCase(DomainModel):
    """One synthetic expected-vs-observed lifecycle outcome."""

    id: str
    expected_diagnosis: str
    observed_diagnosis: str
    expected_escalation: bool
    observed_escalation: bool
    expected_verification: str
    observed_verification: str


class ReplayMetrics(DomainModel):
    """Transparent exact-match metrics without statistical overclaiming."""

    total: int = Field(ge=0)
    diagnosis_matches: int = Field(ge=0)
    escalation_matches: int = Field(ge=0)
    verification_matches: int = Field(ge=0)
    fully_matching_cases: int = Field(ge=0)
    mismatched_case_ids: list[str] = Field(default_factory=list)


def evaluate_replay(cases: list[ReplayCase]) -> ReplayMetrics:
    """Evaluate a bounded in-memory replay corpus deterministically."""
    diagnosis_matches = 0
    escalation_matches = 0
    verification_matches = 0
    fully_matching = 0
    mismatches: list[str] = []
    for case in cases:
        diagnosis_ok = case.expected_diagnosis == case.observed_diagnosis
        escalation_ok = case.expected_escalation == case.observed_escalation
        verification_ok = case.expected_verification == case.observed_verification
        diagnosis_matches += int(diagnosis_ok)
        escalation_matches += int(escalation_ok)
        verification_matches += int(verification_ok)
        if diagnosis_ok and escalation_ok and verification_ok:
            fully_matching += 1
        else:
            mismatches.append(case.id)
    return ReplayMetrics(
        total=len(cases),
        diagnosis_matches=diagnosis_matches,
        escalation_matches=escalation_matches,
        verification_matches=verification_matches,
        fully_matching_cases=fully_matching,
        mismatched_case_ids=mismatches,
    )
