"""需求质量规则：缺验收标准、缺验证方法、模糊措辞、不可测试。"""

from __future__ import annotations

from qms_mcp import db, rules


def _quality(project_id: str):
    return rules.check_requirement_quality(
        project_id, db.fetch_all("requirements_by_project", {"project_id": project_id})
    )


def test_gap_project_quality_exact_counts():
    result = _quality("PRJ-1003")
    assert result["total_requirements"] == 8
    assert result["counts"] == {
        "missing_acceptance_criteria": 1,
        "missing_verification_method": 2,
        "vague_wording": 5,
        "not_testable": 2,
    }
    assert result["flagged_requirement_ids"] == [
        "R-3003",
        "R-3004",
        "R-3006",
        "R-3007",
        "R-3008",
    ]
    assert result["clean"] is False


def test_missing_acceptance_and_method_flags():
    result = _quality("PRJ-1003")
    by_id = {item["requirement_id"]: item for item in result["requirements"]}

    r3004_codes = [issue["code"] for issue in by_id["R-3004"]["issues"]]
    assert r3004_codes == [
        "missing_acceptance_criteria",
        "missing_verification_method",
        "vague_wording",
        "not_testable",
    ]

    r3006_codes = [issue["code"] for issue in by_id["R-3006"]["issues"]]
    assert r3006_codes == ["missing_verification_method", "vague_wording"]


def test_vague_wording_detects_configured_terms():
    result = _quality("PRJ-1003")
    by_id = {item["requirement_id"]: item for item in result["requirements"]}

    def vague_terms(requirement_id: str):
        for issue in by_id[requirement_id]["issues"]:
            if issue["code"] == "vague_wording":
                return issue["terms"]
        return []

    assert vague_terms("R-3003") == ["尽量"]
    assert vague_terms("R-3004") == ["满足要求"]
    assert vague_terms("R-3006") == ["适当", "等"]
    assert vague_terms("R-3007") == ["较快"]
    assert vague_terms("R-3008") == ["良好"]


def test_etc_is_not_flagged_inside_compound_words():
    # “等级”不是模糊措辞；只有列举收尾的“等”才命中。
    assert rules.detect_vague("系统应支持多种报警等级") == []
    assert rules.detect_vague("适配 ICU、急诊等环境") == ["等"]
    assert rules.detect_vague("设备应等待 5 秒") == []


def test_not_testable_rule():
    assert rules.is_measurable("待机功耗不大于 0.5 W") is True
    assert rules.is_measurable("良好") is False

    result = _quality("PRJ-1003")
    by_id = {item["requirement_id"]: item for item in result["requirements"]}
    assert any(
        issue["code"] == "not_testable" for issue in by_id["R-3008"]["issues"]
    )
    assert not any(
        issue["code"] == "not_testable" for issue in by_id["R-3003"]["issues"]
    )


def test_clean_project_has_no_quality_issues():
    result = _quality("PRJ-1001")
    assert result["clean"] is True
    assert result["requirements"] == []
    assert all(count == 0 for count in result["counts"].values())


def test_quality_output_order_is_stable():
    first = _quality("PRJ-1003")
    second = _quality("PRJ-1003")
    assert first == second
    ids = [item["requirement_id"] for item in first["requirements"]]
    assert ids == sorted(ids)
