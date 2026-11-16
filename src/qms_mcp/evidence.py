"""合规佐证草稿生成。

设计要点：

- 输出是**给人复核的草稿**，不是自动合规判定，也不是自动归档。
- 预览模式（默认）只返回 markdown，不碰文件系统。
- 写入模式必须显式 ``confirm``，文件名带 UTC 时间戳，内容含审核人签署区。
- 内容全部来自确定性规则结果，可重复生成、可 diff、可归档。
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]

_FILENAME_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")
_WS_RE = re.compile(r"\s+")


def output_dir() -> Path:
    """返回草稿输出目录；可用 QMS_OUTPUT_DIR 覆盖（测试用）。"""
    raw = os.environ.get("QMS_OUTPUT_DIR")
    return Path(raw).expanduser() if raw else ROOT / "output"


def _cell(value: Any) -> str:
    """转义 markdown 表格单元。"""
    text = _WS_RE.sub(" ", str(value if value is not None else "")).strip()
    return text.replace("|", "\\|")


def _status_label(status: str) -> str:
    return {"present": "已具备", "incomplete": "不完整", "missing": "缺失"}.get(
        status, status
    )


def _list_or_none(items: Sequence[Any], formatter) -> list[str]:
    if not items:
        return ["- 无"]
    return [formatter(item) for item in items]


def build_draft(
    project: Mapping[str, Any],
    dhf_result: Mapping[str, Any],
    trace_result: Mapping[str, Any],
    quality_result: Mapping[str, Any],
    sop_hits: Sequence[Mapping[str, Any]],
    *,
    generated_at: str | None = None,
    preview: bool = True,
) -> str:
    """生成合规佐证草稿 markdown。

    ``generated_at`` 为 None 时不写入时间，保证预览内容可逐字节复现。
    """
    project_id = str(project.get("id"))
    project_name = str(project.get("name") or "")
    phase = str(project.get("phase") or "")

    if preview:
        status_line = "预览（未写入文件）"
        time_line = "预览模式未写入"
    else:
        status_line = "草稿已生成，待人工审核签署"
        time_line = generated_at or "未提供"

    lines: list[str] = []
    lines.append("# 合规佐证草稿（合成数据）")
    lines.append("")
    lines.append(f"> 状态：{status_line}")
    lines.append(f"> 项目：{project_id} {project_name}（阶段：{phase}）")
    lines.append("> 生成工具：qms-trace-mcp（确定性规则引擎，全程无 LLM 调用）")
    lines.append(f"> 生成时间（UTC）：{time_line}")
    lines.append("> 数据性质：全部为合成测试夹具，不含任何真实患者、产品或公司数据。")
    lines.append("")

    # ---- 1. 审核结论 -----------------------------------------------------
    lines.append("## 1. 审核结论（由审核人填写）")
    lines.append("")
    lines.append("| 字段 | 内容 |")
    lines.append("| --- | --- |")
    lines.append("| 审核人 |  |")
    lines.append("| 审核日期 |  |")
    lines.append("| 结论 | □ 通过　□ 有条件通过　□ 退回 |")
    lines.append("| 签署 |  |")
    lines.append("")
    lines.append("> 本区间必须由质量体系授权人员手工填写并签署，工具不会代填。")
    lines.append("")

    # ---- 2. DHF ---------------------------------------------------------
    dhf_counts = dhf_result.get("counts", {})
    lines.append("## 2. DHF（设计历史文档）完整性")
    lines.append("")
    lines.append(
        "必需类别 {total} 项：已具备 {present}，不完整 {incomplete}，缺失 {missing}；"
        "总体结论：{verdict}。".format(
            total=dhf_counts.get("total", 0),
            present=dhf_counts.get("present", 0),
            incomplete=dhf_counts.get("incomplete", 0),
            missing=dhf_counts.get("missing", 0),
            verdict="完整" if dhf_result.get("complete") else "不完整",
        )
    )
    lines.append("")
    lines.append("| 类别 | 状态 | 文档引用 |")
    lines.append("| --- | --- | --- |")
    for item in dhf_result.get("items", []):
        refs = "、".join(item.get("doc_refs") or []) or "—"
        lines.append(
            f"| {_cell(item.get('category'))} | {_status_label(str(item.get('status')))} | {_cell(refs)} |"
        )
    lines.append("")

    # ---- 3. 追溯 --------------------------------------------------------
    trace_counts = trace_result.get("counts", {})
    lines.append("## 3. 需求 -> 设计 -> 测试 追溯")
    lines.append("")
    lines.append(
        "需求总数 {total}；缺设计 {md}，缺测试 {mt}，孤儿设计项 {od}，"
        "无需求来源的测试 {tw}。".format(
            total=trace_result.get("total_requirements", 0),
            md=trace_counts.get("missing_design", 0),
            mt=trace_counts.get("missing_test", 0),
            od=trace_counts.get("orphan_design_items", 0),
            tw=trace_counts.get("tests_without_requirement", 0),
        )
    )
    lines.append("")
    lines.append("### 3.1 需求缺设计链接")
    lines.extend(
        _list_or_none(
            trace_result.get("requirements_missing_design", []),
            lambda item: f"- {item['requirement_id']}（原因：{item['reason']}）",
        )
    )
    lines.append("")
    lines.append("### 3.2 需求缺测试链接")
    lines.extend(
        _list_or_none(
            trace_result.get("requirements_missing_test", []),
            lambda item: f"- {item['requirement_id']}（原因：{item['reason']}）",
        )
    )
    lines.append("")
    lines.append("### 3.3 孤儿设计项 / 无需求测试")
    lines.extend(
        _list_or_none(
            trace_result.get("orphan_design_items", []),
            lambda item: (
                f"- 设计项 {item['design_id']} 未关联有效需求"
                f"（requirement_id={item.get('requirement_id')}，原因：{item['reason']}）"
            ),
        )
    )
    lines.extend(
        _list_or_none(
            trace_result.get("tests_without_requirement", []),
            lambda item: (
                f"- 测试 {item['test_id']} 无法回溯到需求"
                f"（design_id={item.get('design_id')}，原因：{item['reason']}）"
            ),
        )
    )
    lines.append("")

    # ---- 4. 需求质量 ----------------------------------------------------
    quality_counts = quality_result.get("counts", {})
    lines.append("## 4. 需求质量")
    lines.append("")
    lines.append("| 问题类型 | 涉及需求数 |")
    lines.append("| --- | --- |")
    lines.append(f"| 缺验收标准 | {quality_counts.get('missing_acceptance_criteria', 0)} |")
    lines.append(f"| 缺验证方法 | {quality_counts.get('missing_verification_method', 0)} |")
    lines.append(f"| 模糊措辞 | {quality_counts.get('vague_wording', 0)} |")
    lines.append(f"| 不可测试 | {quality_counts.get('not_testable', 0)} |")
    lines.append("")
    if quality_result.get("requirements"):
        for item in quality_result["requirements"]:
            details = "；".join(issue.get("detail", "") for issue in item.get("issues", []))
            lines.append(f"- {item['requirement_id']}：{_cell(details)}")
    else:
        lines.append("- 未发现需求质量问题。")
    lines.append("")

    # ---- 5. 缺陷影响 ----------------------------------------------------
    lines.append("## 5. 缺陷影响面")
    lines.append("")
    lines.append(
        "未关闭缺陷 {open_n} 个；其中 {incomplete_n} 个挂在追溯不完整的需求上。".format(
            open_n=trace_counts.get("open_defects", 0),
            incomplete_n=trace_counts.get("defects_on_incomplete_trace", 0),
        )
    )
    lines.append("")
    lines.append("| 缺陷 | 严重度 | 状态 | 关联需求 | 下游链路 |")
    lines.append("| --- | --- | --- | --- | --- |")
    impact = trace_result.get("defect_impact", [])
    if impact:
        for item in impact:
            lines.append(
                "| {bug} | {severity} | {status} | {requirement} | {downstream} |".format(
                    bug=_cell(item.get("defect_id")),
                    severity=_cell(item.get("severity")),
                    status=_cell(item.get("status")),
                    requirement=_cell(item.get("requirement_id") or "—"),
                    downstream=_cell(item.get("downstream")),
                )
            )
    else:
        lines.append("| — | — | — | — | 无缺陷记录 |")
    lines.append("")

    # ---- 6. SOP 依据 ----------------------------------------------------
    lines.append("## 6. 引用的 SOP（候选依据，审核人需确认版本适用性）")
    lines.append("")
    if sop_hits:
        lines.append("| 文档编号 | 标题 | 版本 | 命中片段 |")
        lines.append("| --- | --- | --- | --- |")
        for hit in sop_hits:
            lines.append(
                "| {doc} | {title} | {version} | {snippet} |".format(
                    doc=_cell(hit.get("doc_id")),
                    title=_cell(hit.get("title")),
                    version=_cell(hit.get("version")),
                    snippet=_cell(hit.get("snippet")),
                )
            )
    else:
        lines.append("- 未检索到匹配的 SOP，请人工补充依据。")
    lines.append("")

    # ---- 7. 声明 --------------------------------------------------------
    lines.append("## 7. 声明")
    lines.append("")
    lines.append(
        "本文件由 qms-trace-mcp 基于合成测试夹具自动生成，仅作为人工审核的"
        "合规佐证草稿，不构成自动合规判定，也不能替代质量体系规定的评审、"
        "批准与归档记录。所有结论必须经授权审核人复核并签署后方可引用。"
    )
    lines.append("")
    return "\n".join(lines)


def safe_project_token(project_id: str) -> str:
    """把项目 ID 变成安全的文件名片段。"""
    token = _FILENAME_SAFE_RE.sub("_", str(project_id)).strip("._-")
    return token or "project"


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_draft(
    markdown: str,
    project_id: str,
    *,
    timestamp: str | None = None,
    directory: Path | None = None,
) -> Path:
    """把草稿写入 ``output/evidence_<project>_<timestamp>.md``，返回绝对路径。"""
    directory = (directory or output_dir()).resolve()
    directory.mkdir(parents=True, exist_ok=True)

    token = safe_project_token(project_id)
    stamp = timestamp or utc_timestamp()
    path = directory / f"evidence_{token}_{stamp}.md"

    # 同一秒内重复写入时避免覆盖已有草稿。
    counter = 1
    while path.exists():
        path = directory / f"evidence_{token}_{stamp}_{counter}.md"
        counter += 1

    path.write_text(markdown, encoding="utf-8")
    return path


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
