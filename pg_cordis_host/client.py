"""Synchronous psql client for existing cordis SQL verbs."""

from __future__ import annotations

import json
import math
import re
import secrets
import subprocess
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

JsonValue = Any

_MAX_ENVELOPE = 8 * 1024 * 1024
_MAX_ERROR_OUTPUT = 4096
_WORKER_ID_RE = re.compile(
    r"^host:([a-z][a-z0-9_-]{0,63}):([0-9a-f]{32})$"
)
_SERVICE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_STEP_NAME_RE = re.compile(r"^s-[1-9][0-9]*$")
_SQLSTATE_RE = re.compile(
    r"(?:ERROR:\s+([0-9A-Z]{5}):)|(?:\bSQLSTATE:\s*([0-9A-Z]{5})\b)"
)
_GRANT_KINDS = frozenset({"run", "named_corpus", "event"})
_PSQL_FLAGS = (
    "--no-psqlrc",
    "-v",
    "ON_ERROR_STOP=1",
    "-v",
    "VERBOSITY=verbose",
    "-q",
    "-t",
    "-A",
)

# Finite timestamptz only: PostgreSQL JSON rejects +/-infinity.
_JOB_OBJECT_SQL = """pg_catalog.jsonb_build_object(
    'job_id', j.job_id,
    'run_id', j.run_id,
    'job_type', j.job_type,
    'payload', j.payload,
    'status', j.status,
    'priority', j.priority,
    'attempt', j.attempt,
    'available_at', CASE
        WHEN j.available_at = '-infinity'::pg_catalog.timestamptz THEN NULL
        WHEN j.available_at = 'infinity'::pg_catalog.timestamptz THEN NULL
        ELSE j.available_at
    END,
    'claim_token', j.claim_token,
    'claimed_by', j.claimed_by,
    'claim_expires_at', j.claim_expires_at,
    'result', j.result,
    'error', j.error,
    'created_at', j.created_at,
    'completed_at', j.completed_at
)"""

_JOB_SNAPSHOT_SQL = """pg_catalog.jsonb_build_object(
    'job_id', j.job_id,
    'run_id', j.run_id,
    'job_type', j.job_type,
    'payload', j.payload,
    'status', j.status,
    'priority', j.priority,
    'attempt', j.attempt,
    'available_at', CASE
        WHEN j.available_at = '-infinity'::pg_catalog.timestamptz THEN NULL
        WHEN j.available_at = 'infinity'::pg_catalog.timestamptz THEN NULL
        ELSE j.available_at
    END,
    'claimed_by', j.claimed_by,
    'claim_expires_at', j.claim_expires_at,
    'result', j.result,
    'error', j.error,
    'created_at', j.created_at,
    'completed_at', j.completed_at,
    'claim_present', j.claim_token IS NOT NULL
)"""


class CordisHostError(Exception):
    """Base host-client error."""


class CordisInputError(CordisHostError):
    """Local validation failed before starting psql."""


class CordisCommandTimeout(CordisHostError):
    """The psql child exceeded the configured command timeout."""


class CordisSqlError(CordisHostError):
    """psql exited nonzero."""

    def __init__(
        self, returncode: int, output: str, sqlstate: str | None = None
    ) -> None:
        self.returncode = returncode
        self.sqlstate = sqlstate
        bounded = output[:_MAX_ERROR_OUTPUT]
        suffix = f" [{sqlstate}]" if sqlstate else ""
        super().__init__(f"psql failed ({returncode}){suffix}: {bounded}")


class CordisProtocolError(CordisHostError):
    """Successful command returned contract-incompatible JSON."""


