"""Framework-neutral authenticated webhook normalization."""

import hashlib
import hmac
import json
import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from threading import Lock
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from lumis_sdk.domain import IncidentInput

_DELIVERY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_HEADER_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")


class WebhookError(ValueError):
    """Base class for safely reportable webhook rejection."""


class WebhookAuthenticationError(WebhookError):
    """Raised when timestamp or HMAC authentication fails."""


class WebhookPayloadError(WebhookError):
    """Raised when a webhook body or envelope exceeds strict bounds."""


class WebhookReplayError(WebhookError):
    """Raised when a delivery ID was already observed or cannot be recorded safely."""


class WebhookConfig(BaseModel):
    """Strict security and normalization settings for one generic webhook source."""

    model_config = ConfigDict(extra="forbid")

    source_tool: str = Field(default="generic-webhook", min_length=1, max_length=100)
    secret_env: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    signature_header: str = Field(default="x-lumis-signature", min_length=1, max_length=100)
    delivery_id_header: str = Field(default="x-lumis-delivery", min_length=1, max_length=100)
    timestamp_header: str = Field(default="x-lumis-timestamp", min_length=1, max_length=100)
    environment: str = Field(default="local", min_length=1, max_length=100)
    max_payload_bytes: int = Field(default=1_048_576, ge=1, le=10_485_760)
    max_clock_skew_seconds: int = Field(default=300, ge=1, le=3_600)
    max_json_depth: int = Field(default=20, ge=1, le=100)
    max_json_nodes: int = Field(default=10_000, ge=1, le=100_000)

    @model_validator(mode="after")
    def require_distinct_valid_headers(self) -> "WebhookConfig":
        names = [
            self.signature_header,
            self.delivery_id_header,
            self.timestamp_header,
        ]
        if any(not _HEADER_NAME.fullmatch(name) for name in names):
            raise ValueError("webhook header names must use valid HTTP token characters")
        if len({name.lower() for name in names}) != len(names):
            raise ValueError("webhook security header names must be distinct")
        return self


class ReplayGuard(Protocol):
    """Atomically claim delivery IDs behind a replaceable durable implementation."""

    def claim(self, delivery_id: str, *, now: datetime) -> bool:
        """Return false when the delivery was already claimed."""
        ...


class InMemoryReplayGuard:
    """Bounded process-local replay protection for tests and small local tools."""

    def __init__(self, *, ttl_seconds: int = 86_400, max_entries: int = 10_000) -> None:
        if ttl_seconds < 1 or ttl_seconds > 604_800:
            raise ValueError("ttl_seconds must be between 1 and 604800")
        if max_entries < 1 or max_entries > 100_000:
            raise ValueError("max_entries must be between 1 and 100000")
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: dict[str, float] = {}
        self._lock = Lock()

    def claim(self, delivery_id: str, *, now: datetime) -> bool:
        """Claim once, evict expired IDs, and fail closed when capacity is exhausted."""
        now_timestamp = now.timestamp()
        with self._lock:
            self._entries = {
                key: expiry for key, expiry in self._entries.items() if expiry > now_timestamp
            }
            if delivery_id in self._entries:
                return False
            if len(self._entries) >= self.max_entries:
                raise WebhookReplayError("replay guard capacity is exhausted")
            self._entries[delivery_id] = now_timestamp + self.ttl_seconds
        return True


