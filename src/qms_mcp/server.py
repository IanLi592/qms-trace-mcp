"""qms-trace-mcp 的 FastMCP 服务端。

暴露 7 个工具、3 个资源、1 个提示词模板。
每个工具调用都会写一条审计日志；工具内部不调用任何 LLM。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from . import audit, db, evidence, rules

ROOT = Path(__file__).resolve().parents[2]

mcp = FastMCP(
    "qms-trace-mcp",
    instructions=(
        "医疗器械研发质量体系（QMS）只读核查工具。"
        "所有数据均为合成测试夹具；所有查询走命名白名单且数据库以只读方式打开。"
        "工具不调用 LLM，输出可通过审计日志中的结果哈希复现。"
        "draft_compliance_evidence 只生成待人工签署的草稿，不构成自动合规判定。"
    ),
)

EVIDENCE_SOP_QUERY = "设计控制 DHF 风险管理 设计验证 变更控制 缺陷 CAPA"


# ---------------------------------------------------------------------------
# 审计包装
# ---------------------------------------------------------------------------
def _audited(tool_name: str, args: dict[str, Any], fn: Callable[[], Any]) -> Any:
    started = time.perf_counter()
    try:
        result = fn()
    except Exception as exc:  # noqa: BLE001 - 审计后原样抛出
        elapsed_ms = (time.perf_counter() - started) * 1000
        audit.record(
            tool_name,
            args,
            False,
            elapsed_ms,
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    elapsed_ms = (time.perf_counter() - started) * 1000
    audit.record(tool_name, args, True, elapsed_ms, result=result)
    return result


def _require_project(project_id: str) -> dict[str, Any]:
    if not isinstance(project_id, str) or not project_id.strip():
        raise ValueError("project_id 不能为空")
    project = db.fetch_one("project_by_id", {"project_id": project_id})
    if project is None:
        raise ValueError(f"未知项目: {project_id}")
    return project


def _collect_checks(project_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    project = _require_project(project_id)
    dhf_result = rules.check_dhf_completeness(
        project_id, db.fetch_all("dhf_items_by_project", {"project_id": project_id})
    )
    trace_result = rules.find_traceability_gaps(
        project_id,
        db.fetch_all("requirements_by_project", {"project_id": project_id}),
        db.fetch_all("design_items_by_project", {"project_id": project_id}),
        db.fetch_all("test_records_by_project", {"project_id": project_id}),
        db.fetch_all("defects_by_project", {"project_id": project_id}),
    )
    quality_result = rules.check_requirement_quality(
        project_id, db.fetch_all("requirements_by_project", {"project_id": project_id})
    )
    return project, dhf_result, trace_result, quality_result


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
@mcp.tool()
def list_projects() -> list[dict[str, Any]]:
    """列出所有研发项目（合成数据），按项目编号排序。"""
    return _audited(
        "list_projects",
        {},
        lambda: db.fetch_all("projects_list"),
    )


@mcp.tool()
def check_dhf_completeness(project_id: str) -> dict[str, Any]:
    """核查项目 DHF（设计历史文档）是否覆盖全部必需类别。

    返回每类的状态（present / incomplete / missing）、文档引用和汇总计数。
    """
    return _audited(
        "check_dhf_completeness",
        {"project_id": project_id},
        lambda: _dhf_payload(project_id),
    )


def _dhf_payload(project_id: str) -> dict[str, Any]:
    project = _require_project(project_id)
    result = rules.check_dhf_completeness(
        project_id, db.fetch_all("dhf_items_by_project", {"project_id": project_id})
    )
    return {
        "project_id": project_id,
        "project_name": project["name"],
        "phase": project["phase"],
        **result,
    }


@mcp.tool()
def find_traceability_gaps(project_id: str) -> dict[str, Any]:
    """识别 需求 -> 设计 -> 测试 的追溯缺失，并给出缺陷影响面。

    包括：需求缺设计链接、需求缺测试链接、孤儿设计项、无需求来源的测试。
    缺陷影响面按严重度排序，并标注缺陷所在需求的下游链路是否完整。
    """
    return _audited(
        "find_traceability_gaps",
        {"project_id": project_id},
        lambda: _trace_payload(project_id),
    )


def _trace_payload(project_id: str) -> dict[str, Any]:
    project = _require_project(project_id)
    result = rules.find_traceability_gaps(
        project_id,
        db.fetch_all("requirements_by_project", {"project_id": project_id}),
        db.fetch_all("design_items_by_project", {"project_id": project_id}),
        db.fetch_all("test_records_by_project", {"project_id": project_id}),
        db.fetch_all("defects_by_project", {"project_id": project_id}),
    )
    return {
        "project_id": project_id,
        "project_name": project["name"],
        **result,
    }


@mcp.tool()
def check_requirement_quality(project_id: str) -> dict[str, Any]:
    """检查需求的可验证性：缺验收标准、缺验证方法、模糊措辞、不可测试。"""
    return _audited(
        "check_requirement_quality",
        {"project_id": project_id},
        lambda: _quality_payload(project_id),
    )


def _quality_payload(project_id: str) -> dict[str, Any]:
    project = _require_project(project_id)
    result = rules.check_requirement_quality(
        project_id, db.fetch_all("requirements_by_project", {"project_id": project_id})
    )
    return {
        "project_id": project_id,
        "project_name": project["name"],
        **result,
    }


@mcp.tool()
def search_sop(query: str, top_k: int = 5) -> dict[str, Any]:
    """按关键词检索 SOP，返回可引用的文档编号、标题、版本和片段。

    排序使用 BM25-lite（纯关键词，无向量、无 LLM）；top_k 收敛到 1..20。
    """
    return _audited(
        "search_sop",
        {"query": query, "top_k": top_k},
        lambda: _search_payload(query, top_k),
    )


def _search_payload(query: str, top_k: int) -> dict[str, Any]:
    effective = rules.clamp_top_k(top_k)
    hits = rules.search_sops(db.fetch_all("sops_all"), query, effective)
    return {
        "query": query.strip() if isinstance(query, str) else query,
        "top_k": effective,
        "hit_count": len(hits),
        "hits": hits,
    }


@mcp.tool()
def draft_compliance_evidence(project_id: str, confirm: bool = False) -> dict[str, Any]:
    """生成合规佐证草稿；默认只预览，不写入任何文件。

    confirm=False：返回预览 markdown 和 would_write_to 提示，拒绝写入。
    confirm=True：写入 output/evidence_<project>_<UTC时间戳>.md，返回路径与哈希。

    草稿是给审核人复核和签署的，不是自动合规判定，也不是自动归档。
    """
    return _audited(
        "draft_compliance_evidence",
        {"project_id": project_id, "confirm": confirm},
        lambda: _evidence_payload(project_id, confirm),
    )


def _evidence_payload(project_id: str, confirm: bool) -> dict[str, Any]:
    project, dhf_result, trace_result, quality_result = _collect_checks(project_id)
    sop_hits = rules.search_sops(
        db.fetch_all("sops_all"), EVIDENCE_SOP_QUERY, 5
    )

    common = {
        "project_id": project_id,
        "synthetic_data": True,
        "generated_from": [
            "check_dhf_completeness",
            "find_traceability_gaps",
            "check_requirement_quality",
            "search_sop",
        ],
    }

    if not confirm:
        preview = evidence.build_draft(
            project,
            dhf_result,
            trace_result,
            quality_result,
            sop_hits,
            generated_at=None,
            preview=True,
        )
        return {
            **common,
            "status": "preview",
            "written": False,
            "path": None,
            "absolute_path": None,
            "sha256": None,
            "preview": preview,
            "message": (
                "预览模式：未写入任何文件。确认草稿内容后以 confirm=true 再次调用。"
                "该草稿必须由审核人复核签署，不构成自动合规判定。"
            ),
        }

    stamp = evidence.utc_timestamp()
    markdown = evidence.build_draft(
        project,
        dhf_result,
        trace_result,
        quality_result,
        sop_hits,
        generated_at=stamp,
        preview=False,
    )
    path = evidence.write_draft(markdown, project_id, timestamp=stamp)
    return {
        **common,
        "status": "written",
        "written": True,
        "path": _display_path(path),
        "absolute_path": str(path.resolve()),
        "sha256": evidence.file_sha256(path),
        "preview": markdown,
        "message": (
            "草稿已写入文件，等待人工审核签署。"
            "它不是自动合规判定，也不能替代质量体系规定的审批记录。"
        ),
    }


@mcp.tool()
def get_audit_log(limit: int = 20) -> dict[str, Any]:
    """返回最近的审计日志记录（旧 -> 新），用于复核工具调用与结果哈希。"""
    return _audited(
        "get_audit_log",
        {"limit": limit},
        lambda: _audit_payload(limit),
    )


def _audit_payload(limit: int) -> dict[str, Any]:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = 20
    value = max(1, min(value, 200))
    records = audit.tail(value)
    return {
        "path": str(audit.audit_path()),
        "count": len(records),
        "records": records,
    }


# ---------------------------------------------------------------------------
# 资源
# ---------------------------------------------------------------------------
@mcp.resource(
    "qms://dhf/index",
    name="dhf_index",
    title="DHF 类别核查清单",
    description="全部项目的 DHF 必需类别清单，含已具备 / 不完整 / 缺失计数。",
    mime_type="text/markdown",
)
def dhf_index() -> str:
    projects = db.fetch_all("projects_list")
    lines = [
        "# DHF 类别核查清单（合成数据）",
        "",
        "必需类别（"
        + str(len(rules.REQUIRED_DHF_CATEGORIES))
        + "）："
        + "、".join(rules.REQUIRED_DHF_CATEGORIES),
        "",
        "| 项目 | 类别 | 状态 | 文档引用 |",
        "| --- | --- | --- | --- |",
    ]
    total = {"present": 0, "incomplete": 0, "missing": 0}
    for project in projects:
        result = rules.check_dhf_completeness(
            str(project["id"]),
            db.fetch_all("dhf_items_by_project", {"project_id": str(project["id"])}),
        )
        for item in result["items"]:
            total[item["status"]] += 1
            refs = "、".join(item["doc_refs"]) or "—"
            lines.append(
                f"| {project['id']} | {item['category']} | "
                f"{item['status_label']} | {refs} |"
            )
    lines.append("")
    lines.append(
        "汇总：已具备 {present}，不完整 {incomplete}，缺失 {missing}。".format(**total)
    )
    lines.append("")
    lines.append("> 数据为合成测试夹具；该清单只做规则核查，不替代 DHF 正式评审。")
    return "\n".join(lines)


@mcp.resource(
    "qms://trace/matrix/{project_id}",
    name="trace_matrix",
    title="需求追溯矩阵",
    description="指定项目的 需求 -> 设计 -> 测试 追溯矩阵（markdown）。",
    mime_type="text/markdown",
)
def trace_matrix(project_id: str) -> str:
    project = _require_project(project_id)
    requirements = db.fetch_all("requirements_by_project", {"project_id": project_id})
    designs = db.fetch_all("design_items_by_project", {"project_id": project_id})
    tests = db.fetch_all("test_records_by_project", {"project_id": project_id})
    design_ids = {str(row["id"]) for row in designs}
    test_ids = {str(row["id"]) for row in tests}

    lines = [
        f"# 需求追溯矩阵：{project['id']} {project['name']}（合成数据）",
        "",
        f"- 阶段：{project['phase']}",
        f"- 需求数：{len(requirements)}",
        "",
        "| 需求 | 来源文档 | 设计 | 测试 | 链路 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for requirement in requirements:
        has_design = bool(requirement["design_id"]) and str(requirement["design_id"]) in design_ids
        has_test = bool(requirement["test_id"]) and str(requirement["test_id"]) in test_ids
        if has_design and has_test:
            link = "完整"
        elif not has_design and not has_test:
            link = "缺设计与测试"
        elif not has_design:
            link = "缺设计"
        else:
            link = "缺测试"
        lines.append(
            "| {rid} | {doc} | {design} | {test} | {link} |".format(
                rid=requirement["id"],
                doc=requirement["source_doc"] or "—",
                design=requirement["design_id"] or "—",
                test=requirement["test_id"] or "—",
                link=link,
            )
        )

    requirements_by_id = {str(row["id"]) for row in requirements}
    orphan_designs = [
        str(row["id"])
        for row in designs
        if not row["requirement_id"] or str(row["requirement_id"]) not in requirements_by_id
    ]
    designs_by_id = {str(row["id"]): row for row in designs}
    orphan_tests = [
        str(row["id"])
        for row in tests
        if not row["design_id"]
        or str(row["design_id"]) not in designs_by_id
        or not designs_by_id[str(row["design_id"])]["requirement_id"]
        or str(designs_by_id[str(row["design_id"])]["requirement_id"]) not in requirements_by_id
    ]

    lines.append("")
    lines.append("孤儿设计项：" + ("、".join(orphan_designs) if orphan_designs else "无"))
    lines.append("")
    lines.append("无需求来源的测试：" + ("、".join(orphan_tests) if orphan_tests else "无"))
    lines.append("")
    lines.append("> 矩阵由规则引擎生成，数据为合成测试夹具。")
    return "\n".join(lines)


@mcp.resource(
    "qms://sop/{doc_id}",
    name="sop_detail",
    title="SOP 全文",
    description="按文档编号返回 SOP 全文与版本号。",
    mime_type="text/markdown",
)
def sop_detail(doc_id: str) -> str:
    sop = db.fetch_one("sop_by_id", {"doc_id": doc_id})
    if sop is None:
        raise ValueError(f"未知 SOP: {doc_id}")
    return (
        f"# {sop['title']}\n\n"
        f"- 文档编号：{sop['id']}\n"
        f"- 版本：{sop['version']}\n"
        f"- 数据性质：合成测试夹具\n\n"
        f"---\n\n{sop['body']}\n"
    )


# ---------------------------------------------------------------------------
# 提示词
# ---------------------------------------------------------------------------
@mcp.prompt(
    title="设计评审 Gate 检查清单",
    description="设计评审 gate 前，让评审人按固定顺序跑完只读检查并形成结论。",
)
def review_gate_checklist(project_id: str = "PRJ-1003") -> str:
    """设计评审 gate 前的检查提示词模板。"""
    return f"""你是医疗器械研发质量体系的评审助手，负责在项目 {project_id} 的设计评审 gate 前做只读核查。

