"""Deterministic, transparent ranking shared by memory adapters."""

import json
import re

from lumis_sdk.domain import TruthState
from lumis_sdk.ports import IncidentEpisode, MemoryMatch, MemoryQuery

_WORD_PATTERN = re.compile(r"[a-z0-9_]+")


def is_idempotent_episode_replay(
    existing: IncidentEpisode,
    incoming: IncidentEpisode,
) -> bool:
    """Treat replay of the original episode as safe after an explicit resolution."""
    if existing == incoming:
        return True
    if existing.resolution is None or incoming.resolution is not None:
        return False
    unresolved_existing = existing.model_copy(
        update={
            "resolution": None,
            "truth_state": TruthState.UNCONFIRMED_HYPOTHESIS,
            "truth_transitions": [],
            "superseded_by_incident_id": None,
        }
    )
    return unresolved_existing == incoming


def rank_memory_episodes(
    episodes: list[IncidentEpisode],
    query: MemoryQuery,
) -> list[MemoryMatch]:
    """Rank bounded candidate episodes with inspectable lexical and filter reasons."""
    query_terms = set(_tokenize(query.text))
    matches: list[MemoryMatch] = []

    for episode in episodes:
        reusable_states = {
            TruthState.HUMAN_CONFIRMED,
            TruthState.VERIFICATION_CONFIRMED,
        }
        if query.reusable_only and episode.truth_state not in reusable_states:
            continue
        if query.truth_states and episode.truth_state not in query.truth_states:
            continue
        if (
            query.classification is not None
            and episode.diagnosis.triage.classification != query.classification
        ):
            continue
        if (
            query.pipeline_name is not None
            and episode.incident.pipeline_name != query.pipeline_name
        ):
            continue

        episode_terms = set(_tokenize(_searchable_text(episode)))
        matched_terms = sorted(query_terms & episode_terms)
        if query_terms and not matched_terms:
            continue

        lexical_score = float(len(matched_terms))
        filter_score = 0.0
        truth_score = {
            TruthState.VERIFICATION_CONFIRMED: 2.0,
            TruthState.HUMAN_CONFIRMED: 1.5,
            TruthState.UNCONFIRMED_HYPOTHESIS: 0.0,
            TruthState.REJECTED: 0.0,
            TruthState.SUPERSEDED: 0.0,
        }[episode.truth_state]
        score = lexical_score + truth_score
        reasons: list[str] = []
        if matched_terms:
            reasons.append(f"matched terms: {', '.join(matched_terms)}")
        if query.classification is not None:
            score += 1
            filter_score += 1
            reasons.append(f"classification matched: {query.classification}")
        if query.pipeline_name is not None:
            score += 1
            filter_score += 1
            reasons.append(f"pipeline matched: {query.pipeline_name}")
        reasons.append(f"truth state: {episode.truth_state.value}")
        if truth_score:
            reasons.append(f"confirmed truth weight: {truth_score:g}")
        if not reasons:
            reasons.append("matched an unfiltered bounded memory query")
        matches.append(
            MemoryMatch(
                episode=episode,
                score=score,
                reasons=reasons,
                score_components={
                    "lexical": lexical_score,
                    "filters": filter_score,
                    "truth": truth_score,
                },
            )
        )

    return sorted(
        matches,
        key=lambda match: (match.score, match.episode.incident_id),
        reverse=True,
    )[: query.limit]


def _searchable_text(episode: IncidentEpisode) -> str:
    resolution = episode.resolution
    return " ".join(
        [
            episode.incident.source_tool,
            episode.incident.pipeline_name or "",
            episode.incident.environment,
            json.dumps(episode.incident.raw_payload, sort_keys=True, default=str),
            episode.diagnosis.triage.classification,
            episode.diagnosis.triage.summary,
            episode.diagnosis.root_cause_hypothesis,
            resolution.confirmed_root_cause if resolution is not None else "",
            resolution.action_taken if resolution is not None else "",
            resolution.outcome if resolution is not None else "",
            " ".join(resolution.reusable_notes) if resolution is not None else "",
        ]
    )


def _tokenize(value: str) -> list[str]:
    return _WORD_PATTERN.findall(value.lower())