class CordisFeatureUnavailable(CordisHostError):
    """Optional exact SQL capability is not installed."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


@dataclass(frozen=True)
class ClaimedJob:
    job_id: int
    run_id: str
    job_type: str
    payload: JsonValue
    status: str
    priority: int
    attempt: int
    available_at: datetime | None
    claim_token: uuid.UUID
    claimed_by: str
    claim_expires_at: datetime
    result: JsonValue
    error: JsonValue
    created_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True)
class JobSnapshot:
    job_id: int
    run_id: str
    job_type: str
    payload: JsonValue
    status: str
    priority: int
    attempt: int
    available_at: datetime | None
    claimed_by: str | None
    claim_expires_at: datetime | None
    result: JsonValue
    error: JsonValue
    created_at: datetime
    completed_at: datetime | None
    claim_present: bool


@dataclass(frozen=True)
class CheckpointEvent:
    run_id: str
    kind: str
    payload: JsonValue
    step_name: str | None = None


@dataclass(frozen=True)
class AgentStep:
    run_id: str
    seq: int
    kind: str
    payload: JsonValue
    step_name: str | None
    created_at: datetime


@dataclass(frozen=True)
class RunState:
    status: str
    steps_used: int
    answer: str | None
    error: str | None


@dataclass(frozen=True)
class AwaitEventResult:
    accepted: bool
    should_suspend: bool
    payload: JsonValue
    source_run_id: str | None
    source_seq: int | None


@dataclass(frozen=True)
class NamedCorpusRef:
    grant_id: uuid.UUID
    corpus_id: str
    label: str


@dataclass(frozen=True)
class PluginCatalogEntry:
    identity: str
    version: str
    name: str
    description: str
    locus: str
    invocation: str
    required_grants: tuple[str, ...]
    effect_class: str
    retry_class: str
    reconciliation: str
    inject: JsonValue
    provide: JsonValue
    intercept: JsonValue
    capability: JsonValue
    session_scope: str
    config: JsonValue
    metadata: JsonValue
    source_kind: str
    entrypoint: str | None
    refreshed_at: datetime


@dataclass(frozen=True)
class AuthorizedHostTool:
    identity: str
    name: str
    description: str
    version: str
    locus: str
    invocation: str
    required_grants: tuple[str, ...]
    bindings: Mapping[str, JsonValue]
    effect_class: str
    retry_class: str
    reconciliation: str
    entrypoint: None
    session_scope: str
    capability: JsonValue
    config: JsonValue
    inject: JsonValue
    provide: JsonValue
    intercept: JsonValue
    descriptor: Mapping[str, JsonValue]


def new_host_worker_id(
    service: str, instance_id: uuid.UUID | None = None
) -> str:
    if not isinstance(service, str) or _SERVICE_RE.fullmatch(service) is None:
        raise CordisInputError("service must match [a-z][a-z0-9_-]{0,63}")
    uid = instance_id if instance_id is not None else uuid.uuid4()
    if not isinstance(uid, uuid.UUID):
        raise CordisInputError("instance_id must be a UUID")
    return f"host:{service}:{uid.hex}"


def _require_nonblank(name: str, value: str) -> str:
    if not isinstance(value, str) or value.strip() == "":
        raise CordisInputError(f"{name} must be a nonblank string")
    return value


def _require_positive_int(name: str, value: int) -> int:
    if type(value) is not int or value <= 0:
        raise CordisInputError(f"{name} must be a positive int")
    return value


def _require_uuid(name: str, value: uuid.UUID) -> uuid.UUID:
    if not isinstance(value, uuid.UUID):
        raise CordisInputError(f"{name} must be a UUID")
    return value


def _require_mapping(name: str, value: object) -> Mapping[str, JsonValue]:
    if not isinstance(value, Mapping) or isinstance(value, (str, bytes)):
        raise CordisInputError(f"{name} must be a JSON object")
    return value


def _require_aware(name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise CordisInputError(f"{name} must be a timezone-aware datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise CordisInputError(f"{name} must be a timezone-aware datetime")
    return value


def _require_step_name(value: str) -> str:
    if not isinstance(value, str) or _STEP_NAME_RE.fullmatch(value) is None:
        raise CordisInputError("step_name must match s-N")
    return value


def _parse_dt(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value != "":
        text = value.replace(" ", "T", 1)
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise CordisProtocolError("unparseable timestamp") from None
    else:
        raise CordisProtocolError("timestamp must be a string or null")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CordisProtocolError("timestamp must be timezone-aware")
    return parsed


def _parse_required_dt(value: object) -> datetime:
    parsed = _parse_dt(value)
    if parsed is None:
        raise CordisProtocolError("timestamp must not be null")
    return parsed


def _parse_uuid(value: object) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    if not isinstance(value, str):
        raise CordisProtocolError("uuid must be a string")
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise CordisProtocolError("unparseable uuid") from exc


def _parse_optional_uuid(value: object) -> uuid.UUID | None:
    if value is None:
        return None
    return _parse_uuid(value)


def _parse_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CordisProtocolError("expected integer")
    return value


def _parse_optional_int(value: object) -> int | None:
    if value is None:
        return None
    return _parse_int(value)


def _parse_bool(value: object) -> bool:
    if not isinstance(value, bool):
        raise CordisProtocolError("expected boolean")
    return value


def _parse_str(value: object) -> str:
    if not isinstance(value, str):
        raise CordisProtocolError("expected string")
    return value


def _parse_optional_str(value: object) -> str | None:
    if value is None:
        return None
    return _parse_str(value)


def _grants_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise CordisProtocolError("required_grants must be a JSON array")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or item not in _GRANT_KINDS:
            raise CordisProtocolError("invalid required_grants entry")
        out.append(item)
    return tuple(out)


def _sqlstate_from_output(output: str) -> str | None:
    match = _SQLSTATE_RE.search(output)
    if match is None:
        return None
    return match.group(1) or match.group(2)


def _claimed_job(row: Mapping[str, JsonValue], worker_id: str) -> ClaimedJob:
    status = _parse_str(row.get("status"))
    claimed_by = _parse_str(row.get("claimed_by"))
    token = _parse_uuid(row.get("claim_token"))
    if status != "RUNNING":
        raise CordisProtocolError("claimed job status must be RUNNING")
    if claimed_by != worker_id:
        raise CordisProtocolError("claimed_by must match client worker_id")
    return ClaimedJob(
        job_id=_parse_int(row.get("job_id")),
        run_id=_parse_str(row.get("run_id")),
        job_type=_parse_str(row.get("job_type")),
        payload=row.get("payload"),
        status=status,
        priority=_parse_int(row.get("priority")),
        attempt=_parse_int(row.get("attempt")),
        available_at=_parse_dt(row.get("available_at")),
        claim_token=token,
        claimed_by=claimed_by,
        claim_expires_at=_parse_required_dt(row.get("claim_expires_at")),
        result=row.get("result"),
        error=row.get("error"),
        created_at=_parse_required_dt(row.get("created_at")),
        completed_at=_parse_dt(row.get("completed_at")),
    )


def _job_snapshot(row: Mapping[str, JsonValue]) -> JobSnapshot:
    if "claim_token" in row:
        raise CordisProtocolError("job snapshot must not include claim_token")
    return JobSnapshot(
        job_id=_parse_int(row.get("job_id")),
        run_id=_parse_str(row.get("run_id")),
        job_type=_parse_str(row.get("job_type")),
        payload=row.get("payload"),
        status=_parse_str(row.get("status")),
        priority=_parse_int(row.get("priority")),
        attempt=_parse_int(row.get("attempt")),
        available_at=_parse_dt(row.get("available_at")),
        claimed_by=_parse_optional_str(row.get("claimed_by")),
        claim_expires_at=_parse_dt(row.get("claim_expires_at")),
        result=row.get("result"),
        error=row.get("error"),
        created_at=_parse_required_dt(row.get("created_at")),
        completed_at=_parse_dt(row.get("completed_at")),
        claim_present=_parse_bool(row.get("claim_present")),
    )


def _agent_step(row: Mapping[str, JsonValue]) -> AgentStep:
    return AgentStep(
        run_id=_parse_str(row.get("run_id")),
        seq=_parse_int(row.get("seq")),
        kind=_parse_str(row.get("kind")),
        payload=row.get("payload"),
        step_name=_parse_optional_str(row.get("step_name")),
        created_at=_parse_required_dt(row.get("created_at")),
    )


def _plugin_entry(row: Mapping[str, JsonValue]) -> PluginCatalogEntry:
    entrypoint = row.get("entrypoint")
    if entrypoint is not None and not isinstance(entrypoint, str):
        raise CordisProtocolError("entrypoint must be a string or null")
    return PluginCatalogEntry(
        identity=_parse_str(row.get("identity")),
        version=_parse_str(row.get("version")),
        name=_parse_str(row.get("name")),
        description=_parse_str(row.get("description")),
        locus=_parse_str(row.get("locus")),
        invocation=_parse_str(row.get("invocation")),
        required_grants=_grants_tuple(row.get("required_grants")),
        effect_class=_parse_str(row.get("effect_class")),
        retry_class=_parse_str(row.get("retry_class")),
        reconciliation=_parse_str(row.get("reconciliation")),
        inject=row.get("inject"),
        provide=row.get("provide"),
        intercept=row.get("intercept"),
        capability=row.get("capability"),
        session_scope=_parse_str(row.get("session_scope")),
        config=row.get("config"),
        metadata=row.get("metadata"),
        source_kind=_parse_str(row.get("source_kind")),
        entrypoint=entrypoint,
        refreshed_at=_parse_required_dt(row.get("refreshed_at")),
    )


class CordisHostClient:
    def __init__(
        self,
        dsn: str,
        worker_id: str,
        *,
        psql_path: str | Path = "psql",
        command_timeout_seconds: float = 30.0,
    ) -> None:
        if not isinstance(dsn, str) or dsn.strip() == "":
            raise CordisInputError("dsn must be a nonblank string")
        if not isinstance(worker_id, str) or _WORKER_ID_RE.fullmatch(worker_id) is None:
            raise CordisInputError(
                "worker_id must match host:<service>:<32-hex>"
            )
        if isinstance(psql_path, Path):
            path_text = str(psql_path)
        elif isinstance(psql_path, str):
            path_text = psql_path
        else:
            raise CordisInputError("psql_path must be a string or Path")
        if path_text.strip() == "":
            raise CordisInputError("psql_path must be a nonblank string")
        if (
            not isinstance(command_timeout_seconds, (int, float))
            or isinstance(command_timeout_seconds, bool)
            or not math.isfinite(command_timeout_seconds)
            or command_timeout_seconds <= 0
        ):
            raise CordisInputError("command_timeout_seconds must be positive")
        self._dsn = dsn
        self._worker_id = worker_id
        self._psql_path = path_text
        self._timeout = float(command_timeout_seconds)

    @property
    def worker_id(self) -> str:
        return self._worker_id

    def __repr__(self) -> str:
        return (
            "CordisHostClient("
            f"worker_id={self._worker_id!r}, "
            f"command_timeout_seconds={self._timeout})"
        )

    def claim_job(
        self, run_id: str | None, lease_seconds: int = 90
    ) -> ClaimedJob | None:
        if run_id is not None:
            _require_nonblank("run_id", run_id)
        _require_positive_int("lease_seconds", lease_seconds)
        raw = self._run(
            f"""
