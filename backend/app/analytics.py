from datetime import UTC, date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Subquery

from app.auth import get_db, require_roles
from app.models import (
    DatasetRequest,
    Episode,
    EpisodeQuality,
    RequestStatus,
    RequestStatusHistory,
    User,
    UserRole,
)

MAX_RANGE_DAYS = 366

router = APIRouter()
staff_only = require_roles(UserRole.OPERATOR, UserRole.ADMIN)


class EpisodeDay(BaseModel):
    day: date
    robot_id: str
    count: int


class StatusCount(BaseModel):
    status: str
    count: int


class TaskCount(BaseModel):
    task_name: str
    count: int


class AnalyticsOut(BaseModel):
    start_date: date
    end_date: date
    episodes_per_day: list[EpisodeDay]
    requests_by_status: list[StatusCount]
    median_seconds_to_delivery: float | None
    top_tasks: list[TaskCount]


def _window(start_date: date, end_date: date) -> tuple[datetime, datetime]:
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="end_date must be on or after start_date")
    if (end_date - start_date).days > MAX_RANGE_DAYS:
        raise HTTPException(status_code=422, detail="date range must be 366 days or less")
    start = datetime.combine(start_date, time.min, tzinfo=UTC)
    end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UTC)
    return start, end


def _submitted_between(start: datetime, end: datetime) -> Subquery:
    return (
        select(
            RequestStatusHistory.request_id.label("request_id"),
            func.min(RequestStatusHistory.changed_at).label("submitted_at"),
        )
        .where(
            RequestStatusHistory.to_status == RequestStatus.SUBMITTED.value,
            RequestStatusHistory.from_status.is_(None),
            RequestStatusHistory.changed_at >= start,
            RequestStatusHistory.changed_at < end,
        )
        .group_by(RequestStatusHistory.request_id)
        .subquery()
    )


def _first_delivery() -> Subquery:
    return (
        select(
            RequestStatusHistory.request_id.label("request_id"),
            func.min(RequestStatusHistory.changed_at).label("delivered_at"),
        )
        .where(RequestStatusHistory.to_status == RequestStatus.DELIVERED.value)
        .group_by(RequestStatusHistory.request_id)
        .subquery()
    )


def _episodes_per_day(db: Session, start: datetime, end: datetime) -> list[EpisodeDay]:
    day = cast(func.timezone("UTC", Episode.recorded_at), Date).label("day")
    rows = db.execute(
        select(day, Episode.robot_id, func.count())
        .where(Episode.recorded_at >= start, Episode.recorded_at < end)
        .group_by(day, Episode.robot_id)
        .order_by(day, Episode.robot_id)
    )
    return [
        EpisodeDay(day=recorded_day, robot_id=robot_id, count=int(count))
        for recorded_day, robot_id, count in rows
    ]


def _requests_by_status(db: Session, submitted: Subquery) -> list[StatusCount]:
    rows = db.execute(
        select(DatasetRequest.status, func.count())
        .join(submitted, submitted.c.request_id == DatasetRequest.id)
        .group_by(DatasetRequest.status)
    )
    counts = {status.value: 0 for status in RequestStatus}
    for status, count in rows:
        counts[str(status)] = int(count)
    return [
        StatusCount(status=status.value, count=counts[status.value]) for status in RequestStatus
    ]


def _median_seconds(db: Session, submitted: Subquery) -> float | None:
    delivered = _first_delivery()
    seconds = func.extract("epoch", delivered.c.delivered_at - submitted.c.submitted_at)
    value = db.scalar(
        select(func.percentile_cont(0.5).within_group(seconds.asc())).select_from(
            submitted.join(delivered, delivered.c.request_id == submitted.c.request_id)
        )
    )
    if value is None:
        return None
    return float(value)


def _top_tasks(db: Session, start: datetime, end: datetime) -> list[TaskCount]:
    counted = func.count().label("count")
    rows = db.execute(
        select(Episode.task_name, counted)
        .where(
            Episode.quality == EpisodeQuality.GOOD.value,
            Episode.recorded_at >= start,
            Episode.recorded_at < end,
        )
        .group_by(Episode.task_name)
        .order_by(counted.desc(), Episode.task_name.asc())
        .limit(5)
    )
    return [TaskCount(task_name=task_name, count=int(count)) for task_name, count in rows]


@router.get("/analytics", response_model=AnalyticsOut)
def analytics(
    start_date: date,
    end_date: date,
    db: Session = Depends(get_db),
    _user: User = Depends(staff_only),
) -> AnalyticsOut:
    start, end = _window(start_date, end_date)
    submitted = _submitted_between(start, end)
    return AnalyticsOut(
        start_date=start_date,
        end_date=end_date,
        episodes_per_day=_episodes_per_day(db, start, end),
        requests_by_status=_requests_by_status(db, submitted),
        median_seconds_to_delivery=_median_seconds(db, submitted),
        top_tasks=_top_tasks(db, start, end),
    )
