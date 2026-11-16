"""JSONL 审计日志。

每次 MCP 工具调用写一行，字段固定：

- ``timestamp``：UTC ISO-8601，毫秒精度，以 Z 结尾
- ``tool``：工具名
- ``args``：脱敏后的参数（长字符串截断，文档正文类字段直接替换）
- ``ok``：成功 / 失败
- ``error``：失败时的异常类型与消息（截断）
- ``duration_ms``：耗时
- ``result_sha256``：工具结果的规范化 JSON 的 sha256（失败时为 null）

结果哈希让「同一个输入是否产生了同一个输出」可以被离线复现和比对。
审计文件本身不参与确定性比较。
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]

SCHEMA_VERSION = 1
MAX_STRING = 120
MAX_ITEMS = 20
MAX_DEPTH = 4

# 这些键即使出现在参数里也不写入日志，只记录占位符。
SENSITIVE_KEYS = frozenset(
    {
        "body",
        "text",
        "content",
        "document",
        "doc_body",
        "sop_body",
        "full_text",
    }
)

_LOCK = threading.Lock()


def audit_path() -> Path:
    """返回审计文件路径；测试或部署可用 QMS_AUDIT_PATH 覆盖。"""
    raw = os.environ.get("QMS_AUDIT_PATH")
    return Path(raw).expanduser() if raw else ROOT / "logs" / "audit.jsonl"


def canonical_json(value: Any) -> str:
    """稳定的 JSON 表示：键排序、无多余空白、保留中文。"""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def result_sha256(result: Any) -> str:
    """工具结果的 sha256，用于判断两次调用是否产生同一结果。"""
    return hashlib.sha256(canonical_json(result).encode("utf-8")).hexdigest()


def _truncate_string(value: str) -> str:
    if len(value) <= MAX_STRING:
        return value
    return f"{value[:MAX_STRING]}…<truncated {len(value)} chars>"


def sanitize(value: Any, _depth: int = 0) -> Any:
    """递归脱敏参数，绝不把完整文档正文写进日志。"""
    if _depth > MAX_DEPTH:
        return "<max-depth>"

    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_ITEMS:
                out["<truncated>"] = f"<{len(value) - MAX_ITEMS} more keys>"
                break
            key_str = str(key)
            if key_str.lower() in SENSITIVE_KEYS:
                out[key_str] = "<redacted>"
            else:
                out[key_str] = sanitize(item, _depth + 1)
        return out

    if isinstance(value, (list, tuple)):
        items = [sanitize(item, _depth + 1) for item in value[:MAX_ITEMS]]
        if len(value) > MAX_ITEMS:
            items.append(f"<truncated {len(value) - MAX_ITEMS} items>")
        return items

    if isinstance(value, str):
        return _truncate_string(value)

    if value is None or isinstance(value, (bool, int, float)):
        return value

    return _truncate_string(str(value))


def record(
    tool: str,
    args: Mapping[str, Any] | None,
    ok: bool,
    duration_ms: float,
    *,
    result: Any = None,
    result_hash: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """追加一条审计记录并返回它。"""
    if result_hash is None and ok:
        result_hash = result_sha256(result)

    entry: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "tool": tool,
        "args": sanitize(dict(args or {})),
        "ok": bool(ok),
        "error": _truncate_string(error) if error else None,
        "duration_ms": round(float(duration_ms), 3),
        "result_sha256": result_hash if ok else None,
    }

    path = audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = canonical_json(entry)
    with _LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
    return entry


def read_records() -> list[dict[str, Any]]:
    """读取全部审计记录（跳过空行与损坏行）。"""
    path = audit_path()
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                records.append(parsed)
    return records


def tail(limit: int = 20) -> list[dict[str, Any]]:
    """返回最近 ``limit`` 条记录，按写入顺序（旧 -> 新）。"""
    if limit < 0:
        limit = 0
    records = read_records()
    if limit == 0:
        return []
    return records[-limit:]