SELECT COALESCE(
  (SELECT pg_catalog.jsonb_agg({_JOB_OBJECT_SQL}) FROM cordis.claim_job(
      (d.payload->>'run_id'),
      d.payload->>'worker_id',
      (d.payload->>'lease_seconds')::pg_catalog.int4
  ) AS j),
  '[]'::pg_catalog.jsonb
)
FROM (SELECT $TAG$::pg_catalog.jsonb AS payload) AS d
""",
            {
                "run_id": run_id,
                "worker_id": self._worker_id,
                "lease_seconds": lease_seconds,
            },
        )
        if not isinstance(raw, list):
            raise CordisProtocolError("claim_job must return a JSON array")
        if len(raw) == 0:
            return None
        if len(raw) != 1 or not isinstance(raw[0], dict):
            raise CordisProtocolError("claim_job returned an unexpected row set")
        job = _claimed_job(raw[0], self._worker_id)
        if run_id is not None and job.run_id != run_id:
            raise CordisProtocolError("claimed run_id did not match the request")
        return job

    def renew_claim(
        self, claim_token: uuid.UUID, extend_seconds: int = 90
    ) -> bool:
        return self._bool_token_call(
            "cordis.renew_claim",
            claim_token,
            extra_sql=", (d.payload->>'extend_seconds')::pg_catalog.int4",
            extra_payload={"extend_seconds": _require_positive_int(
                "extend_seconds", extend_seconds
            )},
        )

    def yield_claim(self, claim_token: uuid.UUID) -> bool:
        return self._bool_token_call("cordis.yield_claim", claim_token)

    def complete_claim(
        self, claim_token: uuid.UUID, result: JsonValue | None = None
    ) -> bool:
        _require_uuid("claim_token", claim_token)
        return self._as_bool(
            self._run(
                """
