"""审计日志：字段形状、脱敏、错误记录、结果哈希。"""

from __future__ import annotations

import hashlib
import json
import re

import pytest

from qms_mcp import audit, server


def test_audit_record_shape_and_hash():
    result = server.list_projects()
    records = audit.read_records()
    entry = records[-1]

    assert set(entry) == {
        "schema_version",
        "timestamp",
        "tool",
        "args",
        "ok",
        "error",
        "duration_ms",
        "result_sha256",
    }
    assert entry["tool"] == "list_projects"
    assert entry["ok"] is True
    assert entry["error"] is None
    assert entry["args"] == {}
    assert entry["duration_ms"] >= 0
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", entry["timestamp"])
    assert entry["result_sha256"] == audit.result_sha256(result)


def test_result_hash_matches_manual_canonical_json():
    payload = {"b": 1, "a": [2, 3]}
    expected = hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    assert audit.result_sha256(payload) == expected
    assert audit.result_sha256({"a": [2, 3], "b": 1}) == expected


def test_audit_sanitizes_long_strings_and_bodies():
    sanitized = audit.sanitize(
        {
            "query": "长" * 300,
            "body": "完整文档正文不应进入日志",
            "nested": {"text": "秘密", "ok": True},
        }
    )
    assert sanitized["body"] == "<redacted>"
    assert sanitized["nested"]["text"] == "<redacted>"
    assert sanitized["nested"]["ok"] is True
    assert sanitized["query"].endswith("chars>")
    assert len(sanitized["query"]) < 300


def test_every_tool_call_appends_audit_record():
    server.list_projects()
    server.check_dhf_completeness("PRJ-1003")
    server.find_traceability_gaps("PRJ-1003")
    server.check_requirement_quality("PRJ-1003")
    server.search_sop("DHF", 2)
    server.draft_compliance_evidence("PRJ-1003", confirm=False)
    server.get_audit_log(5)

    records = audit.read_records()
    assert {entry["tool"] for entry in records} == {
        "list_projects",
        "check_dhf_completeness",
        "find_traceability_gaps",
        "check_requirement_quality",
        "search_sop",
        "draft_compliance_evidence",
        "get_audit_log",
    }
    assert all(entry["ok"] is True for entry in records)


def test_error_is_audited():
    with pytest.raises(ValueError):
        server.check_dhf_completeness("PRJ-9999")

    entry = audit.read_records()[-1]
    assert entry["tool"] == "check_dhf_completeness"
    assert entry["ok"] is False
    assert entry["result_sha256"] is None
    assert entry["error"].startswith("ValueError:")
    assert entry["args"] == {"project_id": "PRJ-9999"}


def test_tail_limit_and_order():
    audit.record("t1", {}, True, 1.0, result={"n": 1})
    audit.record("t2", {}, True, 2.0, result={"n": 2})
    audit.record("t3", {}, True, 3.0, result={"n": 3})

    tail = audit.tail(2)
    assert [entry["tool"] for entry in tail] == ["t2", "t3"]
    assert audit.tail(0) == []


def test_get_audit_log_returns_tail():
    server.list_projects()
    server.list_projects()
    result = server.get_audit_log(2)

    assert result["count"] == 2
    assert [entry["tool"] for entry in result["records"]] == [
        "list_projects",
        "list_projects",
    ]
    # 本次 get_audit_log 调用本身也会写审计，但不在它自己的返回结果里。
    assert audit.read_records()[-1]["tool"] == "get_audit_log"


def test_same_call_produces_same_result_hash():
    server.check_requirement_quality("PRJ-1003")
    first = audit.read_records()[-1]["result_sha256"]
    server.check_requirement_quality("PRJ-1003")
    second = audit.read_records()[-1]["result_sha256"]
    assert first == second
