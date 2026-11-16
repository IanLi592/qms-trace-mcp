"""合规佐证草稿：预览不落盘、确认才写入、内容可复现、需人工签署。"""

from __future__ import annotations

import re
from pathlib import Path

from qms_mcp import db, evidence, rules, server


def test_preview_writes_nothing(tmp_path: Path, monkeypatch):
    output = tmp_path / "preview-output"
    monkeypatch.setenv("QMS_OUTPUT_DIR", str(output))

    result = server.draft_compliance_evidence("PRJ-1003", confirm=False)

    assert result["status"] == "preview"
    assert result["written"] is False
    assert result["path"] is None
    assert result["absolute_path"] is None
    assert result["sha256"] is None
    assert "未写入任何文件" in result["message"]
    assert not output.exists() or not any(output.iterdir())


def test_confirm_writes_file(tmp_path: Path, monkeypatch):
    output = tmp_path / "confirmed-output"
    monkeypatch.setenv("QMS_OUTPUT_DIR", str(output))

    result = server.draft_compliance_evidence("PRJ-1003", confirm=True)

    assert result["status"] == "written"
    assert result["written"] is True
    path = Path(result["absolute_path"])
    assert path.is_file()
    assert path.parent == output.resolve() or path.parent.resolve() == output.resolve()
    assert re.fullmatch(
        r"evidence_PRJ-1003_\d{8}T\d{6}Z\.md", path.name
    ), path.name
    assert result["sha256"] == evidence.file_sha256(path)


def test_evidence_contains_synthetic_notice_and_signoff():
    result = server.draft_compliance_evidence("PRJ-1003", confirm=False)
    preview = result["preview"]

    assert "合成数据" in preview
    assert "合成测试夹具" in preview
    assert "PRJ-1003" in preview
    assert "审核人" in preview
    assert "签署" in preview
    assert "不构成自动合规判定" in preview
    assert result["synthetic_data"] is True


def test_preview_is_byte_identical_across_calls():
    first = server.draft_compliance_evidence("PRJ-1003", confirm=False)
    second = server.draft_compliance_evidence("PRJ-1003", confirm=False)
    assert first["preview"] == second["preview"]


def test_build_draft_with_fixed_timestamp_is_deterministic():
    project, dhf_result, trace_result, quality_result = server._collect_checks("PRJ-1003")
    sop_hits = rules.search_sops(
        db.fetch_all("sops_all"), server.EVIDENCE_SOP_QUERY, 5
    )
    first = evidence.build_draft(
        project,
        dhf_result,
        trace_result,
        quality_result,
        sop_hits,
        generated_at="20260101T000000Z",
        preview=False,
    )
    second = evidence.build_draft(
        project,
        dhf_result,
        trace_result,
        quality_result,
        sop_hits,
        generated_at="20260101T000000Z",
        preview=False,
    )
    assert first == second
    assert "20260101T000000Z" in first


def test_write_draft_fixed_timestamp_path_and_content(tmp_path: Path):
    markdown = "# 草稿\n\n合成测试夹具\n"
    first = evidence.write_draft(
        markdown, "PRJ-1003", timestamp="20260101T000000Z", directory=tmp_path
    )
    assert first.name == "evidence_PRJ-1003_20260101T000000Z.md"
    assert first.read_text(encoding="utf-8") == markdown

    # 同一时间戳再次写入不覆盖旧文件。
    second = evidence.write_draft(
        markdown, "PRJ-1003", timestamp="20260101T000000Z", directory=tmp_path
    )
    assert second.name == "evidence_PRJ-1003_20260101T000000Z_1.md"
    assert first.read_text(encoding="utf-8") == markdown


def test_evidence_mentions_dhf_trace_quality_and_defects():
    preview = server.draft_compliance_evidence("PRJ-1003", confirm=False)["preview"]
    assert "DHF（设计历史文档）完整性" in preview
    assert "需求 -> 设计 -> 测试 追溯" in preview
    assert "需求质量" in preview
    assert "缺陷影响面" in preview
    assert "SOP-QMS-002" in preview