SELECT pg_catalog.to_jsonb(cordis.complete_claim(
    (d.payload->>'claim_token')::pg_catalog.uuid,
    d.payload->'result'
))
FROM (SELECT $TAG$::pg_catalog.jsonb AS payload) AS d
""",
                {"claim_token": str(claim_token), "result": result},
            )
        )

    def fail_claim(
        self, claim_token: uuid.UUID, reason: Mapping[str, JsonValue]
    ) -> bool:
        _require_uuid("claim_token", claim_token)
        _require_mapping("reason", reason)
        return self._as_bool(
            self._run(
                """
SELECT pg_catalog.to_jsonb(cordis.fail_claim(
    (d.payload->>'claim_token')::pg_catalog.uuid,
    d.payload->'reason'
))
FROM (SELECT $TAG$::pg_catalog.jsonb AS payload) AS d
""",
                {"claim_token": str(claim_token), "reason": dict(reason)},
            )
        )

    def get_job(self, run_id: str) -> JobSnapshot | None:
        _require_nonblank("run_id", run_id)
        raw = self._run(
            f"""
SELECT COALESCE(
  (SELECT {_JOB_SNAPSHOT_SQL} FROM cordis.jobs AS j
    WHERE j.run_id = d.payload->>'run_id'),
  'null'::pg_catalog.jsonb
)
FROM (SELECT $TAG$::pg_catalog.jsonb AS payload) AS d
""",
            {"run_id": run_id},
        )
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise CordisProtocolError("get_job must return an object or null")
        return _job_snapshot(raw)

    def checkpoint(
        self,
        claim_token: uuid.UUID,
        events: Sequence[CheckpointEvent],
        extend_seconds: int = 90,
    ) -> bool:
        _require_uuid("claim_token", claim_token)
        _require_positive_int("extend_seconds", extend_seconds)
        if not isinstance(events, Sequence) or isinstance(events, (str, bytes)):
            raise CordisInputError("events must be a sequence")
        encoded: list[dict[str, JsonValue]] = []
        for event in events:
            if not isinstance(event, CheckpointEvent):
                raise CordisInputError("events must contain CheckpointEvent values")
            item: dict[str, JsonValue] = {
                "run_id": _require_nonblank("run_id", event.run_id),
                "kind": _require_nonblank("kind", event.kind),
                "payload": event.payload,
            }
            if event.step_name is not None:
                item["step_name"] = _require_step_name(event.step_name)
            encoded.append(item)
        return self._as_bool(
            self._run(
                """
