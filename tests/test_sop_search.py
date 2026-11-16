"""SOP 关键词检索（BM25-lite）。"""

from __future__ import annotations

import pytest

from qms_mcp import db, rules, server


def _sops():
    return db.fetch_all("sops_all")


def test_dhf_query_ranks_dhf_sop_first():
    hits = rules.search_sops(_sops(), "DHF")
    assert hits[0]["doc_id"] == "SOP-QMS-002"
    assert "DHF" in hits[0]["snippet"]


def test_risk_query_ranks_risk_sop_first():
    hits = rules.search_sops(_sops(), "风险")
    assert hits[0]["doc_id"] == "SOP-QMS-003"


def test_change_impact_query_ranks_change_sop_first():
    hits = rules.search_sops(_sops(), "变更影响分析")
    assert hits[0]["doc_id"] == "SOP-QMS-005"


def test_no_match_returns_empty_list():
    assert rules.search_sops(_sops(), "xyzzy 不存在的术语") == []


def test_hits_are_citable():
    hits = rules.search_sops(_sops(), "验证", top_k=3)
    assert hits
    for hit in hits:
        assert hit["doc_id"].startswith("SOP-QMS-")
        assert hit["title"]
        assert hit["version"]
        assert hit["snippet"]
        assert isinstance(hit["score"], float)


def test_top_k_is_respected_and_clamped():
    assert len(rules.search_sops(_sops(), "设计", top_k=2)) == 2
    assert len(rules.search_sops(_sops(), "设计", top_k=0)) == 1
    assert len(rules.search_sops(_sops(), "设计", top_k=99)) == len(_sops())


def test_scores_are_non_increasing():
    hits = rules.search_sops(_sops(), "设计验证", top_k=6)
    scores = [hit["score"] for hit in hits]
    assert scores == sorted(scores, reverse=True)


def test_empty_query_rejected():
    with pytest.raises(ValueError):
        rules.search_sops(_sops(), "")
    with pytest.raises(ValueError):
        rules.search_sops(_sops(), "   ")


def test_search_sop_tool_reports_effective_top_k():
    result = server.search_sop("DHF", top_k=99)
    assert result["top_k"] == 20
    assert result["hit_count"] == len(result["hits"])
    assert result["hits"][0]["doc_id"] == "SOP-QMS-002"
