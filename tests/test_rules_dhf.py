"""DHF 完整性规则。"""

from __future__ import annotations

from qms_mcp import db, rules


def _dhf(project_id: str):
    return rules.check_dhf_completeness(
        project_id, db.fetch_all("dhf_items_by_project", {"project_id": project_id})
    )


def test_required_dhf_categories_constant():
    assert rules.REQUIRED_DHF_CATEGORIES == (
        "需求规格",
        "风险管理",
        "验证报告",
        "设计评审记录",
        "变更记录",
    )


def test_complete_project_dhf_has_no_gaps():
    result = _dhf("PRJ-1001")
    assert result["complete"] is True
    assert result["counts"] == {
        "total": 5,
        "present": 5,
        "incomplete": 0,
        "missing": 0,
    }


def test_gap_project_dhf_exact_counts():
    result = _dhf("PRJ-1003")
    assert result["complete"] is False
    assert result["counts"] == {
        "total": 5,
        "present": 2,
        "incomplete": 2,
        "missing": 1,
    }


def test_gap_project_dhf_statuses_and_doc_refs():
    result = _dhf("PRJ-1003")
    by_category = {item["category"]: item for item in result["items"]}
    assert by_category["需求规格"]["status"] == "present"
    assert by_category["风险管理"]["status"] == "incomplete"
    assert by_category["风险管理"]["doc_refs"] == ["DHF-3002-风险管理"]
    assert by_category["验证报告"]["status"] == "present"
    assert by_category["设计评审记录"]["status"] == "incomplete"
    assert by_category["设计评审记录"]["doc_refs"] == ["DHF-3004-设计评审记录"]
    assert by_category["变更记录"]["status"] == "missing"
    assert by_category["变更记录"]["doc_refs"] == []


def test_dhf_unknown_categories_are_reported_not_counted():
    rows = db.fetch_all("dhf_items_by_project", {"project_id": "PRJ-1001"})
    rows.append(
        {
            "project_id": "PRJ-1001",
            "category": "临床评价",
            "doc_ref": "DHF-1006-临床评价",
            "present": 1,
        }
    )
    result = rules.check_dhf_completeness("PRJ-1001", rows)
    assert result["unknown_categories"] == ["临床评价"]
    assert result["counts"]["total"] == 5
    assert result["complete"] is True


def test_dhf_item_order_is_stable():
    result = _dhf("PRJ-1003")
    assert [item["category"] for item in result["items"]] == list(
        rules.REQUIRED_DHF_CATEGORIES
    )