SELECT pg_catalog.to_jsonb(cordis.checkpoint(
    (d.payload->>'claim_token')::pg_catalog.uuid,
    d.payload->'events',
    (d.payload->>'extend_seconds')::pg_catalog.int4
))
FROM (SELECT $TAG$::pg_catalog.jsonb AS payload) AS d
""",
                {
                    "claim_token": str(claim_token),
                    "events": encoded,
                    "extend_seconds": extend_seconds,
                },
            )
        )

    def emit_step_scoped(
        self,
        claim_token: uuid.UUID,
        run_id: str,
        slice_id: uuid.UUID,
        kind: str,
        payload: Mapping[str, JsonValue],
        *,
        step_name: str | None = None,
        corpus_ids: Sequence[str] = (),
        extend_seconds: int = 90,
    ) -> bool:
        _require_uuid("claim_token", claim_token)
        _require_nonblank("run_id", run_id)
        _require_uuid("slice_id", slice_id)
        _require_nonblank("kind", kind)
        mapping = _require_mapping("payload", payload)
        if "p08_scope" in mapping:
            raise CordisInputError("payload must not contain p08_scope")
        _require_positive_int("extend_seconds", extend_seconds)
        if not isinstance(corpus_ids, Sequence) or isinstance(
            corpus_ids, (str, bytes)
        ):
            raise CordisInputError("corpus_ids must be a sequence of strings")
        corpora: list[str] = []
        for item in corpus_ids:
            if not isinstance(item, str):
                raise CordisInputError("corpus_ids must be strings")
            corpora.append(item)
        if step_name is not None:
            _require_step_name(step_name)
        return self._as_bool(
            self._run(
                """
SELECT pg_catalog.to_jsonb(cordis.emit_step_scoped(
    (d.payload->>'claim_token')::pg_catalog.uuid,
    d.payload->>'run_id',
    (d.payload->>'slice_id')::pg_catalog.uuid,
    d.payload->>'kind',
    d.payload->'payload',
    NULLIF(d.payload->>'step_name', ''),
    COALESCE(
      (SELECT pg_catalog.array_agg(x) FROM pg_catalog.jsonb_array_elements_text(d.payload->'corpus_ids') AS t(x)),
      ARRAY[]::pg_catalog.text[]
    ),
    (d.payload->>'extend_seconds')::pg_catalog.int4
))
FROM (SELECT $TAG$::pg_catalog.jsonb AS payload) AS d
""",
                {
                    "claim_token": str(claim_token),
                    "run_id": run_id,
                    "slice_id": str(slice_id),
                    "kind": kind,
                    "payload": dict(mapping),
                    "step_name": step_name,
                    "corpus_ids": corpora,
                    "extend_seconds": extend_seconds,
                },
            )
        )

    def next_step_name(self, run_id: str) -> str:
        _require_nonblank("run_id", run_id)
        raw = self._run(
            """
SELECT pg_catalog.to_jsonb(cordis.next_step_name(d.payload->>'run_id'))
FROM (SELECT $TAG$::pg_catalog.jsonb AS payload) AS d
""",
            {"run_id": run_id},
        )
        name = _parse_str(raw)
        if _STEP_NAME_RE.fullmatch(name) is None:
            raise CordisProtocolError("next_step_name must match s-N")
        return name

    def llm_checkpoint(
        self, run_id: str, step_name: str
    ) -> AgentStep | None:
        _require_nonblank("run_id", run_id)
        _require_step_name(step_name)
        raw = self._run(
            """
SELECT COALESCE(
  (SELECT pg_catalog.jsonb_agg(pg_catalog.to_jsonb(s)) FROM cordis.llm_checkpoint(
      d.payload->>'run_id',
      d.payload->>'step_name'
  ) AS s),
  '[]'::pg_catalog.jsonb
)
FROM (SELECT $TAG$::pg_catalog.jsonb AS payload) AS d
""",
            {"run_id": run_id, "step_name": step_name},
        )
        if not isinstance(raw, list):
            raise CordisProtocolError("llm_checkpoint must return a JSON array")
        if len(raw) == 0:
            return None
        if len(raw) != 1 or not isinstance(raw[0], dict):
            raise CordisProtocolError("llm_checkpoint returned multiple rows")
        return _agent_step(raw[0])

    def run_state(self, run_id: str) -> RunState:
        _require_nonblank("run_id", run_id)
        raw = self._run(
            """
SELECT COALESCE(
  (SELECT pg_catalog.to_jsonb(s) FROM cordis.run_state(d.payload->>'run_id') AS s),
  'null'::pg_catalog.jsonb
)
FROM (SELECT $TAG$::pg_catalog.jsonb AS payload) AS d
""",
            {"run_id": run_id},
        )
        if not isinstance(raw, dict):
            raise CordisProtocolError("run_state must return one row")
        status = _parse_str(raw.get("status"))
        if status not in {"final", "error", "awaiting", "in-progress"}:
            raise CordisProtocolError("unexpected run_state status")
        return RunState(
            status=status,
            steps_used=_parse_int(raw.get("steps_used")),
            answer=_parse_optional_str(raw.get("answer")),
            error=_parse_optional_str(raw.get("error")),
        )

    def provider_idempotency_key(self, run_id: str, step_name: str) -> str:
        _require_nonblank("run_id", run_id)
        _require_step_name(step_name)
        raw = self._run(
            """
