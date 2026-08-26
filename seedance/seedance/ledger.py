"""Job store, spend accounting and the budget stop.

Two jobs of this module:

* Never pay twice for the same generation. A completed job is keyed by the
  fingerprint of its spec, so a repeated request is served from disk.
* Never pay more than you meant to. Every submission is costed first and checked
  against the caps; over the line, it does not go out.

SQLite via the stdlib, deliberately: the whole point is a file you can copy,
inspect with `sqlite3` and hand to an accountant.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from seedance.models import JobKind, JobRecord, JobSpec, JobStatus, Resolution

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id               TEXT PRIMARY KEY,
    run_id           TEXT NOT NULL,
    kind             TEXT NOT NULL,
    provider         TEXT NOT NULL,
    fingerprint      TEXT NOT NULL,
    spec_json        TEXT NOT NULL,
    status           TEXT NOT NULL,
    estimated_usd    REAL NOT NULL DEFAULT 0,
    actual_usd       REAL,
    tokens           INTEGER,
    provider_task_id TEXT,
    video_path       TEXT,
    error            TEXT,
    cached           INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_fingerprint_idx ON jobs (fingerprint);
CREATE INDEX IF NOT EXISTS jobs_run_idx         ON jobs (run_id);
CREATE INDEX IF NOT EXISTS jobs_created_idx     ON jobs (created_at);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Statuses that represent money committed. A failed job is not billed, so it must
# not eat the budget; a pending or running one might still land, so it does.
BILLABLE = (JobStatus.PENDING, JobStatus.RUNNING, JobStatus.SUCCEEDED)


class BudgetExceededError(RuntimeError):
    def __init__(self, window: str, spent: float, estimate: float, cap: float) -> None:
        self.window = window
        super().__init__(
            f"{window} budget would be exceeded: ${spent:.2f} already committed "
            f"+ ${estimate:.2f} for this job > ${cap:.2f} cap. "
            f"Raise it with `seedance budget --{window} <usd>` or pass --force."
        )


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _spec_to_json(spec: JobSpec) -> str:
    return json.dumps(asdict(spec), ensure_ascii=False, sort_keys=True)


def _spec_from_json(payload: str) -> JobSpec:
    raw: dict[str, Any] = json.loads(payload)
    raw["resolution"] = Resolution(raw["resolution"])
    raw["reference_images"] = tuple(raw.get("reference_images", ()))
    return JobSpec(**raw)


def _row_to_record(row: sqlite3.Row) -> JobRecord:
    return JobRecord(
        id=row["id"],
        run_id=row["run_id"],
        kind=JobKind(row["kind"]),
        provider=row["provider"],
        spec=_spec_from_json(row["spec_json"]),
        fingerprint=row["fingerprint"],
        status=JobStatus(row["status"]),
        estimated_usd=row["estimated_usd"],
        actual_usd=row["actual_usd"],
        tokens=row["tokens"],
        provider_task_id=row["provider_task_id"],
        video_path=row["video_path"],
        error=row["error"],
        cached=bool(row["cached"]),
        created_at=row["created_at"],
    )


class Ledger:
    """Everything the gateway remembers about what it spent."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- writes -------------------------------------------------------------

    def record(self, job: JobRecord) -> JobRecord:
        job.created_at = job.created_at or _now()
        self._conn.execute(
            """
            INSERT INTO jobs (id, run_id, kind, provider, fingerprint, spec_json, status,
                              estimated_usd, actual_usd, tokens, provider_task_id,
                              video_path, error, cached, created_at, updated_at)
            VALUES (:id, :run_id, :kind, :provider, :fingerprint, :spec_json, :status,
                    :estimated_usd, :actual_usd, :tokens, :provider_task_id,
                    :video_path, :error, :cached, :created_at, :updated_at)
            ON CONFLICT(id) DO UPDATE SET
                status           = excluded.status,
                estimated_usd    = excluded.estimated_usd,
                actual_usd       = excluded.actual_usd,
                tokens           = excluded.tokens,
                provider_task_id = excluded.provider_task_id,
                video_path       = excluded.video_path,
                error            = excluded.error,
                updated_at       = excluded.updated_at
            """,
            {
                "id": job.id,
                "run_id": job.run_id,
                "kind": job.kind.value,
                "provider": job.provider,
                "fingerprint": job.fingerprint,
                "spec_json": _spec_to_json(job.spec),
                "status": job.status.value,
                "estimated_usd": job.estimated_usd,
                "actual_usd": job.actual_usd,
                "tokens": job.tokens,
                "provider_task_id": job.provider_task_id,
                "video_path": job.video_path,
                "error": job.error,
                "cached": int(job.cached),
                "created_at": job.created_at,
                "updated_at": _now(),
            },
        )
        self._conn.commit()
        return job

    # -- reads --------------------------------------------------------------

    def get(self, job_id: str) -> JobRecord | None:
        row = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _row_to_record(row) if row else None

    def find_completed(self, fingerprint: str) -> JobRecord | None:
        """A finished job with a file still on disk, or nothing."""
        rows = self._conn.execute(
            """
            SELECT * FROM jobs
            WHERE fingerprint = ? AND status = ? AND video_path IS NOT NULL
            ORDER BY created_at DESC
            """,
            (fingerprint, JobStatus.SUCCEEDED.value),
        ).fetchall()
        for row in rows:
            if Path(row["video_path"]).exists():
                return _row_to_record(row)
        return None

    def by_run(self, run_id: str) -> list[JobRecord]:
        rows = self._conn.execute(
            "SELECT * FROM jobs WHERE run_id = ? ORDER BY created_at", (run_id,)
        ).fetchall()
        return [_row_to_record(row) for row in rows]

    def recent(self, limit: int = 20) -> list[JobRecord]:
        rows = self._conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_row_to_record(row) for row in rows]

    def latest_run_id(self, kind: JobKind | None = None) -> str | None:
        sql = "SELECT run_id FROM jobs"
        params: tuple[str, ...] = ()
        if kind is not None:
            sql += " WHERE kind = ?"
            params = (kind.value,)
        sql += " ORDER BY created_at DESC LIMIT 1"
        row = self._conn.execute(sql, params).fetchone()
        return row["run_id"] if row else None

    # -- spend --------------------------------------------------------------

    def spend_since(self, since: datetime) -> float:
        placeholders = ", ".join("?" for _ in BILLABLE)
        row = self._conn.execute(
            f"""
            SELECT COALESCE(SUM(COALESCE(actual_usd, estimated_usd)), 0) AS total
            FROM jobs
            WHERE created_at >= ? AND cached = 0 AND status IN ({placeholders})
            """,  # noqa: S608 - placeholders are generated from a fixed tuple, not input
            (since.isoformat(timespec="seconds"), *[s.value for s in BILLABLE]),
        ).fetchone()
        return float(row["total"])

    def today_spend(self) -> float:
        now = datetime.now(UTC)
        return self.spend_since(now.replace(hour=0, minute=0, second=0, microsecond=0))

    def month_spend(self) -> float:
        now = datetime.now(UTC)
        return self.spend_since(now.replace(day=1, hour=0, minute=0, second=0, microsecond=0))

    # -- budget -------------------------------------------------------------

    def set_cap(self, window: str, usd: float) -> None:
        self._conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (f"budget_{window}", str(usd)),
        )
        self._conn.commit()

    def cap(self, window: str, fallback: float) -> float:
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = ?", (f"budget_{window}",)
        ).fetchone()
        return float(row["value"]) if row else fallback

    def assert_within_budget(self, estimate: float, *, daily: float, monthly: float) -> None:
        """Refuse a submission that would take committed spend past a cap."""
        for window, cap, spent in (
            ("daily", self.cap("daily", daily), self.today_spend()),
            ("monthly", self.cap("monthly", monthly), self.month_spend()),
        ):
            if cap > 0 and spent + estimate > cap:
                raise BudgetExceededError(window, spent, estimate, cap)


@contextmanager
def open_ledger(path: Path) -> Iterator[Ledger]:
    ledger = Ledger(path)
    try:
        yield ledger
    finally:
        ledger.close()
