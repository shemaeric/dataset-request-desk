import csv
import io
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.auth import get_db, require_roles
from app.models import Episode, EpisodeQuality, User, UserRole

COLUMNS = (
    "episode_id",
    "robot_id",
    "task_name",
    "recorded_at",
    "duration_seconds",
    "operator_name",
    "quality",
)
KNOWN_ROBOTS = frozenset({"arm-01", "arm-02", "arm-03", "mobile-01", "humanoid-01"})
MAX_UPLOAD_BYTES = 32 * 1024 * 1024
MAX_REPORTED_ERRORS = 100
QUALITIES = {quality.value for quality in EpisodeQuality}

router = APIRouter(prefix="/episodes")
staff_only = require_roles(UserRole.OPERATOR, UserRole.ADMIN)


class ImportFileError(Exception):
    def __init__(self, detail: str) -> None:
        self.detail = detail


@dataclass(frozen=True)
class ParsedEpisode:
    source_episode_id: str
    robot_id: str
    task_name: str
    recorded_at: datetime
    duration_seconds: int
    operator_name: str
    quality: str


class RowError(BaseModel):
    row: int
    episode_id: str | None
    reason: str


class ImportReport(BaseModel):
    created: int
    skipped: int
    conflicts: int
    invalid: int
    errors: list[RowError]


class EpisodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_episode_id: str
    robot_id: str
    task_name: str
    recorded_at: datetime
    duration_seconds: int
    operator_name: str
    quality: str


class EpisodePage(BaseModel):
    items: list[EpisodeOut]
    total: int
    limit: int
    offset: int


def _cell(row: dict[str, str | None], column: str) -> str:
    return str(row.get(column) or "").strip()


def _task_name(value: str) -> str:
    return " ".join(value.split()).lower()


def _recorded_at(value: str) -> datetime | None:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed: datetime | None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = None
        for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _duration(value: str) -> int | None:
    if not value.isdecimal():
        return None
    number = int(value)
    if number <= 0:
        return None
    return number


def _parse_row(row: dict[str, str | None]) -> tuple[ParsedEpisode | None, str | None, str | None]:
    reasons: list[str] = []
    episode_id = _cell(row, "episode_id").upper()
    if not episode_id:
        reasons.append("episode_id is required")

    robot_id = _cell(row, "robot_id").lower()
    if not robot_id:
        reasons.append("robot_id is required")
    elif robot_id not in KNOWN_ROBOTS:
        reasons.append("unknown robot")

    task_raw = _cell(row, "task_name")
    task_name = _task_name(task_raw)
    if not task_name:
        reasons.append("task_name is required")

    recorded_raw = _cell(row, "recorded_at")
    recorded_at: datetime | None = None
    if not recorded_raw:
        reasons.append("recorded_at is required")
    else:
        recorded_at = _recorded_at(recorded_raw)
        if recorded_at is None:
            reasons.append("recorded_at is not a valid timestamp")

    duration_raw = _cell(row, "duration_seconds")
    duration: int | None = None
    if not duration_raw:
        reasons.append("duration is required")
    else:
        duration = _duration(duration_raw)
        if duration is None:
            reasons.append("duration must be a positive integer")

    operator_name = " ".join(_cell(row, "operator_name").split())
    if not operator_name:
        reasons.append("operator_name is required")

    quality = _cell(row, "quality").lower()
    if not quality:
        reasons.append("quality is required")
    elif quality not in QUALITIES:
        reasons.append("quality must be good, usable, or bad")

    if reasons or recorded_at is None or duration is None:
        return None, episode_id or None, "; ".join(reasons)
    return (
        ParsedEpisode(
            source_episode_id=episode_id,
            robot_id=robot_id,
            task_name=task_name,
            recorded_at=recorded_at,
            duration_seconds=duration,
            operator_name=operator_name,
            quality=quality,
        ),
        episode_id,
        None,
    )