SELECT pg_catalog.to_jsonb(pg_catalog.md5((d.payload->>'run_id') || '/' || (d.payload->>'step_name')))
FROM (SELECT $TAG$::pg_catalog.jsonb AS payload) AS d
""",
            {"run_id": run_id, "step_name": step_name},
        )
        key = _parse_str(raw)
        if re.fullmatch(r"[0-9a-f]{32}", key) is None:
            raise CordisProtocolError("provider key must be 32 lowercase hex")
        return key

    def await_event(
        self,
        claim_token: uuid.UUID,
        run_id: str,
        event_scope_id: str,
        event_name: str,
        await_id: uuid.UUID,
        *,
        deadline: datetime | None = None,
        ui_metadata: Mapping[str, JsonValue] | None = None,
        extend_seconds: int = 90,
    ) -> AwaitEventResult:
        _require_uuid("claim_token", claim_token)
        _require_nonblank("run_id", run_id)
        _require_nonblank("event_scope_id", event_scope_id)
        _require_nonblank("event_name", event_name)
        _require_uuid("await_id", await_id)
        _require_positive_int("extend_seconds", extend_seconds)
        if deadline is not None:
            _require_aware("deadline", deadline)
        meta = {}
        if ui_metadata is None:
            meta = {}
        else:
            meta = dict(_require_mapping("ui_metadata", ui_metadata))
        raw = self._run(
            """
SELECT COALESCE(
  (SELECT pg_catalog.jsonb_agg(pg_catalog.to_jsonb(r)) FROM cordis.await_event(
      (d.payload->>'claim_token')::pg_catalog.uuid,
      d.payload->>'run_id',
      d.payload->>'event_scope_id',
      d.payload->>'event_name',
      (d.payload->>'await_id')::pg_catalog.uuid,
      NULLIF(d.payload->>'deadline', '')::pg_catalog.timestamptz,
      d.payload->'ui_metadata',
      (d.payload->>'extend_seconds')::pg_catalog.int4
  ) AS r),
  '[]'::pg_catalog.jsonb
)
FROM (SELECT $TAG$::pg_catalog.jsonb AS payload) AS d
""",
            {
                "claim_token": str(claim_token),
                "run_id": run_id,
                "event_scope_id": event_scope_id,
                "event_name": event_name,
                "await_id": str(await_id),
                "deadline": deadline.isoformat() if deadline is not None else None,
                "ui_metadata": meta,
                "extend_seconds": extend_seconds,
            },
        )
        if not isinstance(raw, list) or len(raw) != 1 or not isinstance(raw[0], dict):
            raise CordisProtocolError("await_event must return one row")
        row = raw[0]
        accepted = _parse_bool(row.get("accepted"))
        should_suspend = _parse_bool(row.get("should_suspend"))
        if not accepted and should_suspend:
            raise CordisProtocolError("await_event combination is invalid")
        return AwaitEventResult(
            accepted=accepted,
            should_suspend=should_suspend,
            payload=row.get("payload"),
            source_run_id=_parse_optional_str(row.get("source_run_id")),
            source_seq=_parse_optional_int(row.get("source_seq")),
        )

    def sleep_claim(
        self,
        claim_token: uuid.UUID,
        run_id: str,
        until: datetime,
        extend_seconds: int = 90,
    ) -> bool:
        _require_uuid("claim_token", claim_token)
        _require_nonblank("run_id", run_id)
        _require_aware("until", until)
        _require_positive_int("extend_seconds", extend_seconds)
        present = self._run(
            "SELECT pg_catalog.to_jsonb(pg_catalog.to_regprocedure("
            "'cordis.sleep_claim(uuid,text,timestamptz,integer)'::pg_catalog.text) "
            "IS NOT NULL)",
            {},
        )
        if present is not True:
            raise CordisFeatureUnavailable("P10_SLEEP_UNAVAILABLE")
        try:
            return self._as_bool(
                self._run(
                    """
SELECT pg_catalog.to_jsonb(cordis.sleep_claim(
    (d.payload->>'claim_token')::pg_catalog.uuid,
    d.payload->>'run_id',
    (d.payload->>'until')::pg_catalog.timestamptz,
    (d.payload->>'extend_seconds')::pg_catalog.int4
))
FROM (SELECT $TAG$::pg_catalog.jsonb AS payload) AS d
""",
                    {
                        "claim_token": str(claim_token),
                        "run_id": run_id,
                        "until": until.isoformat(),
                        "extend_seconds": extend_seconds,
                    },
                )
            )
        except CordisSqlError as exc:
            if exc.sqlstate == "42883":
                raise CordisFeatureUnavailable("P10_SLEEP_UNAVAILABLE") from None
            raise

    def recall_named_corpus(
        self, run_id: str, slice_id: uuid.UUID, corpus_id: str
    ) -> NamedCorpusRef | None:
        _require_nonblank("run_id", run_id)
        _require_uuid("slice_id", slice_id)
        _require_nonblank("corpus_id", corpus_id)
        raw = self._run(
            """
