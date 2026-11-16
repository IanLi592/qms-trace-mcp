"""Read-only SQLite access with a named-query allowlist.

三条硬约束（都在代码里强制，不依赖提示词）：

1. 连接使用 ``file:...?mode=ro&immutable=1`` URI，SQLite 层直接拒绝写入。
2. 模型输入永远不会成为 SQL 文本；所有 SQL 都是本文件里的常量。
3. 调用方只能按名字取查询，参数名也必须与 SQL 中声明的绑定参数完全一致。

因此 MCP 客户端（或背后的模型）能给数据库的输入只有两类：
项目 ID 之类的标量值，以及查询名。拼 SQL、改表、删库都没有入口。
"""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Mapping

# src/qms_mcp/db.py -> 项目根目录
ROOT = Path(__file__).resolve().parents[2]


class DatabaseError(RuntimeError):
    """数据库访问失败（不是查询本身的问题）。"""


class UnknownQueryError(DatabaseError):
    """请求了白名单之外的查询名。"""


class InvalidQueryParamsError(DatabaseError):
    """绑定参数与 SQL 声明不一致。"""


# ---------------------------------------------------------------------------
# 命名查询白名单：这里没有的 SQL，运行时一律不可达。
# 全部以 SELECT / WITH 开头，加载时还会再校验一次。
# ---------------------------------------------------------------------------
QUERIES: dict[str, str] = {
    "projects_list": """
        SELECT id, name, phase
        FROM projects
        ORDER BY id
    """,
    "project_by_id": """
        SELECT id, name, phase
        FROM projects
        WHERE id = :project_id
    """,
    "requirements_by_project": """
        SELECT id, project_id, source_doc, text, verification_method,
               acceptance_criteria, design_id, test_id
        FROM requirements
        WHERE project_id = :project_id
        ORDER BY id
    """,
    "design_items_by_project": """
        SELECT id, project_id, requirement_id
        FROM design_items
        WHERE project_id = :project_id
        ORDER BY id
    """,
    "test_records_by_project": """
        SELECT id, project_id, design_id, result, status
        FROM test_records
        WHERE project_id = :project_id
        ORDER BY id
    """,
    "dhf_items_by_project": """
        SELECT project_id, category, doc_ref, present
        FROM dhf_items
        WHERE project_id = :project_id
        ORDER BY category, doc_ref
    """,
    "sops_all": """
        SELECT id, title, version, body
        FROM sops
        ORDER BY id
    """,
    "sop_by_id": """
        SELECT id, title, version, body
        FROM sops
        WHERE id = :doc_id
    """,
    "defects_by_project": """
        SELECT id, project_id, requirement_id, severity, status
        FROM defects
        WHERE project_id = :project_id
        ORDER BY id
    """,
    "meta_all": """
        SELECT key, value
        FROM meta
        ORDER BY key
    """,
}

_PARAM_RE = re.compile(r":([A-Za-z_][A-Za-z0-9_]*)")
_SELECT_RE = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)

# 从 SQL 里反向推导每个查询允许的参数，避免白名单和 SQL 漂移。
ALLOWED_PARAMS: dict[str, frozenset[str]] = {
    name: frozenset(_PARAM_RE.findall(sql)) for name, sql in QUERIES.items()
}


def db_path() -> Path:
    """返回数据库路径；测试或部署可用 QMS_DB_PATH 覆盖。"""
    raw = os.environ.get("QMS_DB_PATH")
    return Path(raw).expanduser() if raw else ROOT / "data" / "qms.db"


def _readonly_uri(path: Path) -> str:
    # Path.as_uri() 在 Windows 上得到 file:///D:/...，SQLite 可直接识别。
    return f"{path.resolve().as_uri()}?mode=ro&immutable=1"


def connect_readonly() -> sqlite3.Connection:
    """打开只读连接。

    公开这个函数是为了让测试能直接验证 SQLite 层的写保护；
    业务代码应通过 :func:`fetch_all` / :func:`fetch_one` 访问数据。
    """
    path = db_path()
    if not path.is_file():
        raise DatabaseError(
            f"数据库不存在: {path}。请先运行 python scripts/build_fixtures.py"
        )
    conn = sqlite3.connect(_readonly_uri(path), uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def validate_query(name: str) -> str:
    """按名字取 SQL，并确认它确实是一条只读语句。"""
    if name not in QUERIES:
        raise UnknownQueryError(
            f"未登记的命名查询: {name!r}；可用查询: {', '.join(sorted(QUERIES))}"
        )
    sql = QUERIES[name]
    if not _SELECT_RE.match(sql):
        # 防御性检查：即使有人往 QUERIES 里误加了写语句，也会在这里炸掉。
        raise DatabaseError(f"命名查询 {name!r} 不是只读语句")
    return sql


def fetch_all(name: str, params: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """执行命名查询并返回全部行（dict 列表）。"""
    sql = validate_query(name)
    params = dict(params or {})
    allowed = ALLOWED_PARAMS[name]
    supplied = set(params)
    if supplied != set(allowed):
        raise InvalidQueryParamsError(
            f"查询 {name!r} 的参数不匹配：期望 {sorted(allowed)}，收到 {sorted(supplied)}"
        )

    conn = connect_readonly()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def fetch_one(name: str, params: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
    """执行命名查询并返回第一行，没有则返回 None。"""
    rows = fetch_all(name, params)
    return rows[0] if rows else None
