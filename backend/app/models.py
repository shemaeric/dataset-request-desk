from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class UserRole(StrEnum):
    CLIENT = "client"
    OPERATOR = "operator"
    ADMIN = "admin"


class EpisodeQuality(StrEnum):
    GOOD = "good"
    USABLE = "usable"
    BAD = "bad"


class RequestStatus(StrEnum):
    SUBMITTED = "submitted"
    IN_PROGRESS = "in_progress"
    DELIVERED = "delivered"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


def _sql_list(members: type[StrEnum]) -> str:
    return ", ".join(f"'{member.value}'" for member in members)


def _nonblank(column: str, name: str) -> CheckConstraint:
    return CheckConstraint(f"char_length(btrim({column})) > 0", name=name)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        CheckConstraint(f"role IN ({_sql_list(UserRole)})", name="ck_users_role"),
        CheckConstraint("email = lower(email)", name="ck_users_email_lowercase"),
        _nonblank("email", "ck_users_email_not_blank"),
        _nonblank("name", "ck_users_name_not_blank"),
        _nonblank("password_hash", "ck_users_password_hash_not_blank"),
        CheckConstraint(
            "organisation IS NULL OR char_length(btrim(organisation)) > 0",
            name="ck_users_organisation_not_blank",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    organisation: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    requests: Mapped[list[DatasetRequest]] = relationship(back_populates="client")


class Episode(Base):
    __tablename__ = "episodes"
    __table_args__ = (
        UniqueConstraint("source_episode_id", name="uq_episodes_source_episode_id"),
        CheckConstraint(
            f"quality IN ({_sql_list(EpisodeQuality)})",
            name="ck_episodes_quality",
        ),
        CheckConstraint("duration_seconds > 0", name="ck_episodes_duration_positive"),
        _nonblank("source_episode_id", "ck_episodes_source_episode_id_not_blank"),
        _nonblank("robot_id", "ck_episodes_robot_id_not_blank"),
        _nonblank("task_name", "ck_episodes_task_name_not_blank"),
        _nonblank("operator_name", "ck_episodes_operator_name_not_blank"),
        Index("ix_episodes_recorded_at_robot_id", "recorded_at", "robot_id"),
        Index("ix_episodes_quality_task_name", "quality", "task_name"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    source_episode_id: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="CSV column episode_id from the recording export",
    )
    robot_id: Mapped[str] = mapped_column(Text, nullable=False)
    task_name: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    operator_name: Mapped[str] = mapped_column(Text, nullable=False)
    quality: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    assignment: Mapped[Assignment | None] = relationship(back_populates="episode")


class DatasetRequest(Base):
    __tablename__ = "dataset_requests"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_sql_list(RequestStatus)})",
            name="ck_dataset_requests_status",
        ),
        CheckConstraint(
            "episodes_requested > 0",
            name="ck_dataset_requests_episodes_requested_positive",
        ),
        _nonblank("task_name", "ck_dataset_requests_task_name_not_blank"),
        Index("ix_dataset_requests_client_id", "client_id"),
        Index("ix_dataset_requests_status", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    client_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    task_name: Mapped[str] = mapped_column(Text, nullable=False)
    episodes_requested: Mapped[int] = mapped_column(Integer, nullable=False)
    deadline: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="submitted")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    client: Mapped[User] = relationship(back_populates="requests")
    assignments: Mapped[list[Assignment]] = relationship(back_populates="request")
    status_history: Mapped[list[RequestStatusHistory]] = relationship(
        back_populates="request",
        order_by="RequestStatusHistory.id",
    )


class Assignment(Base):
    """One row per episode. The unique episode id is the active-assignment rule."""

    __tablename__ = "assignments"
    __table_args__ = (
        UniqueConstraint("episode_id", name="uq_assignments_episode_id"),
        Index("ix_assignments_request_id", "request_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    episode_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("episodes.id", ondelete="RESTRICT"), nullable=False
    )
    request_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dataset_requests.id", ondelete="RESTRICT"), nullable=False
    )
    assigned_by_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    episode: Mapped[Episode] = relationship(back_populates="assignment")
    request: Mapped[DatasetRequest] = relationship(back_populates="assignments")
    assigned_by: Mapped[User] = relationship()


class RequestStatusHistory(Base):
    __tablename__ = "request_status_history"
    __table_args__ = (
        CheckConstraint(
            f"to_status IN ({_sql_list(RequestStatus)})",
            name="ck_request_status_history_to_status",
        ),
        CheckConstraint(
            f"from_status IS NULL OR from_status IN ({_sql_list(RequestStatus)})",
            name="ck_request_status_history_from_status",
        ),
        Index(
            "ix_request_status_history_request_id_changed_at",
            "request_id",
            "changed_at",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    request_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dataset_requests.id", ondelete="RESTRICT"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_status: Mapped[str] = mapped_column(Text, nullable=False)
    actor_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    request: Mapped[DatasetRequest] = relationship(back_populates="status_history")
    actor: Mapped[User] = relationship()


class AuthSession(Base):
    """Login session. The cookie holds the raw token; this row stores its hash."""

    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
        Index("ix_sessions_user_id", "user_id"),
        _nonblank("token_hash", "ck_sessions_token_hash_not_blank"),
        _nonblank("csrf_token", "ck_sessions_csrf_token_not_blank"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    csrf_token: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    user: Mapped[User] = relationship()