SELECT COALESCE(
  (SELECT pg_catalog.jsonb_agg(pg_catalog.to_jsonb(r)) FROM cordis.recall_named_corpus(
      d.payload->>'run_id',
      (d.payload->>'slice_id')::pg_catalog.uuid,
      d.payload->>'corpus_id'
  ) AS r),
  '[]'::pg_catalog.jsonb
)
FROM (SELECT $TAG$::pg_catalog.jsonb AS payload) AS d
""",
            {
                "run_id": run_id,
                "slice_id": str(slice_id),
                "corpus_id": corpus_id,
            },
        )
        if not isinstance(raw, list):
            raise CordisProtocolError("recall must return a JSON array")
        if len(raw) == 0:
            return None
        if len(raw) != 1 or not isinstance(raw[0], dict):
            raise CordisProtocolError("recall returned an unexpected row set")
        row = raw[0]
        return NamedCorpusRef(
            grant_id=_parse_uuid(row.get("grant_id")),
            corpus_id=_parse_str(row.get("corpus_id")),
            label=_parse_str(row.get("label")),
        )

    def fold_slice_messages(
        self, run_id: str, slice_id: uuid.UUID, paradigm: str
    ) -> Mapping[str, JsonValue]:
        _require_nonblank("run_id", run_id)
        _require_uuid("slice_id", slice_id)
        _require_nonblank("paradigm", paradigm)
        raw = self._run(
            """
SELECT cordis.fold_slice_messages(
    d.payload->>'run_id',
    (d.payload->>'slice_id')::pg_catalog.uuid,
    d.payload->>'paradigm'
)
FROM (SELECT $TAG$::pg_catalog.jsonb AS payload) AS d
""",
            {
                "run_id": run_id,
                "slice_id": str(slice_id),
                "paradigm": paradigm,
            },
        )
        if not isinstance(raw, dict):
            raise CordisProtocolError("fold must return a JSON object")
        return raw

    def read_run_env(
        self, run_id: str, slice_id: uuid.UUID, paradigm: str, key: str
    ) -> JsonValue:
        _require_nonblank("run_id", run_id)
        _require_uuid("slice_id", slice_id)
        _require_nonblank("paradigm", paradigm)
        _require_nonblank("key", key)
        return self._run(
            """
SELECT cordis.read_run_env(
    d.payload->>'run_id',
    (d.payload->>'slice_id')::pg_catalog.uuid,
    d.payload->>'paradigm',
    d.payload->>'key'
)
FROM (SELECT $TAG$::pg_catalog.jsonb AS payload) AS d
""",
            {
                "run_id": run_id,
                "slice_id": str(slice_id),
                "paradigm": paradigm,
                "key": key,
            },
        )

    def authorize_host_tool(
        self,
        run_id: str,
        slice_id: uuid.UUID,
        identity: str,
        bindings: Mapping[str, JsonValue],
    ) -> AuthorizedHostTool:
        _require_nonblank("run_id", run_id)
        _require_uuid("slice_id", slice_id)
        requested = _require_nonblank("identity", identity).strip()
        binding_obj = dict(_require_mapping("bindings", bindings))
        raw = self._run(
            """
SELECT cordis.authorize_tool_dispatch(
    d.payload->>'run_id',
    (d.payload->>'slice_id')::pg_catalog.uuid,
    d.payload->>'identity',
    d.payload->'bindings'
)
FROM (SELECT $TAG$::pg_catalog.jsonb AS payload) AS d
""",
            {
                "run_id": run_id,
                "slice_id": str(slice_id),
                "identity": requested,
                "bindings": binding_obj,
            },
        )
        if not isinstance(raw, dict):
            raise CordisProtocolError("authorization descriptor must be an object")
        returned_identity = _parse_str(raw.get("identity"))
        if returned_identity != requested:
            raise CordisProtocolError("descriptor identity mismatch")
        if _parse_str(raw.get("locus")) != "host":
            raise CordisProtocolError("authorized tool must have locus=host")
        if _parse_str(raw.get("invocation")) != "host_tool":
            raise CordisProtocolError("authorized tool must have invocation=host_tool")
        if raw.get("entrypoint") is not None:
            raise CordisProtocolError("authorized tool entrypoint must be null")
        if _parse_str(raw.get("effect_class")) != "read_only":
            raise CordisProtocolError("authorized tool must be read_only")
        if _parse_str(raw.get("retry_class")) != "replayable":
            raise CordisProtocolError("authorized tool must be replayable")
        if _parse_str(raw.get("reconciliation")) != "none":
            raise CordisProtocolError("authorized tool reconciliation must be none")
        returned_bindings = raw.get("bindings")
        if not isinstance(returned_bindings, dict) or returned_bindings != binding_obj:
            raise CordisProtocolError("descriptor bindings mismatch")
        grants = _grants_tuple(raw.get("required_grants"))
        return AuthorizedHostTool(
            identity=returned_identity,
            name=_parse_str(raw.get("name")),
            description=_parse_str(raw.get("description")),
            version=_parse_str(raw.get("version")),
            locus="host",
            invocation="host_tool",
            required_grants=grants,
            bindings=returned_bindings,
            effect_class="read_only",
            retry_class="replayable",
            reconciliation="none",
            entrypoint=None,
            session_scope=_parse_str(raw.get("session_scope")),
            capability=raw.get("capability"),
            config=raw.get("config"),
            inject=raw.get("inject"),
            provide=raw.get("provide"),
            intercept=raw.get("intercept"),
            descriptor=raw,
        )

    def register_host_plugin(self, definition: Mapping[str, JsonValue]) -> str:
        mapping = _require_mapping("definition", definition)
        raw = self._run(
            """
