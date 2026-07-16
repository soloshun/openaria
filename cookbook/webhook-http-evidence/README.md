# Webhook plus HTTP JSON evidence cookbook

This offline cookbook proves both connector boundaries without embedding a server or making a
live provider call:

1. exact fixture bytes are timestamped, HMAC-signed, replay-checked, and normalized into an
   `IncidentInput`;
2. the independently packaged HTTP JSON evidence provider sends minimized incident metadata to an
   `httpx.MockTransport`;
3. the fixture response is normalized through `EvidenceService`, including redaction and bounds.

```bash
PYTHONPATH=packages/lumis-sdk-http-json-evidence/src \
uv run --with 'httpx>=0.28,<1' \
python cookbook/webhook-http-evidence/demo.py
```

Real HTTP servers remain application responsibilities. Production replay protection should use a
durable atomic store shared by every receiver process. The connector requires an exact HTTPS
origin allowlist, does not follow redirects, and references credentials by environment variable.
It collects evidence only and exposes no action-execution surface.
