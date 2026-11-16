"""pytest 公共夹具。

- 会话开始时重建合成数据库，保证测试断言的是固定夹具。
- 每个测试使用独立的审计日志与 output 目录，避免污染仓库。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

for candidate in (ROOT / "src", ROOT / "scripts"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import build_fixtures  # noqa: E402  (path 已注入)


@pytest.fixture(scope="session", autouse=True)
def built_database() -> Path:
    database = ROOT / "data" / "qms.db"
    os.environ["QMS_DB_PATH"] = str(database)
    build_fixtures.build()
    return database


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QMS_AUDIT_PATH", str(tmp_path / "logs" / "audit.jsonl"))
    monkeypatch.setenv("QMS_OUTPUT_DIR", str(tmp_path / "output"))