SELECT pg_catalog.to_jsonb(cordis.register_host_plugin(d.payload->'definition'))
FROM (SELECT $TAG$::pg_catalog.jsonb AS payload) AS d
""",
            {"definition": dict(mapping)},
        )
        return _parse_str(raw)

    def unregister_host_plugin(self, identity: str) -> bool:
        _require_nonblank("identity", identity)
        return self._as_bool(
            self._run(
                """
SELECT pg_catalog.to_jsonb(cordis.unregister_host_plugin(d.payload->>'identity'))
FROM (SELECT $TAG$::pg_catalog.jsonb AS payload) AS d
""",
                {"identity": identity},
            )
        )

    def get_plugin(self, identity: str) -> PluginCatalogEntry | None:
        _require_nonblank("identity", identity)
        raw = self._run(
            """
SELECT COALESCE(
  (SELECT pg_catalog.to_jsonb(c) FROM cordis.plugin_catalog AS c
    WHERE c.identity = d.payload->>'identity'),
  'null'::pg_catalog.jsonb
)
FROM (SELECT $TAG$::pg_catalog.jsonb AS payload) AS d
""",
            {"identity": identity},
        )
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise CordisProtocolError("get_plugin must return an object or null")
        return _plugin_entry(raw)

    def _bool_token_call(
        self,
        fn: str,
        claim_token: uuid.UUID,
        *,
        extra_sql: str = "",
        extra_payload: Mapping[str, JsonValue] | None = None,
    ) -> bool:
        _require_uuid("claim_token", claim_token)
        payload: dict[str, JsonValue] = {"claim_token": str(claim_token)}
        if extra_payload:
            payload.update(extra_payload)
        return self._as_bool(
            self._run(
                f"""
SELECT pg_catalog.to_jsonb({fn}(
    (d.payload->>'claim_token')::pg_catalog.uuid{extra_sql}
))
FROM (SELECT $TAG$::pg_catalog.jsonb AS payload) AS d
""",
                payload,
            )
        )

    def _as_bool(self, raw: JsonValue) -> bool:
        return _parse_bool(raw)

    def _run(
        self,
        template: str,
        envelope: JsonValue,
        *,
        envelope_is_text: bool = False,
    ) -> JsonValue:
        if envelope_is_text:
            if not isinstance(envelope, str):
                raise CordisInputError("text envelope must be a string")
            encoded = envelope
        else:
            try:
                encoded = json.dumps(
                    envelope,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                )
            except (TypeError, ValueError):
                raise CordisInputError("arguments are not JSON-serializable") from None
        if "\x00" in encoded or "\\u0000" in encoded:
            raise CordisInputError("arguments must not contain NUL")
        if len(encoded.encode("utf-8")) > _MAX_ENVELOPE:
            raise CordisInputError("argument envelope exceeds 8 MiB")
        tag = self._quote_tag(encoded)
        sql = template.replace("$TAG$", f"${tag}${encoded}${tag}$")
        try:
            proc = subprocess.run(
                [self._psql_path, self._dsn, *_PSQL_FLAGS],
                input=sql.encode("utf-8"),
                capture_output=True,
                check=False,
                timeout=self._timeout,
                shell=False,
            )
        except FileNotFoundError:
            raise CordisHostError("psql executable is not available") from None
        except subprocess.TimeoutExpired:
            raise CordisCommandTimeout("psql command timed out") from None
        if proc.returncode != 0:
            combined = proc.stdout.decode("utf-8", errors="replace") + proc.stderr.decode(
                "utf-8", errors="replace"
            )
            raise CordisSqlError(
                proc.returncode,
                combined.replace(self._dsn, "[dsn]"),
                _sqlstate_from_output(combined),
            )
        try:
            stdout = proc.stdout.decode("utf-8")
        except UnicodeDecodeError:
            raise CordisProtocolError("psql output was not valid UTF-8") from None
        text = stdout.strip()
        if text == "":
            raise CordisProtocolError("psql returned no JSON document")
        if "\n" in text:
            raise CordisProtocolError("psql returned multiple output lines")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            raise CordisProtocolError("psql returned malformed JSON") from None

    @staticmethod
    def _quote_tag(payload: str) -> str:
        for _ in range(16):
            tag = "e" + secrets.token_hex(16)
            if tag not in payload:
                return tag
        raise CordisInputError("unable to dollar-quote argument envelope")
