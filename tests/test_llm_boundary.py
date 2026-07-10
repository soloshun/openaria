"""Tests for the optional, provider-neutral model boundary."""

from openaria.config import DeterministicRule
from openaria.llm import ModelAssistanceConfig, ModelDiagnosisRequest, diagnose_with_optional_model
from openaria.llm.redaction import redact_text, redact_value


class FakeGateway:
    """A fixture-only gateway that captures a request and returns JSON."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.request: ModelDiagnosisRequest | None = None

    def complete_diagnosis(self, request: ModelDiagnosisRequest) -> str:
        self.request = request
        return self.response


RULE = DeterministicRule(
    name="fixture-rule",
    all_contains=["INCIDENT_SIGNATURE"],
    classification="configured_failure",
    severity="medium",
    summary="The fixture signature appeared.",
    root_cause_hypothesis="The fixture rule matched.",
    confidence=0.65,
)


def test_disabled_model_assistance_uses_deterministic_diagnosis() -> None:
    """The default path does not call a model gateway."""
    result = diagnose_with_optional_model("ERROR INCIDENT_SIGNATURE", rules=[RULE])

    assert result.triage.classification == "configured_failure"
    assert result.confidence == 0.65


def test_enabled_gateway_receives_only_redacted_log_context() -> None:
    """Secrets and email addresses are removed before a gateway receives context."""
    fixture_response = diagnose_with_optional_model(
        "ERROR INCIDENT_SIGNATURE", rules=[RULE]
    ).model_dump_json()
    gateway = FakeGateway(fixture_response)
    log_text = (
        "OPENROUTER_API_KEY=super-secret\n"
        "Authorization: Bearer another-secret\n"
        "Owner: person@example.com\n"
        "ERROR INCIDENT_SIGNATURE"
    )

    result = diagnose_with_optional_model(
        log_text,
        config=ModelAssistanceConfig(enabled=True, provider="fixture", model="fixture-model"),
        gateway=gateway,
        rules=[RULE],
    )

    assert result.triage.classification == "configured_failure"
    assert gateway.request is not None
    assert "super-secret" not in gateway.request.redacted_log
    assert "another-secret" not in gateway.request.redacted_log
    assert "person@example.com" not in gateway.request.redacted_log
    assert "[REDACTED_SECRET]" in gateway.request.redacted_log
    assert "[REDACTED_TOKEN]" in gateway.request.redacted_log
    assert "[REDACTED_EMAIL]" in gateway.request.redacted_log


def test_invalid_model_response_falls_back_to_deterministic_diagnosis() -> None:
    """Unvalidated model text never becomes an OpenARIA diagnosis."""
    result = diagnose_with_optional_model(
        "ERROR INCIDENT_SIGNATURE",
        config=ModelAssistanceConfig(enabled=True, provider="fixture", model="fixture-model"),
        gateway=FakeGateway('{"classification": "schema_change"}'),
        rules=[RULE],
    )

    assert result.triage.classification == "configured_failure"
    assert result.confidence == 0.65


def test_redaction_masks_common_values() -> None:
    """The standalone redactor documents the baseline transformations."""
    redacted = redact_text(
        "api_key=abc Bearer def person@example.com 415-555-2671 123-45-6789 "
        "4111 1111 1111 1111 ghp_abcdefghijklmnopqrstuvwxyz AKIA1234567890ABCDEF"
    )

    assert "abc" not in redacted
    assert "person@example.com" not in redacted
    assert "415-555-2671" not in redacted
    assert "123-45-6789" not in redacted
    assert "4111 1111 1111 1111" not in redacted
    assert "ghp_abcdefghijklmnopqrstuvwxyz" not in redacted
    assert "AKIA1234567890ABCDEF" not in redacted
    assert "[REDACTED_SECRET]" in redacted
    assert "[REDACTED_TOKEN]" in redacted
    assert "[REDACTED_EMAIL]" in redacted
    assert "[REDACTED_PHONE]" in redacted
    assert "[REDACTED_SSN]" in redacted
    assert "[REDACTED_CARD]" in redacted


def test_redaction_handles_nested_tool_results() -> None:
    """JSON-like context is safe to pass through the same redaction boundary."""
    value = redact_value(
        {
            "owner": "person@example.com",
            "api_key": 1234,
            "items": ["password=unsafe"],
        }
    )

    assert value == {
        "owner": "[REDACTED_EMAIL]",
        "api_key": "[REDACTED_SECRET]",
        "items": ["password=[REDACTED_SECRET]"],
    }
