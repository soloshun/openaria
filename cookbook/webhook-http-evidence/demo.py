"""Offline generic webhook and independently packaged evidence-connector proof."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import httpx
from lumis_http_json_evidence import HttpJsonEvidencePlugin

from lumis_sdk.adapters.incidents import (
    InMemoryReplayGuard,
    WebhookConfig,
    normalize_webhook,
    sign_webhook_payload,
)
from lumis_sdk.application import EvidenceService
from lumis_sdk.config import HttpJsonEvidenceProviderConfig, load_config
from lumis_sdk.domain import EvidenceRequest

ROOT = Path(__file__).parent
NOW = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
WEBHOOK_SECRET = "offline-webhook-secret"


def fixture_transport(request: httpx.Request) -> httpx.Response:
    """Return a local fixture while still exercising HTTP request composition."""
    assert request.url == "https://evidence.example.test/v1/evidence"
    return httpx.Response(
        200,
        content=(ROOT / "evidence-response.json").read_bytes(),
        headers={"Content-Type": "application/json"},
    )


async def main() -> None:
    body = (ROOT / "webhook.json").read_bytes()
    timestamp = int(NOW.timestamp())
    incident = normalize_webhook(
        body,
        {
            "X-Lumis-Delivery": "offline-delivery-1",
            "X-Lumis-Timestamp": str(timestamp),
            "X-Lumis-Signature": sign_webhook_payload(
                body,
                timestamp=timestamp,
                secret=WEBHOOK_SECRET,
            ),
        },
        WebhookConfig(
            source_tool="offline-webhook",
            secret_env="LUMIS_WEBHOOK_SECRET",
        ),
        InMemoryReplayGuard(),
        environ={"LUMIS_WEBHOOK_SECRET": WEBHOOK_SECRET},
        now=NOW,
    )

    project = load_config(ROOT / "lumis.yml")
    provider_config = project.evidence_providers[0]
    if not isinstance(provider_config, HttpJsonEvidenceProviderConfig):
        raise SystemExit("cookbook requires provider: http-json")
    provider = HttpJsonEvidencePlugin().create(
        provider_config,
        environ={"LUMIS_EVIDENCE_TOKEN": "offline-token"},
        transport=httpx.MockTransport(fixture_transport),
    )
    collection = await EvidenceService(
        provider,
        timeout_seconds=provider_config.timeout_seconds,
    ).collect(
        EvidenceRequest(
            incident=incident,
            kinds=provider_config.kinds,
            max_items=provider_config.max_items,
            max_total_characters=provider_config.max_total_characters,
            max_item_characters=provider_config.max_item_characters,
            redact=provider_config.redact,
        )
    )
    print(
        f"incident={incident.pipeline_name} evidence={len(collection.items)} "
        f"detail={collection.items[0].detail}"
    )


if __name__ == "__main__":
    asyncio.run(main())
