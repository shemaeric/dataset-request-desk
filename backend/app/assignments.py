from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_db, require_roles
from app.models import (
    Assignment,
    DatasetRequest,
    Episode,
    EpisodeQuality,
    RequestStatus,
    User,
    UserRole,
)
from app.requests import load_request

NOT_IN_PROGRESS = "Episodes can only be changed while the request is in progress"
ALREADY_HERE = "Episode is already assigned to this request"
ALREADY_ELSEWHERE = "Episode is already assigned to another request"
BAD_QUALITY = "Episode quality must be good or usable"
ASSIGNABLE = {EpisodeQuality.GOOD.value, EpisodeQuality.USABLE.value}

router = APIRouter(prefix="/requests")
staff_only = require_roles(UserRole.OPERATOR, UserRole.ADMIN)


class AssignmentIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    episode_id: int = Field(ge=1)


class AssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    episode_id: int
    request_id: int
    assigned_by_user_id: int
    assigned_at: datetime


def _open_for_assignment(db: Session, request_id: int, actor: User) -> DatasetRequest:
    row = load_request(db, request_id, actor, lock=True)
    if row.status != RequestStatus.IN_PROGRESS.value:
        raise HTTPException(status_code=409, detail=NOT_IN_PROGRESS)
    return row


def _lock_episode(db: Session, episode_id: int) -> Episode:
    episode = db.scalar(select(Episode).where(Episode.id == episode_id).with_for_update())
    if episode is None:
        raise HTTPException(status_code=404, detail="Episode not found")
    return episode


@router.post("/{request_id}/assignments", response_model=AssignmentOut, status_code=201)
def assign_episode(
    request_id: int,
    body: AssignmentIn,
    db: Session = Depends(get_db),
    user: User = Depends(staff_only),
) -> Assignment:
    request_row = _open_for_assignment(db, request_id, user)
    episode = _lock_episode(db, body.episode_id)
    if episode.quality not in ASSIGNABLE:
        raise HTTPException(status_code=409, detail=BAD_QUALITY)

    current = db.scalar(select(Assignment).where(Assignment.episode_id == episode.id))
    if current is not None:
        detail = ALREADY_HERE if current.request_id == request_row.id else ALREADY_ELSEWHERE
        raise HTTPException(status_code=409, detail=detail)

    row = Assignment(
        episode_id=episode.id,
        request_id=request_row.id,
        assigned_by_user_id=user.id,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=ALREADY_ELSEWHERE) from None
    db.refresh(row)
    return row


@router.delete("/{request_id}/assignments/{episode_id}", status_code=204)
def remove_assignment(
    request_id: int,
    episode_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(staff_only),
) -> None:
    request_row = _open_for_assignment(db, request_id, user)
    episode = _lock_episode(db, episode_id)
    row = db.scalar(
        select(Assignment).where(
            Assignment.request_id == request_row.id,
            Assignment.episode_id == episode.id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Assignment not found")
    db.delete(row)
    db.commit()
