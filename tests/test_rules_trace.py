"""需求 -> 设计 -> 测试 追溯规则与缺陷影响面。"""

from __future__ import annotations

from qms_mcp import db, rules


def _trace(project_id: str):
    params = {"project_id": project_id}
    return rules.find_traceability_gaps(
        project_id,
        db.fetch_all("requirements_by_project", params),
        db.fetch_all("design_items_by_project", params),
        db.fetch_all("test_records_by_project", params),
        db.fetch_all("defects_by_project", params),
    )


def test_gap_project_trace_exact_counts():
    result = _trace("PRJ-1003")
    assert result["counts"] == {
        "missing_design": 3,
        "missing_test": 3,
        "orphan_design_items": 2,
        "tests_without_requirement": 3,
        "open_defects": 3,
        "defects_on_incomplete_trace": 1,
    }
    assert result["complete"] is False


def test_gap_project_missing_design_requirements():
    result = _trace("PRJ-1003")
    assert [item["requirement_id"] for item in result["requirements_missing_design"]] == [
        "R-3002",
        "R-3004",
        "R-3006",
    ]
    assert all(
        item["reason"] == "design_id_missing"
        for item in result["requirements_missing_design"]
    )


def test_gap_project_missing_test_requirements():
    result = _trace("PRJ-1003")
    assert [item["requirement_id"] for item in result["requirements_missing_test"]] == [
        "R-3002",
        "R-3003",
        "R-3006",
    ]
    assert result["requirements_with_incomplete_trace"] == [
        "R-3002",
        "R-3003",
        "R-3004",
        "R-3006",
    ]


def test_orphan_design_items_exact():
    result = _trace("PRJ-1003")
    assert result["orphan_design_items"] == [
        {
            "design_id": "D-3006",
            "requirement_id": None,
            "reason": "requirement_id_missing",
        },
        {
            "design_id": "D-3007",
            "requirement_id": "R-9999",
            "reason": "requirement_not_found",
        },
    ]


def test_tests_without_requirement_reasons():
    result = _trace("PRJ-1003")
    assert result["tests_without_requirement"] == [
        {"test_id": "T-3002", "design_id": None, "reason": "no_design_link"},
        {
            "test_id": "T-3006",
            "design_id": "D-3006",
            "reason": "design_has_no_requirement",
        },
        {"test_id": "T-3007", "design_id": None, "reason": "no_design_link"},
    ]


def test_complete_project_has_no_trace_gaps():
    result = _trace("PRJ-1001")
    assert result["complete"] is True
    assert result["requirements_missing_design"] == []
    assert result["requirements_missing_test"] == []
    assert result["orphan_design_items"] == []
    assert result["tests_without_requirement"] == []


def test_traceability_defect_impact_section():
    result = _trace("PRJ-1003")
    impact = {item["defect_id"]: item for item in result["defect_impact"]}

    assert impact["BUG-3001"]["requirement_trace_complete"] is True
    assert impact["BUG-3003"]["requirement_trace_complete"] is False
    assert impact["BUG-3003"]["downstream"] == "缺设计"
    assert impact["BUG-3002"]["status"] == "关闭"
    assert impact["BUG-3004"]["requirement_id"] is None
    assert impact["BUG-3004"]["requirement_trace_complete"] is None

    assert result["counts"]["open_defects"] == 3
    assert result["counts"]["defects_on_incomplete_trace"] == 1


def test_traceability_defect_impact_sorted_by_severity():
    result = _trace("PRJ-1003")
    assert [item["defect_id"] for item in result["defect_impact"]] == [
        "BUG-3003",  # 致命
        "BUG-3001",  # 严重
        "BUG-3002",  # 一般
        "BUG-3004",  # 轻微
    ]
