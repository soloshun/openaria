"""Asynchronous SQLite implementation of the public MemoryStore contract."""

import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from lumis_sdk.adapters.memory import is_idempotent_episode_replay, rank_memory_episodes
from lumis_sdk.domain import ConfirmedResolution, TruthState, TruthTransition
from lumis_sdk.ports import (
    IncidentEpisode,
    MemoryConflictError,
    MemoryIncidentNotFoundError,
    MemoryMatch,
    MemoryQuery,
)

_SCHEMA_VERSION = 1


class SQLiteMemoryStore:
    """Persist portable memory episodes in a local SQLite database."""

    def __init__(self, database_path: Path, *, max_search_candidates: int = 1_000) -> None:
        if max_search_candidates < 1 or max_search_candidates > 10_000:
            raise ValueError("max_search_candidates must be between 1 and 10000")
        self.database_path = database_path
        self.max_search_candidates = max_search_candidates

    async def save_incident(self, incident: IncidentEpisode) -> None:
        """Store an episode idempotently by incident_id."""
        await asyncio.to_thread(self._save_incident, incident)

    async def record_resolution(self, resolution: ConfirmedResolution) -> None:
        """Attach one explicit resolution idempotently to an existing episode."""
        await asyncio.to_thread(self._record_resolution, resolution)

    async def record_truth_transition(self, transition: TruthTransition) -> None:
        """Persist one rejection or supersession idempotently."""
        await asyncio.to_thread(self._record_truth_transition, transition)

    async def search(self, query: MemoryQuery) -> list[MemoryMatch]:
        """Search a bounded candidate set and expose deterministic ranking reasons."""
        episodes = await asyncio.to_thread(self._load_candidates)
        return rank_memory_episodes(episodes, query)

    def _save_incident(self, incident: IncidentEpisode) -> None:
        self._initialize()
        payload = incident.model_dump_json()
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO lumis_memory_episodes (
                    incident_id, episode_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(incident_id) DO NOTHING
                """,
                (incident.incident_id, payload, now, now),
            )
            if cursor.rowcount == 1:
                return
            existing = self._get_episode(connection, incident.incident_id)
        assert existing is not None
        if not is_idempotent_episode_replay(existing, incident):
            raise MemoryConflictError(
                f"incident_id {incident.incident_id!r} already stores different content"
            )

    def _record_resolution(self, resolution: ConfirmedResolution) -> None:
        self._initialize()
        incident_id = str(resolution.incident_id)
        with self._connect() as connection:
            existing = self._get_episode(connection, incident_id, required=False)
            if existing is None:
                raise MemoryIncidentNotFoundError(
                    f"No memory episode found for incident_id {incident_id!r}"
                )
            if existing.resolution is not None:
                if existing.resolution == resolution:
                    return
                raise MemoryConflictError(
                    f"incident_id {incident_id!r} already has a different resolution"
                )
            updated = existing.model_copy(
                update={
                    "resolution": resolution,
                    "truth_state": resolution.truth_state,
                    "truth_transitions": [
                        *existing.truth_transitions,
                        TruthTransition.for_resolution(
                            f"resolution:{resolution.confirmed_at.isoformat()}",
                            resolution=resolution,
                        ),
                    ],
                }
            )
            connection.execute(
                """
                UPDATE lumis_memory_episodes
                SET episode_json = ?, updated_at = ?
                WHERE incident_id = ?
                """,
                (
                    updated.model_dump_json(),
                    datetime.now(UTC).isoformat(),
                    incident_id,
                ),
            )

    def _record_truth_transition(self, transition: TruthTransition) -> None:
        self._initialize()
        if transition.to_state in {
            TruthState.HUMAN_CONFIRMED,
            TruthState.VERIFICATION_CONFIRMED,
        }:
            raise ValueError("confirmed truth must be recorded with an explicit resolution")
        with self._connect() as connection:
            existing = self._get_episode(connection, transition.incident_id, required=False)
            if existing is None:
                raise MemoryIncidentNotFoundError(
                    f"No memory episode found for incident_id {transition.incident_id!r}"
                )
            previous = next(
                (
                    item
                    for item in existing.truth_transitions
                    if item.transition_id == transition.transition_id
                ),
                None,
            )
            if previous is not None:
                if previous == transition:
                    return
                raise MemoryConflictError(
                    f"transition_id {transition.transition_id!r} stores different content"
                )
            if existing.truth_state != transition.from_state:
                raise MemoryConflictError(
                    f"truth transition expected {transition.from_state.value!r}, "
                    f"found {existing.truth_state.value!r}"
                )
            updated = existing.model_copy(
                update={
                    "truth_state": transition.to_state,
                    "truth_transitions": [*existing.truth_transitions, transition],
                    "superseded_by_incident_id": (
                        transition.supersedes_incident_id
                        if transition.to_state is TruthState.SUPERSEDED
                        else existing.superseded_by_incident_id
                    ),
                }
            )
            connection.execute(
                """
                UPDATE lumis_memory_episodes
                SET episode_json = ?, updated_at = ?
                WHERE incident_id = ?
                """,
                (
                    updated.model_dump_json(),
                    datetime.now(UTC).isoformat(),
                    transition.incident_id,
                ),
            )

    def _load_candidates(self) -> list[IncidentEpisode]:
        self._initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT episode_json
                FROM lumis_memory_episodes
                ORDER BY updated_at DESC, incident_id DESC
                LIMIT ?
                """,
                (self.max_search_candidates,),
            ).fetchall()
        return [IncidentEpisode.model_validate_json(str(row["episode_json"])) for row in rows]

    def _initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS lumis_memory_schema (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            current = connection.execute(
                "SELECT MAX(version) AS version FROM lumis_memory_schema"
            ).fetchone()
            current_version = int(current["version"]) if current["version"] is not None else 0
            if current_version > _SCHEMA_VERSION:
                raise RuntimeError(
                    f"SQLite memory schema {current_version} is newer than supported "
                    f"version {_SCHEMA_VERSION}"
                )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS lumis_memory_episodes (
                    incident_id TEXT PRIMARY KEY,
                    episode_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            if current_version < _SCHEMA_VERSION:
                connection.execute(
                    "INSERT INTO lumis_memory_schema (version, applied_at) VALUES (?, ?)",
                    (_SCHEMA_VERSION, datetime.now(UTC).isoformat()),
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _get_episode(
        connection: sqlite3.Connection,
        incident_id: str,
        *,
        required: bool = True,
    ) -> IncidentEpisode | None:
        row = connection.execute(
            "SELECT episode_json FROM lumis_memory_episodes WHERE incident_id = ?",
            (incident_id,),
        ).fetchone()
        if row is None:
            if required:
                raise MemoryIncidentNotFoundError(
                    f"No memory episode found for incident_id {incident_id!r}"
                )
            return None
        return IncidentEpisode.model_validate_json(str(row["episode_json"]))
