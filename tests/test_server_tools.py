"""MCP 服务端：工具注册、资源、提示词、确定性与错误处理。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from qms_mcp import server

SRC = Path(__file__).resolve().parents[1] / "src" / "qms_mcp"


def _run(coroutine):
    return asyncio.run(coroutine)


EXPECTED_TOOLS = [
    "list_projects",
    "check_dhf_completeness",
    "find_traceability_gaps",
    "check_requirement_quality",
    "search_sop",
    "draft_compliance_evidence",
    "get_audit_log",
]


def test_all_seven_tools_registered():
    tools = _run(server.mcp.list_tools())
    assert sorted(tool.name for tool in tools) == sorted(EXPECTED_TOOLS)
    assert len(tools) == 7


def test_resources_and_templates_registered():
    resources = _run(server.mcp.list_resources())
    templates = _run(server.mcp.list_resource_templates())
    assert [str(resource.uri) for resource in resources] == ["qms://dhf/index"]
    assert sorted(template.uriTemplate for template in templates) == [
        "qms://sop/{doc_id}",
        "qms://trace/matrix/{project_id}",
    ]


def test_prompt_registered():
    prompts = _run(server.mcp.list_prompts())
    assert [prompt.name for prompt in prompts] == ["review_gate_checklist"]


def test_dhf_index_resource_content():
    text = server.dhf_index()
    assert "DHF 类别核查清单" in text
    assert "PRJ-1001" in text and "PRJ-1003" in text
    assert "变更记录" in text
    assert "汇总：已具备 12，不完整 2，缺失 1。" in text
    assert "合成测试夹具" in text


def test_trace_matrix_resource_content():
    text = server.trace_matrix("PRJ-1003")
    assert "需求追溯矩阵" in text
    assert "R-3002" in text
    assert "缺设计" in text
    assert "D-3006" in text
    assert "T-3002" in text
    assert "孤儿设计项：D-3006、D-3007" in text


def test_sop_resource_content_and_version():
    text = server.sop_detail("SOP-QMS-003")
    assert "风险管理程序" in text
    assert "版本：4.0" in text
    assert "合成测试数据" in text
    with pytest.raises(ValueError):
        server.sop_detail("SOP-QMS-999")


def test_review_gate_prompt_contains_tool_steps():
    text = server.review_gate_checklist("PRJ-1003")
    for tool_name in (
        "check_dhf_completeness",
        "find_traceability_gaps",
        "check_requirement_quality",
        "search_sop",
        "draft_compliance_evidence",
    ):
        assert tool_name in text
    assert "gate" in text
    assert "合成测试夹具" in text
    assert "不是自动合规判定" in text


def test_tool_calls_are_deterministic():
    calls = [
        lambda: server.list_projects(),
        lambda: server.check_dhf_completeness("PRJ-1003"),
        lambda: server.find_traceability_gaps("PRJ-1003"),
        lambda: server.check_requirement_quality("PRJ-1003"),
        lambda: server.search_sop("风险", 3),
        lambda: server.draft_compliance_evidence("PRJ-1003", confirm=False),
    ]
    for call in calls:
        first = json.dumps(call(), ensure_ascii=False, sort_keys=True)
        second = json.dumps(call(), ensure_ascii=False, sort_keys=True)
        assert first == second


def test_unknown_project_rejected():
    for call in (
        lambda: server.check_dhf_completeness("PRJ-9999"),
        lambda: server.find_traceability_gaps("PRJ-9999"),
        lambda: server.check_requirement_quality("PRJ-9999"),
        lambda: server.draft_compliance_evidence("PRJ-9999", confirm=False),
    ):
        with pytest.raises(ValueError, match="未知项目"):
            call()

    with pytest.raises(ValueError):
        server.check_dhf_completeness("")


def test_no_llm_sdk_imports_in_source():
    forbidden = ("openai", "anthropic", "langchain", "llama_index", "google.generativeai")
    for path in SRC.glob("*.py"):
        source = path.read_text(encoding="utf-8").lower()
        for name in forbidden:
            assert name not in source, f"{path.name} 含有 {name}"
