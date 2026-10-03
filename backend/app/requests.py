from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import get_current_user, get_db, require_roles
from app.models import (
    Assignment,
    DatasetRequest,
    RequestStatus,
    RequestStatusHistory,
    User,
    UserRole,
)

TASK_NAME_MAX = 200
NOTES_MAX = 2_000
EPISODES_MAX = 100_000
DEADLINE_DAYS = 365 * 5
NOT_FOUND = "Request not found"
INVALID_TRANSITION = "Invalid status transition"
SHORT_DELIVERY = "Not enough episodes assigned"

_STAFF = "staff"
_OWNER = "owner"
_STAFF_ROLES = {UserRole.OPERATOR.value, UserRole.ADMIN.value}
_TRANSITIONS: dict[tuple[str, str], str] = {
    (RequestStatus.SUBMITTED.value, RequestStatus.IN_PROGRESS.value): _STAFF,
    (RequestStatus.IN_PROGRESS.value, RequestStatus.DELIVERED.value): _STAFF,
    (RequestStatus.DELIVERED.value, RequestStatus.ACCEPTED.value): _OWNER,
    (RequestStatus.DELIVERED.value, RequestStatus.REJECTED.value): _OWNER,
    (RequestStatus.REJECTED.value, RequestStatus.IN_PROGRESS.value): _STAFF,
}

router = APIRouter(prefix="/requests")
client_only = require_roles(UserRole.CLIENT)


class RequestCreate(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    task_name: str = Field(min_length=1, max_length=TASK_NAME_MAX)
    episodes_requested: int = Field(ge=1, le=EPISODES_MAX)
    deadline: date
    notes: str | None = Field(default=None, max_length=NOTES_MAX)

    @field_validator("notes")
    @classmethod
    def blank_notes_are_empty(cls, value: str | None) -> str | None:
        if not value:
            return None
        return value

    @field_validator("deadline")
    @classmethod
    def deadline_in_range(cls, value: date) -> date:
        today = datetime.now(UTC).date()
        if value < today or value > today + timedelta(days=DEADLINE_DAYS):
            raise ValueError("deadline is out of range")
        return value


class TransitionIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: RequestStatus


class HistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_status: str | None
    to_status: str
    actor_user_id: int
    changed_at: datetime


class RequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    client_id: int
    task_name: str
    episodes_requested: int
    deadline: date
    notes: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class RequestDetailOut(RequestOut):
    status_history: list[HistoryOut]


def assigned_episode_count(db: Session, request_id: int) -> int:
    # Assignment writes these rows. Delivery only checks the count.
    counted = db.scalar(
        select(func.count()).select_from(Assignment).where(Assignment.request_id == request_id)
    )
    return int(counted or 0)


def _hidden(actor: User, row: DatasetRequest) -> bool:
    return actor.role == UserRole.CLIENT.value and row.client_id != actor.id


def load_request(
    db: Session, request_id: int, actor: User, *, lock: bool = False
) -> DatasetRequest:
    stmt = select(DatasetRequest).where(DatasetRequest.id == request_id)
    if lock:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if row is None or _hidden(actor, row):
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return row


def apply_transition(db: Session, row: DatasetRequest, actor: User, target: str) -> None:
    rule = _TRANSITIONS.get((row.status, target))
    if rule is None:
        raise HTTPException(status_code=409, detail=INVALID_TRANSITION)
    if rule == _STAFF and actor.role not in _STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Forbidden")
    owns_row = actor.role == UserRole.CLIENT.value and actor.id == row.client_id
    if rule == _OWNER and not owns_row:
        raise HTTPException(status_code=403, detail="Forbidden")
    if (
        target == RequestStatus.DELIVERED.value
        and assigned_episode_count(db, row.id) < row.episodes_requested
    ):
        raise HTTPException(status_code=409, detail=SHORT_DELIVERY)

    previous = row.status
    row.status = target
    row.updated_at = datetime.now(UTC)
    db.add(
        RequestStatusHistory(
            request_id=row.id,
            from_status=previous,
            to_status=target,
            actor_user_id=actor.id,
        )
    )
    db.commit()


@router.post("", response_model=RequestDetailOut, status_code=201)
def create_request(
    body: RequestCreate,
    db: Session = Depends(get_db),
    user: User = Depends(client_only),
) -> DatasetRequest:
    row = DatasetRequest(
        client_id=user.id,
        task_name=body.task_name,
        episodes_requested=body.episodes_requested,
        deadline=body.deadline,
        notes=body.notes,
        status=RequestStatus.SUBMITTED,
    )
    db.add(row)
    db.flush()
    db.add(
        RequestStatusHistory(
            request_id=row.id,
            from_status=None,
            to_status=RequestStatus.SUBMITTED,
            actor_user_id=user.id,
        )
    )
    db.commit()
    db.refresh(row)
    return row


@router.get("", response_model=list[RequestOut])
def list_requests(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DatasetRequest]:
    stmt = select(DatasetRequest).order_by(DatasetRequest.id.desc())
    if user.role == UserRole.CLIENT.value:
        stmt = stmt.where(DatasetRequest.client_id == user.id)
    return list(db.scalars(stmt))


@router.get("/{request_id}", response_model=RequestDetailOut)
def get_request(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DatasetRequest:
    return load_request(db, request_id, user)


@router.post("/{request_id}/transitions", response_model=RequestDetailOut)
def transition_request(
    request_id: int,
    body: TransitionIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DatasetRequest:
    row = load_request(db, request_id, user, lock=True)
    apply_transition(db, row, user, body.status)
    db.refresh(row)
    return row
