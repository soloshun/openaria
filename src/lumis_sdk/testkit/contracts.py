"""Reusable assertions for third-party adapter contract tests."""

from datetime import UTC, datetime
from uuid import UUID

from lumis_sdk.adapters.reports import parse_json_report, render_json_report
from lumis_sdk.domain import (
    DiagnosisReportDocument,
    EvidenceCollection,
    EvidenceRequest,
    TruthState,
    TruthTransition,
)
from lumis_sdk.ports import (
    MemoryConflictError,
    MemoryIncidentNotFoundError,
    MemoryQuery,
    MemoryStore,
)

from .fixtures import make_test_episode, make_test_resolution


def assert_evidence_collection_contract(
    collection: EvidenceCollection,
    request: EvidenceRequest,
) -> None:
    """Raise an actionable assertion when a provider violates public bounds."""
    if len(collection.items) > request.max_items:
        raise AssertionError("evidence provider returned more items than requested")
    ids = [item.id for item in collection.items]
    if len(ids) != len(set(ids)):
        raise AssertionError("evidence provider returned duplicate evidence IDs")
    if request.kinds and any(item.kind not in request.kinds for item in collection.items):
        raise AssertionError("evidence provider returned an unrequested evidence kind")
    if any(len(item.detail) > request.max_item_characters for item in collection.items):
        raise AssertionError("evidence provider returned an item above the character limit")
    total = sum(len(item.detail) for item in collection.items)
    if total > request.max_total_characters:
        raise AssertionError("evidence provider returned evidence above the total character limit")
    if any(failure.provider != collection.provider for failure in collection.failures):
        raise AssertionError("evidence failure provider does not match the collection provider")


def assert_json_report_round_trip(value: str) -> DiagnosisReportDocument:
    """Validate a JSON report and prove canonical serialization round-trips."""
    document = parse_json_report(value)
    canonical = render_json_report(
        document.incident,
        document.diagnosis,
        truth_state=document.truth_state,
        confirmed_resolution=document.confirmed_resolution,
    )
    if parse_json_report(canonical) != document:
        raise AssertionError("diagnosis report did not survive a canonical JSON round trip")
    return document


async def assert_memory_store_contract(store: MemoryStore) -> None:
    """Exercise public idempotency, truth, resolution, search, and error semantics."""
    episode = make_test_episode()
    await store.save_incident(episode)
    await store.save_incident(episode)

    changed = episode.model_copy(
        update={
            "diagnosis": episode.diagnosis.model_copy(
                update={"root_cause_hypothesis": "Different content for the same idempotency key."}
            )
        }
    )
    try:
        await store.save_incident(changed)
    except MemoryConflictError:
        pass
    else:
        raise AssertionError("memory store accepted different content for one incident_id")

    resolution = make_test_resolution()
    await store.record_resolution(resolution)
    await store.record_resolution(resolution)

    matches = await store.search(
        MemoryQuery(
            text="TESTKIT_SIGNATURE",
            classification="testkit_failure",
            pipeline_name="synthetic-pipeline",
            limit=1,
        )
    )
    if len(matches) != 1:
        raise AssertionError("memory store did not return the saved matching episode")
    match = matches[0]
    if match.episode.resolution != resolution:
        raise AssertionError("memory store did not preserve the confirmed resolution")
    if match.episode.truth_state != resolution.truth_state:
        raise AssertionError("memory store did not preserve the explicit truth state")
    if not match.reasons or match.score <= 0:
        raise AssertionError("memory search must expose positive transparent ranking reasons")
    if set(match.score_components) != {"lexical", "filters", "truth"}:
        raise AssertionError("memory search must expose stable score components")

    rejected_id = "33333333-3333-4333-8333-333333333333"
    await store.save_incident(make_test_episode(incident_id=rejected_id))
    rejection = TruthTransition(
        transition_id="testkit-rejection",
        incident_id=rejected_id,
        from_state=TruthState.UNCONFIRMED_HYPOTHESIS,
        to_state=TruthState.REJECTED,
        actor="testkit-verifier",
        reason="Synthetic verification failed.",
        recorded_at=datetime(2026, 1, 2, tzinfo=UTC),
        verification_id="verification-testkit",
    )
    await store.record_truth_transition(rejection)
    await store.record_truth_transition(rejection)
    reusable = await store.search(MemoryQuery(text="TESTKIT_SIGNATURE", reusable_only=True))
    if any(match.episode.incident_id == rejected_id for match in reusable):
        raise AssertionError("rejected memory was returned as reusable")

    missing = resolution.model_copy(
        update={"incident_id": UUID("22222222-2222-4222-8222-222222222222")}
    )
    try:
        await store.record_resolution(missing)
    except MemoryIncidentNotFoundError:
        pass
    else:
        raise AssertionError("memory store accepted a resolution for an unknown incident")
