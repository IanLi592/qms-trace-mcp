"""合成夹具本身的不变量。"""

from __future__ import annotations

from qms_mcp import db


def test_database_has_three_projects():
    projects = db.fetch_all("projects_list")
    assert len(projects) == 3
    assert {row["phase"] for row in projects} == {"设计转移", "设计验证", "概念"}


def test_meta_marks_dataset_as_synthetic():
    meta = {row["key"]: row["value"] for row in db.fetch_all("meta_all")}
    assert meta["dataset"] == "synthetic-fixtures-v1"
    assert "合成测试夹具" in meta["warning"]
    assert meta["gap_sample"] == "PRJ-1003"


def test_gap_project_has_requirements_designs_tests_and_defects():
    params = {"project_id": "PRJ-1003"}
    assert len(db.fetch_all("requirements_by_project", params)) == 8
    assert len(db.fetch_all("design_items_by_project", params)) == 7
    assert len(db.fetch_all("test_records_by_project", params)) == 7
    assert len(db.fetch_all("defects_by_project", params)) == 4


def test_sops_have_citable_identity_fields():
    sops = db.fetch_all("sops_all")
    assert len(sops) == 6
    for sop in sops:
        assert sop["id"].startswith("SOP-QMS-")
        assert sop["title"]
        assert sop["version"]
        assert "合成测试数据" in sop["body"]