def normalize_webhook(
    body: bytes,
    headers: Mapping[str, str],
    config: WebhookConfig,
    replay_guard: ReplayGuard,
    *,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> IncidentInput:
    """Authenticate bounded bytes and normalize them without embedding an HTTP server."""
    if len(body) > config.max_payload_bytes:
        raise WebhookPayloadError(f"webhook payload exceeds {config.max_payload_bytes} bytes")
    normalized_headers = _normalize_headers(headers)
    delivery_id = _required_header(normalized_headers, config.delivery_id_header)
    if not _DELIVERY_ID.fullmatch(delivery_id):
        raise WebhookPayloadError("webhook delivery ID has an invalid format")
    timestamp_text = _required_header(normalized_headers, config.timestamp_header)
    signature = _required_header(normalized_headers, config.signature_header)

    try:
        timestamp = int(timestamp_text)
        observed_at = datetime.fromtimestamp(timestamp, tz=UTC)
    except (ValueError, OSError, OverflowError) as error:
        raise WebhookAuthenticationError("webhook timestamp must be Unix seconds") from error
    current_time = (now or datetime.now(UTC)).astimezone(UTC)
    if abs((current_time - observed_at).total_seconds()) > config.max_clock_skew_seconds:
        raise WebhookAuthenticationError("webhook timestamp is outside the allowed clock skew")

    values = os.environ if environ is None else environ
    secret = values.get(config.secret_env)
    if not secret:
        raise WebhookAuthenticationError(
            f"required webhook secret environment variable {config.secret_env!r} is not set"
        )
    expected = sign_webhook_payload(body, timestamp=timestamp, secret=secret)
    if not hmac.compare_digest(signature, expected):
        raise WebhookAuthenticationError("webhook signature is invalid")

    payload = _load_bounded_json(
        body,
        max_depth=config.max_json_depth,
        max_nodes=config.max_json_nodes,
    )
    if "_lumis_webhook" in payload:
        raise WebhookPayloadError("webhook payload uses reserved field '_lumis_webhook'")
    try:
        claimed = replay_guard.claim(delivery_id, now=current_time)
    except WebhookReplayError:
        raise
    except Exception as error:
        raise WebhookReplayError("replay guard failed closed") from error
    if not claimed:
        raise WebhookReplayError(f"webhook delivery {delivery_id!r} was already processed")

    pipeline_name = _string_field(payload, "pipeline_name")
    pipeline = payload.get("pipeline")
    if pipeline_name is None and isinstance(pipeline, dict):
        pipeline_name = _string_field(pipeline, "name")
    environment = _string_field(payload, "environment") or config.environment
    return IncidentInput(
        source_tool=config.source_tool,
        pipeline_name=pipeline_name,
        environment=environment,
        raw_payload={
            **payload,
            "_lumis_webhook": {
                "delivery_id": delivery_id,
                "observed_at": observed_at.isoformat(),
            },
        },
    )


def sign_webhook_payload(body: bytes, *, timestamp: int, secret: str) -> str:
    """Create the documented `sha256=<hex>` signature over timestamp and exact bytes."""
    signed = str(timestamp).encode("ascii") + b"." + body
    digest = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _normalize_headers(headers: Mapping[str, str]) -> dict[str, str]:
    if len(headers) > 100:
        raise WebhookPayloadError("webhook envelope exceeds 100 headers")
    normalized: dict[str, str] = {}
    for name, value in headers.items():
        key = name.strip().lower()
        if not key or key in normalized:
            raise WebhookPayloadError("webhook headers contain a duplicate or empty name")
        if len(key) > 100 or len(value) > 8_192:
            raise WebhookPayloadError("webhook header name or value exceeds its size limit")
        if "\r" in value or "\n" in value:
            raise WebhookPayloadError("webhook header values must not contain newlines")
        normalized[key] = value.strip()
    return normalized


def _required_header(headers: Mapping[str, str], name: str) -> str:
    value = headers.get(name.lower())
    if not value:
        raise WebhookAuthenticationError(f"required webhook header {name!r} is missing")
    return value


def _load_bounded_json(body: bytes, *, max_depth: int, max_nodes: int) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise WebhookPayloadError(f"webhook JSON contains duplicate key {key!r}")
            value[key] = item
        return value

    try:
        value = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except WebhookPayloadError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise WebhookPayloadError("webhook body must be valid bounded UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise WebhookPayloadError("webhook JSON root must be an object")
    stack: list[tuple[object, int]] = [(value, 1)]
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > max_nodes:
            raise WebhookPayloadError(f"webhook JSON exceeds {max_nodes} nodes")
        if depth > max_depth:
            raise WebhookPayloadError(f"webhook JSON exceeds depth {max_depth}")
        if isinstance(item, dict):
            stack.extend((nested, depth + 1) for nested in item.values())
        elif isinstance(item, list):
            stack.extend((nested, depth + 1) for nested in item)
    return value


def _string_field(payload: Mapping[str, object], field: str) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise WebhookPayloadError(f"webhook field {field!r} must be a non-empty string")
    return value.strip()


def _reject_json_constant(value: str) -> None:
    raise WebhookPayloadError(f"webhook JSON constant {value!r} is not allowed")
