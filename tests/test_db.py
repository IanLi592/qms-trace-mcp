"""数据库层：命名查询白名单与 SQLite 只读边界。"""

from __future__ import annotations

import sqlite3

import pytest

from qms_mcp import db


def test_readonly_uri_is_mode_ro_immutable():
    uri = db._readonly_uri(db.db_path())
    assert "mode=ro" in uri
    assert "immutable=1" in uri


def test_named_queries_are_select_only():
    for name, sql in db.QUERIES.items():
        assert sql.strip().lower().startswith(("select", "with")), name


def test_unknown_query_name_rejected():
    with pytest.raises(db.UnknownQueryError):
        db.fetch_all("drop_all_tables")


def test_extra_query_parameter_rejected():
    with pytest.raises(db.InvalidQueryParamsError):
        db.fetch_all("project_by_id", {"project_id": "PRJ-1001", "order_by": "id"})


def test_missing_query_parameter_rejected():
    with pytest.raises(db.InvalidQueryParamsError):
        db.fetch_all("project_by_id", {})


def test_sqlite_rejects_write_on_readonly_connection():
    connection = db.connect_readonly()
    try:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute(
                "INSERT INTO projects (id, name, phase) VALUES ('X', 'Y', 'Z')"
            )
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM projects")
    finally:
        connection.close()


def test_project_list_is_complete_and_sorted():
    projects = db.fetch_all("projects_list")
    assert [row["id"] for row in projects] == ["PRJ-1001", "PRJ-1002", "PRJ-1003"]


def test_fetch_one_unknown_project_returns_none():
    assert db.fetch_one("project_by_id", {"project_id": "PRJ-9999"}) is None
