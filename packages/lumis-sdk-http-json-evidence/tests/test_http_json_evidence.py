"""Offline transport and plugin contracts for the HTTP JSON evidence connector."""

import asyncio
import json

import httpx
import pytest
from lumis_http_json_evidence import (
    MANIFEST,
    HttpJsonEvidencePlugin,
    HttpJsonEvidenceProvider,
    create_plugin,
)

from lumis_sdk.application import EvidenceService
from lumis_sdk.config import HttpJsonEvidenceProviderConfig
from lumis_sdk.domain import EvidenceRequest, PluginAuthority, PluginCapability
from lumis_sdk.testkit import (
    assert_evidence_collection_contract,
    assert_plugin_factory_contract,
    make_test_incident,
)


def _config(**updates: object) -> HttpJsonEvidenceProviderConfig:
    values = {
        "provider": "http-json",
        "url": "https://evidence.example.test/v1/evidence",
        "allowedOrigins": ["https://evidence.example.test"],
        "tokenEnv": "FIXTURE_EVIDENCE_TOKEN",
        "maxResponseBytes": 10_000,
        **updates,
    }
    return HttpJsonEvidenceProviderConfig.model_validate(
        values,
    )


def test_manifest_and_factory_declare_optional_authorities() -> None:
    assert MANIFEST.spec.capabilities == [PluginCapability.EVIDENCE_PROVIDER]
    assert MANIFEST.spec.required_authorities == [
        PluginAuthority.NETWORK,
        PluginAuthority.SECRETS,
    ]
    assert isinstance(
        assert_plugin_factory_contract(create_plugin, MANIFEST),
        HttpJsonEvidencePlugin,
    )


def test_connector_collects_minimized_bounded_evidence_offline() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer fixture-token"
        payload = json.loads(request.content)
        assert "raw_payload" not in payload["incident"]
        assert payload["incident"]["pipelineName"] == "synthetic-pipeline"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "http-evidence-1",
                        "source": "fixture-api",
                        "detail": "ERROR TESTKIT_SIGNATURE owner=person@example.com",
                        "confidence": 1.0,
                        "kind": "log_window",
                        "reference": "https://evidence.example.test/items/1",
                    }
                ]
            },
        )

    provider = HttpJsonEvidencePlugin().create(
        _config(),
        environ={"FIXTURE_EVIDENCE_TOKEN": "fixture-token"},
        transport=httpx.MockTransport(handler),
    )
    request = EvidenceRequest(incident=make_test_incident(), kinds=["log_window"])
    collection = asyncio.run(EvidenceService(provider).collect(request))

    assert collection.items[0].detail.endswith("[REDACTED_EMAIL]")
    assert_evidence_collection_contract(collection, request)


def test_connector_retries_retryable_status_and_rejects_redirects() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"items": []})

    provider = HttpJsonEvidenceProvider.from_environment(
        _config(retries=1),
        environ={"FIXTURE_EVIDENCE_TOKEN": "fixture-token"},
        transport=httpx.MockTransport(handler),
    )
    collection = asyncio.run(provider.collect(EvidenceRequest(incident=make_test_incident())))
    assert collection.failures == []
    assert calls == 2

    redirect = HttpJsonEvidenceProvider.from_environment(
        _config(),
        environ={"FIXTURE_EVIDENCE_TOKEN": "fixture-token"},
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                302,
                headers={"Location": "https://other.example.test/evidence"},
            )
        ),
    )
    failed = asyncio.run(redirect.collect(EvidenceRequest(incident=make_test_incident())))
    assert failed.failures[0].code == "redirect_not_allowed"
    assert failed.failures[0].retryable is False


def test_connector_rejects_oversized_or_invalid_response_and_missing_secret() -> None:
    oversized = HttpJsonEvidenceProvider.from_environment(
        _config(maxResponseBytes=10),
        environ={"FIXTURE_EVIDENCE_TOKEN": "fixture-token"},
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b'{"items":[{"large":"response"}]}')
        ),
    )
    failed = asyncio.run(oversized.collect(EvidenceRequest(incident=make_test_incident())))
    assert failed.failures[0].code == "response_too_large"

    invalid = HttpJsonEvidenceProvider.from_environment(
        _config(),
        environ={"FIXTURE_EVIDENCE_TOKEN": "fixture-token"},
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b'{"items":[],"items":[]}')
        ),
    )
    failed = asyncio.run(invalid.collect(EvidenceRequest(incident=make_test_incident())))
    assert failed.failures[0].code == "invalid_response"

    with pytest.raises(ValueError, match="is not set"):
        HttpJsonEvidenceProvider.from_environment(_config(), environ={})
