"""Security and normalization tests for the framework-neutral webhook adapter."""

from datetime import UTC, datetime

import pytest

from lumis_sdk.adapters.incidents import (
    InMemoryReplayGuard,
    WebhookAuthenticationError,
    WebhookConfig,
    WebhookPayloadError,
    WebhookReplayError,
    normalize_webhook,
    sign_webhook_payload,
)

NOW = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
TIMESTAMP = int(NOW.timestamp())
SECRET = "synthetic-webhook-secret"


def _config(**updates: object) -> WebhookConfig:
    return WebhookConfig(
        source_tool="fixture-webhook",
        secret_env="FIXTURE_WEBHOOK_SECRET",
        **updates,
    )


def _headers(body: bytes, **updates: str) -> dict[str, str]:
    headers = {
        "X-Lumis-Delivery": "delivery-1",
        "X-Lumis-Timestamp": str(TIMESTAMP),
        "X-Lumis-Signature": sign_webhook_payload(
            body,
            timestamp=TIMESTAMP,
            secret=SECRET,
        ),
    }
    headers.update(updates)
    return headers


def test_authenticated_webhook_normalizes_portable_incident() -> None:
    body = b'{"pipeline":{"name":"orders"},"environment":"production","status":"failed"}'

    incident = normalize_webhook(
        body,
        _headers(body),
        _config(),
        InMemoryReplayGuard(),
        environ={"FIXTURE_WEBHOOK_SECRET": SECRET},
        now=NOW,
    )

    assert incident.source_tool == "fixture-webhook"
    assert incident.pipeline_name == "orders"
    assert incident.environment == "production"
    assert incident.raw_payload["status"] == "failed"
    assert incident.raw_payload["_lumis_webhook"]["delivery_id"] == "delivery-1"


def test_webhook_rejects_invalid_signature_stale_timestamp_and_replay() -> None:
    body = b'{"pipeline_name":"orders"}'
    guard = InMemoryReplayGuard()
    headers = _headers(body)

    with pytest.raises(WebhookAuthenticationError, match="signature"):
        normalize_webhook(
            body,
            {**headers, "X-Lumis-Signature": "sha256=invalid"},
            _config(),
            guard,
            environ={"FIXTURE_WEBHOOK_SECRET": SECRET},
            now=NOW,
        )
    with pytest.raises(WebhookAuthenticationError, match="clock skew"):
        normalize_webhook(
            body,
            headers,
            _config(max_clock_skew_seconds=1),
            guard,
            environ={"FIXTURE_WEBHOOK_SECRET": SECRET},
            now=datetime(2026, 7, 16, 12, 1, tzinfo=UTC),
        )

    normalize_webhook(
        body,
        headers,
        _config(),
        guard,
        environ={"FIXTURE_WEBHOOK_SECRET": SECRET},
        now=NOW,
    )
    with pytest.raises(WebhookReplayError, match="already processed"):
        normalize_webhook(
            body,
            headers,
            _config(),
            guard,
            environ={"FIXTURE_WEBHOOK_SECRET": SECRET},
            now=NOW,
        )


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b'{"value":1,"value":2}', "duplicate key"),
        (b'["not-an-object"]', "root must be an object"),
        (b'{"_lumis_webhook":{}}', "reserved field"),
        (b'{"value":NaN}', "constant"),
    ],
)
def test_webhook_rejects_hostile_json(body: bytes, message: str) -> None:
    with pytest.raises(WebhookPayloadError, match=message):
        normalize_webhook(
            body,
            _headers(body),
            _config(),
            InMemoryReplayGuard(),
            environ={"FIXTURE_WEBHOOK_SECRET": SECRET},
            now=NOW,
        )


def test_webhook_enforces_payload_structure_and_replay_capacity() -> None:
    oversized = b'{"value":"' + (b"x" * 100) + b'"}'
    with pytest.raises(WebhookPayloadError, match="exceeds 20 bytes"):
        normalize_webhook(
            oversized,
            _headers(oversized),
            _config(max_payload_bytes=20),
            InMemoryReplayGuard(),
            environ={"FIXTURE_WEBHOOK_SECRET": SECRET},
            now=NOW,
        )

    nested = b'{"a":{"b":{"c":1}}}'
    with pytest.raises(WebhookPayloadError, match="exceeds depth 2"):
        normalize_webhook(
            nested,
            _headers(nested),
            _config(max_json_depth=2),
            InMemoryReplayGuard(),
            environ={"FIXTURE_WEBHOOK_SECRET": SECRET},
            now=NOW,
        )

    guard = InMemoryReplayGuard(max_entries=1)
    first = b'{"value":1}'
    second = b'{"value":2}'
    normalize_webhook(
        first,
        _headers(first),
        _config(),
        guard,
        environ={"FIXTURE_WEBHOOK_SECRET": SECRET},
        now=NOW,
    )
    with pytest.raises(WebhookReplayError, match="capacity"):
        normalize_webhook(
            second,
            _headers(second, **{"X-Lumis-Delivery": "delivery-2"}),
            _config(),
            guard,
            environ={"FIXTURE_WEBHOOK_SECRET": SECRET},
            now=NOW,
        )


def test_webhook_secret_reference_fails_closed() -> None:
    body = b'{"value":1}'

    with pytest.raises(WebhookAuthenticationError, match="is not set"):
        normalize_webhook(
            body,
            _headers(body),
            _config(),
            InMemoryReplayGuard(),
            environ={},
            now=NOW,
        )