请严格按顺序执行，不要臆造数据：

1. 调用 check_dhf_completeness("{project_id}")，确认 5 个必需 DHF 类别是否齐全；
   对 missing / incomplete 的类别，记录文档引用和缺口。
2. 调用 find_traceability_gaps("{project_id}")，列出缺设计、缺测试、孤儿设计项、
   无需求来源的测试，并检查未关闭缺陷是否挂在追溯不完整的需求上。
3. 调用 check_requirement_quality("{project_id}")，列出缺验收标准、缺验证方法、
   模糊措辞、不可测试的需求。
4. 对每个缺口，用 search_sop 检索对应 SOP（例如 "DHF 管理"、"风险管理"、
   "设计验证"、"变更控制"），记录文档编号和版本，作为整改依据。
5. 如需形成佐证草稿，调用 draft_compliance_evidence("{project_id}", confirm=False)
   先看预览；是否写入文件由人工决定，且草稿必须由审核人签署。

输出格式：
- 结论：通过 / 有条件通过 / 退回
- 阻断项（必须关闭才能过 gate）
- 非阻断项（可带条件放行）
- 每条结论必须引用工具返回的 requirement_id / design_id / test_id / doc_id。

注意：数据是合成测试夹具；你的结论是评审输入，不是自动合规判定。
"""


if __name__ == "__main__":
    # 默认 stdio 传输：MCP 客户端（Claude Desktop / Claude Code 等）通过管道拉起本进程。
    mcp.run()
