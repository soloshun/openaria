# Webhook and evidence connector API

## Generic webhook normalization

Lumis SDK does not embed a web server. Applications pass the exact already-received body bytes
and headers to `normalize_webhook`, along with explicit security configuration and a replay guard.

```python
from lumis_sdk.adapters.incidents import (
    InMemoryReplayGuard,
    WebhookConfig,
    normalize_webhook,
)

incident = normalize_webhook(
    body,
    headers,
    WebhookConfig(
        source_tool="pipeline-events",
        secret_env="PIPELINE_WEBHOOK_SECRET",
    ),
    InMemoryReplayGuard(),
)
```

The signature format is `sha256=<hex>` over:

```text
<unix timestamp>.<exact request body bytes>
```

The adapter applies constant-time HMAC comparison, clock-skew and payload limits, unique-key
UTF-8 JSON parsing, depth/node bounds, strict delivery IDs, and fail-closed replay claims. The
process-local guard is for local tools and tests; multi-process deployments must provide a
durable atomic `ReplayGuard`.

Transport concerns remain outside core: TLS termination, HTTP method/content-type enforcement,
source IP policy, rate limiting, queueing, request logging, and response status selection.

## HTTP JSON evidence plugin

The independently packaged `lumis-sdk-http-json-evidence` plugin implements `EvidenceProvider`
without adding `httpx` to core.

```yaml
spec:
  evidenceProviders:
    - provider: http-json
      url: https://evidence.example.test/v1/evidence
      allowedOrigins: [https://evidence.example.test]
      tokenEnv: LUMIS_EVIDENCE_TOKEN
      maxResponseBytes: 1000000
      timeoutSeconds: 5
      retries: 1
```

```python
from lumis_http_json_evidence import HttpJsonEvidencePlugin

provider = HttpJsonEvidencePlugin().create(config)
collection = await EvidenceService(provider).collect(request)
```

The connector requires HTTPS and exact origin allowlisting, never follows redirects, loads only
the named token reference, sends minimized incident metadata rather than raw payloads, bounds
response bytes before JSON parsing, and returns structured failures. Core `EvidenceService`
continues to enforce requested kinds, item counts, character budgets, duplicate IDs, timeouts,
and redaction.

See the [offline cookbook](../../cookbook/webhook-http-evidence/README.md).
