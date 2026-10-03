"""Prove Alembic can build the schema on an empty database.

The test creates and drops only ``dataset_request_desk_migrate_test``.
It refuses to drop the development database.
"""

import os
import re
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.models import Assignment, Episode

DEV_DATABASE = "dataset_request_desk"
TEST_DATABASE = "dataset_request_desk_migrate_test"
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_source_episode_id_and_active_assignment_are_unique() -> None:
    episode_uniques = {
        constraint.name: [column.name for column in constraint.columns]
        for constraint in Episode.__table__.constraints
        if constraint.name is not None and constraint.name.startswith("uq_")
    }
    assignment_uniques = {
        constraint.name: [column.name for column in constraint.columns]
        for constraint in Assignment.__table__.constraints
        if constraint.name is not None and constraint.name.startswith("uq_")
    }

    assert episode_uniques["uq_episodes_source_episode_id"] == ["source_episode_id"]
    assert assignment_uniques["uq_assignments_episode_id"] == ["episode_id"]


def test_migration_upgrades_empty_database(monkeypatch: pytest.MonkeyPatch) -> None:
    _recreate_database(TEST_DATABASE)
    engine = create_engine(_database_url(TEST_DATABASE))
    try:
        monkeypatch.setenv("DATABASE_URL", _database_url(TEST_DATABASE))
        config = Config(str(BACKEND_ROOT / "alembic.ini"))
        command.upgrade(config, "head")
        command.check(config)
        _assert_schema(engine)
        _assert_constraints_reject_invalid_rows(engine)
    finally:
        engine.dispose()
        _drop_database(TEST_DATABASE)


def _admin_url() -> str:
    return os.environ.get(
        "MIGRATION_ADMIN_URL",
        "postgresql+psycopg://desk:desk@127.0.0.1:5432/postgres",
    )


def _database_url(name: str) -> str:
    _guard_test_database(name)
    prefix, separator, _current = _admin_url().rpartition("/")
    if separator != "/":
        raise RuntimeError("MIGRATION_ADMIN_URL must end with a database name")
    return f"{prefix}/{name}"


def _guard_test_database(name: str) -> None:
    if name == DEV_DATABASE or not re.fullmatch(r"[a-z_]+_migrate_test", name):
        raise RuntimeError(f"refusing to create or drop database {name}")


def _admin_engine() -> Engine:
    return create_engine(_admin_url(), isolation_level="AUTOCOMMIT")


def _recreate_database(name: str) -> None:
    _guard_test_database(name)
    engine = _admin_engine()
    try:
        with engine.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": name},
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
            connection.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        engine.dispose()


def _drop_database(name: str) -> None:
    _guard_test_database(name)
    engine = _admin_engine()
    try:
        with engine.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": name},
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    finally:
        engine.dispose()


def _assert_schema(engine: Engine) -> None:
    inspected = inspect(engine)
    assert set(inspected.get_table_names()) >= {
        "users",
        "episodes",
        "dataset_requests",
        "assignments",
        "request_status_history",
        "alembic_version",
    }

    episode_uniques = inspected.get_unique_constraints("episodes")
    assert any(
        constraint["name"] == "uq_episodes_source_episode_id"
        and constraint["column_names"] == ["source_episode_id"]
        for constraint in episode_uniques
    )
    assignment_uniques = inspected.get_unique_constraints("assignments")
    assert any(
        constraint["name"] == "uq_assignments_episode_id"
        and constraint["column_names"] == ["episode_id"]
        for constraint in assignment_uniques
    )

    episode_checks = {
        constraint["name"] for constraint in inspected.get_check_constraints("episodes")
    }
    assert "ck_episodes_quality" in episode_checks
    assert "ck_episodes_duration_positive" in episode_checks

    request_checks = {
        constraint["name"] for constraint in inspected.get_check_constraints("dataset_requests")
    }
    assert "ck_dataset_requests_status" in request_checks

    user_checks = {constraint["name"] for constraint in inspected.get_check_constraints("users")}
    assert "ck_users_role" in user_checks

    assignment_fks = {
        (tuple(fk["constrained_columns"]), fk["referred_table"])
        for fk in inspected.get_foreign_keys("assignments")
    }
    assert (("episode_id",), "episodes") in assignment_fks
    assert (("request_id",), "dataset_requests") in assignment_fks
    assert (("assigned_by_user_id",), "users") in assignment_fks

    history_fks = {
        (tuple(fk["constrained_columns"]), fk["referred_table"])
        for fk in inspected.get_foreign_keys("request_status_history")
    }
    assert (("request_id",), "dataset_requests") in history_fks
    assert (("actor_user_id",), "users") in history_fks

    index_names = {index["name"] for index in inspected.get_indexes("episodes")}
    assert "ix_episodes_recorded_at_robot_id" in index_names
    assert "ix_episodes_quality_task_name" in index_names
    request_indexes = {index["name"] for index in inspected.get_indexes("dataset_requests")}
    assert "ix_dataset_requests_client_id" in request_indexes
    assert "ix_dataset_requests_status" in request_indexes


def _assert_constraints_reject_invalid_rows(engine: Engine) -> None:
    with engine.begin() as connection:
        user_id = connection.execute(
            text(
                """
                INSERT INTO users (email, password_hash, name, role)
                VALUES ('client-a@example.com', 'hashed-password', 'Acme Robotics', 'client')
                RETURNING id
                """
            )
        ).scalar_one()
        episode_id = connection.execute(
            text(
                """
                INSERT INTO episodes (
                    source_episode_id, robot_id, task_name, recorded_at,
                    duration_seconds, operator_name, quality
                )
                VALUES (
                    'EP-00156', 'mobile-01', 'stack blocks', '2026-08-16T23:28:00Z',
                    78, 'Diane', 'good'
                )
                RETURNING id
                """
            )
        ).scalar_one()
        request_id = connection.execute(
            text(
                """
                INSERT INTO dataset_requests (
                    client_id, task_name, episodes_requested, deadline
                )
                VALUES (:client_id, 'stack blocks', 1, '2026-10-04')
                RETURNING id
                """
            ),
            {"client_id": user_id},
        ).scalar_one()
        connection.execute(
            text(
                """
                INSERT INTO assignments (episode_id, request_id, assigned_by_user_id)
                VALUES (:episode_id, :request_id, :user_id)
                """
            ),
            {"episode_id": episode_id, "request_id": request_id, "user_id": user_id},
        )
        connection.execute(
            text(
                """
                INSERT INTO request_status_history (
                    request_id, from_status, to_status, actor_user_id
                )
                VALUES (:request_id, NULL, 'submitted', :user_id)
                """
            ),
            {"request_id": request_id, "user_id": user_id},
        )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO episodes (
                        source_episode_id, robot_id, task_name, recorded_at,
                        duration_seconds, operator_name, quality
                    )
                    VALUES (
                        'EP-00156', 'arm-01', 'pick cup', '2026-08-17T00:00:00Z',
                        10, 'Aline', 'usable'
                    )
                    """
                )
            )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO assignments (episode_id, request_id, assigned_by_user_id)
                    VALUES (:episode_id, :request_id, :user_id)
                    """
                ),
                {"episode_id": episode_id, "request_id": request_id, "user_id": user_id},
            )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO episodes (
                        source_episode_id, robot_id, task_name, recorded_at,
                        duration_seconds, operator_name, quality
                    )
                    VALUES (
                        'EP-00020', 'mobile-01', 'fold towel', '2026-08-11T00:14:00Z',
                        90, 'Patrick', 'excellent'
                    )
                    """
                )
            )