def _matches(stored: Episode, parsed: ParsedEpisode) -> bool:
    return (
        stored.robot_id == parsed.robot_id
        and stored.task_name == parsed.task_name
        and stored.recorded_at == parsed.recorded_at
        and stored.duration_seconds == parsed.duration_seconds
        and stored.operator_name == parsed.operator_name
        and stored.quality == parsed.quality
    )


def _blank(row: dict[str, str | None]) -> bool:
    return all(not _cell(row, column) for column in COLUMNS)


def import_csv(db: Session, text: str) -> ImportReport:
    reader = csv.DictReader(io.StringIO(text), restval="")
    if reader.fieldnames is None:
        raise ImportFileError("CSV header must include " + ", ".join(COLUMNS))
    reader.fieldnames = [name.strip() for name in reader.fieldnames]
    missing = [column for column in COLUMNS if column not in reader.fieldnames]
    if missing:
        raise ImportFileError("CSV header is missing " + ", ".join(missing))

    created = skipped = conflicts = invalid = 0
    errors: list[RowError] = []

    def reject(row_number: int, episode_id: str | None, reason: str, *, conflict: bool) -> None:
        nonlocal conflicts, invalid
        if conflict:
            conflicts += 1
        else:
            invalid += 1
        if len(errors) < MAX_REPORTED_ERRORS:
            errors.append(RowError(row=row_number, episode_id=episode_id, reason=reason))

    for row_number, row in enumerate(reader, start=2):
        if _blank(row):
            continue
        parsed, episode_id, reason = _parse_row(row)
        if parsed is None:
            reject(row_number, episode_id, reason or "invalid row", conflict=False)
            continue
        inserted = db.scalar(
            pg_insert(Episode)
            .values(
                source_episode_id=parsed.source_episode_id,
                robot_id=parsed.robot_id,
                task_name=parsed.task_name,
                recorded_at=parsed.recorded_at,
                duration_seconds=parsed.duration_seconds,
                operator_name=parsed.operator_name,
                quality=parsed.quality,
            )
            .on_conflict_do_nothing(constraint="uq_episodes_source_episode_id")
            .returning(Episode.id)
        )
        if inserted is not None:
            created += 1
            continue
        stored = db.scalar(
            select(Episode).where(Episode.source_episode_id == parsed.source_episode_id)
        )
        if stored is not None and _matches(stored, parsed):
            skipped += 1
            continue
        reject(
            row_number,
            parsed.source_episode_id,
            f"episode {parsed.source_episode_id} already exists with different data",
            conflict=True,
        )

    return ImportReport(
        created=created,
        skipped=skipped,
        conflicts=conflicts,
        invalid=invalid,
        errors=errors,
    )


@router.post("/import", response_model=ImportReport)
def import_episodes(
    file: UploadFile,
    db: Session = Depends(get_db),
    _user: User = Depends(staff_only),
) -> ImportReport:
    payload = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="CSV file is too large")
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="CSV file must be UTF-8") from exc
    try:
        report = import_csv(db, text)
    except ImportFileError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=exc.detail) from exc
    except csv.Error as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="CSV file could not be parsed") from exc
    db.commit()
    return report


@router.get("", response_model=EpisodePage)
def list_episodes(
    task_name: str | None = None,
    quality: EpisodeQuality | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _user: User = Depends(staff_only),
) -> EpisodePage:
    rows_stmt = select(Episode)
    count_stmt = select(func.count()).select_from(Episode)
    if task_name and task_name.strip():
        cleaned = _task_name(task_name)
        rows_stmt = rows_stmt.where(Episode.task_name == cleaned)
        count_stmt = count_stmt.where(Episode.task_name == cleaned)
    if quality is not None:
        rows_stmt = rows_stmt.where(Episode.quality == quality.value)
        count_stmt = count_stmt.where(Episode.quality == quality.value)
    total = db.scalar(count_stmt)
    rows = db.scalars(rows_stmt.order_by(Episode.source_episode_id).limit(limit).offset(offset))
    return EpisodePage(
        items=[EpisodeOut.model_validate(row) for row in rows],
        total=int(total or 0),
        limit=limit,
        offset=offset,
    )
