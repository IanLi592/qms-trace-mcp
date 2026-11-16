"""确定性核查规则（纯函数，不碰数据库）。

所有输入都是普通 dict / list，所有输出都使用稳定排序；
同一份输入永远得到同一份输出，方便测试断言与审计复现。
"""

from __future__ import annotations

import math
import re
from typing import Any, Iterable, Mapping, Sequence

# DHF（设计历史文档）必须覆盖的类别。缺失任何一类都算不完整。
REQUIRED_DHF_CATEGORIES: tuple[str, ...] = (
    "需求规格",
    "风险管理",
    "验证报告",
    "设计评审记录",
    "变更记录",
)

# 需求文本里常见的模糊措辞。这里只放少量高置信词，避免误报太多。
VAGUE_TERMS: tuple[str, ...] = (
    "适当",
    "尽量",
    "合理",
    "较快",
    "良好",
    "满足要求",
)

# “等”单独处理：它在“等级 / 等待 / 等于”里是正常词，不是模糊措辞。
# 只有作为列举收尾时才判定为模糊。
VAGUE_ETC_RE = re.compile(r"等(?![级待同价式候于])")

# 可测量判据：数字或比较符。没有这些就认为验收标准不可验证。
MEASURABLE_RE = re.compile(r"\d|≥|≤|>|<|=|±|%")

VERIFICATION_METHODS: tuple[str, ...] = ("测试", "检查", "分析", "演示")

SEVERITY_ORDER: dict[str, int] = {
    "致命": 0,
    "严重": 1,
    "一般": 2,
    "轻微": 3,
}

_STATUS_LABELS = {
    "present": "已具备",
    "incomplete": "不完整",
    "missing": "缺失",
}


def _blank_to_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _sort_key(value: Any) -> str:
    return str(value)


# ---------------------------------------------------------------------------
# 1. DHF 完整性
# ---------------------------------------------------------------------------
def check_dhf_completeness(
    project_id: str, dhf_rows: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    """按 ``REQUIRED_DHF_CATEGORIES`` 逐项核查 DHF 覆盖情况。

    - ``missing``：表里没有任何该类别记录
    - ``incomplete``：有记录，但 ``present`` 全部为 0
    - ``present``：至少一条 ``present = 1``
    """
    by_category: dict[str, list[Mapping[str, Any]]] = {}
    for row in dhf_rows:
        category = str(row.get("category") or "")
        by_category.setdefault(category, []).append(row)

    items: list[dict[str, Any]] = []
    counts = {"total": len(REQUIRED_DHF_CATEGORIES), "present": 0, "incomplete": 0, "missing": 0}

    for category in REQUIRED_DHF_CATEGORIES:
        rows = by_category.get(category, [])
        refs = sorted(
            {str(row.get("doc_ref")) for row in rows if _blank_to_none(row.get("doc_ref"))}
        )
        present_count = sum(1 for row in rows if _as_int(row.get("present")) == 1)

        if not rows:
            status = "missing"
        elif present_count == 0:
            status = "incomplete"
        else:
            status = "present"

        counts[status] += 1
        items.append(
            {
                "category": category,
                "status": status,
                "status_label": _STATUS_LABELS[status],
                "doc_refs": refs,
                "declared_count": len(rows),
                "present_count": present_count,
            }
        )

    unknown = sorted(set(by_category) - set(REQUIRED_DHF_CATEGORIES))
    return {
        "project_id": project_id,
        "required_categories": list(REQUIRED_DHF_CATEGORIES),
        "items": items,
        "counts": counts,
        "unknown_categories": unknown,
        "complete": counts["incomplete"] == 0 and counts["missing"] == 0,
    }


# ---------------------------------------------------------------------------
# 2. 需求质量
# ---------------------------------------------------------------------------
def detect_vague(text: str | None) -> list[str]:
    """返回命中的模糊措辞，按首次出现位置排序。"""
    if not text:
        return []
    matches: list[tuple[int, str]] = []
    for term in VAGUE_TERMS:
        index = text.find(term)
        if index >= 0:
            matches.append((index, term))
    etc = VAGUE_ETC_RE.search(text)
    if etc:
        matches.append((etc.start(), "等"))

    earliest: dict[str, int] = {}
    for index, term in matches:
        earliest[term] = min(index, earliest.get(term, index))
    return [term for term, _ in sorted(earliest.items(), key=lambda item: (item[1], item[0]))]


def is_measurable(criteria: str | None) -> bool:
    """验收标准里是否有至少一个数字或比较符。"""
    if not criteria:
        return False
    return bool(MEASURABLE_RE.search(criteria))


def check_requirement_quality(
    project_id: str, requirements: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    """逐条检查需求是否具备可验证的质量属性。"""
    requirements = list(requirements)
    flagged: list[dict[str, Any]] = []
    counts = {
        "missing_acceptance_criteria": 0,
        "missing_verification_method": 0,
        "vague_wording": 0,
        "not_testable": 0,
    }

    for requirement in sorted(requirements, key=lambda row: _sort_key(row.get("id"))):
        requirement_id = str(requirement.get("id"))
        criteria = requirement.get("acceptance_criteria")
        method = _blank_to_none(requirement.get("verification_method"))
        issues: list[dict[str, Any]] = []

        if not _blank_to_none(criteria):
            issues.append(
                {
                    "code": "missing_acceptance_criteria",
                    "detail": "未填写 acceptance_criteria",
                }
            )

        if method is None:
            issues.append(
                {
                    "code": "missing_verification_method",
                    "detail": "未填写 verification_method",
                }
            )

        vague_terms = detect_vague(
            " ".join(
                part
                for part in (str(requirement.get("text") or ""), str(criteria or ""))
                if part
            )
        )
        if vague_terms:
            issues.append(
                {
                    "code": "vague_wording",
                    "detail": "模糊措辞: " + ", ".join(vague_terms),
                    "terms": vague_terms,
                }
            )

        if not _blank_to_none(criteria):
            issues.append(
                {
                    "code": "not_testable",
                    "detail": "缺少验收标准，无法设计测试",
                }
            )
        elif not is_measurable(str(criteria)):
            issues.append(
                {
                    "code": "not_testable",
                    "detail": "验收标准不含数字或比较符，无法客观判定",
                }
            )

        if issues:
            flagged.append({"requirement_id": requirement_id, "issues": issues})
            for issue in issues:
                counts[issue["code"]] += 1

    return {
        "project_id": project_id,
        "total_requirements": len(requirements),
        "requirements": flagged,
        "flagged_requirement_ids": [item["requirement_id"] for item in flagged],
        "counts": counts,
        "clean": not flagged,
    }


# ---------------------------------------------------------------------------
# 3. 追溯链路
# ---------------------------------------------------------------------------
def _link_status(link: Any, target_by_id: Mapping[str, Any], missing_code: str) -> str | None:
    link_id = _blank_to_none(link)
    if link_id is None:
        return missing_code
    if link_id not in target_by_id:
        return "not_found"
    return None


def _downstream_label(has_design: bool, has_test: bool) -> str:
    if has_design and has_test:
        return "完整"
    if not has_design and not has_test:
        return "缺设计与测试"
    if not has_design:
        return "缺设计"
    return "缺测试"


def find_traceability_gaps(
    project_id: str,
    requirements: Iterable[Mapping[str, Any]],
    design_items: Iterable[Mapping[str, Any]],
    test_records: Iterable[Mapping[str, Any]],
    defects: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """检查需求 -> 设计 -> 测试的链路，并给出缺陷影响面。

    缺口判定同时看两侧：

    - 需求侧：``design_id`` / ``test_id`` 为空或指向不存在的记录
    - 设计侧：设计项没有关联需求，或关联到不存在的需求
    - 测试侧：测试记录没有设计链接，或其设计项没有关联需求
    """
    requirements = list(requirements)
    design_items = list(design_items)
    test_records = list(test_records)
    defects = list(defects)

    requirements_by_id = {str(row.get("id")): row for row in requirements}
    designs_by_id = {str(row.get("id")): row for row in design_items}
    tests_by_id = {str(row.get("id")): row for row in test_records}

    missing_design: list[dict[str, Any]] = []
    missing_test: list[dict[str, Any]] = []
    incomplete_ids: list[str] = []

    for requirement in sorted(requirements, key=lambda row: _sort_key(row.get("id"))):
        requirement_id = str(requirement.get("id"))

        design_reason = _link_status(
            requirement.get("design_id"), designs_by_id, "design_id_missing"
        )
        test_reason = _link_status(requirement.get("test_id"), tests_by_id, "test_id_missing")

        if design_reason:
            missing_design.append(
                {
                    "requirement_id": requirement_id,
                    "design_id": _blank_to_none(requirement.get("design_id")),
                    "reason": design_reason,
                }
            )
        if test_reason:
            missing_test.append(
                {
                    "requirement_id": requirement_id,
                    "test_id": _blank_to_none(requirement.get("test_id")),
                    "reason": test_reason,
                }
            )
        if design_reason or test_reason:
            incomplete_ids.append(requirement_id)

    orphan_designs: list[dict[str, Any]] = []
    for design in sorted(design_items, key=lambda row: _sort_key(row.get("id"))):
        design_id = str(design.get("id"))
        requirement_id = _blank_to_none(design.get("requirement_id"))
        if requirement_id is None:
            orphan_designs.append(
                {
                    "design_id": design_id,
                    "requirement_id": None,
                    "reason": "requirement_id_missing",
                }
            )
        elif requirement_id not in requirements_by_id:
            orphan_designs.append(
                {
                    "design_id": design_id,
                    "requirement_id": requirement_id,
                    "reason": "requirement_not_found",
                }
            )

    tests_without_requirement: list[dict[str, Any]] = []
    for test in sorted(test_records, key=lambda row: _sort_key(row.get("id"))):
        test_id = str(test.get("id"))
        design_id = _blank_to_none(test.get("design_id"))
        if design_id is None:
            reason = "no_design_link"
        elif design_id not in designs_by_id:
            reason = "design_not_found"
        else:
            requirement_id = _blank_to_none(designs_by_id[design_id].get("requirement_id"))
            if requirement_id is None:
                reason = "design_has_no_requirement"
            elif requirement_id not in requirements_by_id:
                reason = "requirement_not_found"
            else:
                continue
        tests_without_requirement.append(
            {"test_id": test_id, "design_id": design_id, "reason": reason}
        )

    # 缺陷影响面：把每个缺陷挂回需求，并标出下游链路是否齐全。
    impact: list[dict[str, Any]] = []
    for defect in defects:
        requirement_id = _blank_to_none(defect.get("requirement_id"))
        if requirement_id is None:
            trace_complete: bool | None = None
            downstream = "无关联需求"
        else:
            requirement = requirements_by_id.get(requirement_id)
            if requirement is None:
                trace_complete = None
                downstream = "需求不存在"
            else:
                has_design = _link_status(
                    requirement.get("design_id"), designs_by_id, "design_id_missing"
                ) is None
                has_test = _link_status(
                    requirement.get("test_id"), tests_by_id, "test_id_missing"
                ) is None
                trace_complete = has_design and has_test
                downstream = _downstream_label(has_design, has_test)
        impact.append(
            {
                "defect_id": str(defect.get("id")),
                "severity": str(defect.get("severity") or ""),
                "status": str(defect.get("status") or ""),
                "requirement_id": requirement_id,
                "requirement_trace_complete": trace_complete,
                "downstream": downstream,
            }
        )

    impact.sort(
        key=lambda item: (
            SEVERITY_ORDER.get(item["severity"], 99),
            item["defect_id"],
        )
    )

    open_defects = sum(1 for item in impact if item["status"] == "打开")
    defects_on_incomplete_trace = sum(
        1
        for item in impact
        if item["status"] == "打开"
        and item["requirement_id"] is not None
        and item["requirement_trace_complete"] is False
    )

    counts = {
        "missing_design": len(missing_design),
        "missing_test": len(missing_test),
        "orphan_design_items": len(orphan_designs),
        "tests_without_requirement": len(tests_without_requirement),
        "open_defects": open_defects,
        "defects_on_incomplete_trace": defects_on_incomplete_trace,
    }

    return {
        "project_id": project_id,
        "total_requirements": len(requirements),
        "requirements_missing_design": missing_design,
        "requirements_missing_test": missing_test,
        "requirements_with_incomplete_trace": incomplete_ids,
        "orphan_design_items": orphan_designs,
        "tests_without_requirement": tests_without_requirement,
        "defect_impact": impact,
        "counts": counts,
        "complete": all(
            counts[key] == 0
            for key in (
                "missing_design",
                "missing_test",
                "orphan_design_items",
                "tests_without_requirement",
            )
        ),
    }


# ---------------------------------------------------------------------------
# 4. SOP 检索（BM25-lite，纯关键词，无向量、无 LLM）
# ---------------------------------------------------------------------------
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9._+-]*|[一-鿿]+")
_CJK_RE = re.compile(r"^[一-鿿]+$")
_WS_RE = re.compile(r"\s+")


def _tokenize(query: str) -> list[str]:
    """拆出检索词；中文长词额外拆成二字组，弥补没有分词器的问题。"""
    raw = _WORD_RE.findall(query.lower())
    tokens: list[str] = []
    seen: set[str] = set()
    for token in raw:
        variants = [token]
        if _CJK_RE.match(token) and len(token) > 2:
            variants.extend(token[index : index + 2] for index in range(len(token) - 1))
        for variant in variants:
            if variant and variant not in seen:
                seen.add(variant)
                tokens.append(variant)
    return tokens


def _make_snippet(body: str, tokens: Sequence[str], width: int = 60) -> str:
    lower = body.lower()
    for token in tokens:
        index = lower.find(token)
        if index >= 0:
            start = max(0, index - width // 2)
            end = min(len(body), index + len(token) + width)
            piece = _WS_RE.sub(" ", body[start:end]).strip()
            prefix = "…" if start > 0 else ""
            suffix = "…" if end < len(body) else ""
            return f"{prefix}{piece}{suffix}"
    return _WS_RE.sub(" ", body[:120]).strip()


def clamp_top_k(top_k: Any) -> int:
    """把 top_k 收敛到 1..20，非法值回落到 5。"""
    try:
        value = int(top_k)
    except (TypeError, ValueError):
        return 5
    return max(1, min(value, 20))


def search_sops(
    sops: Iterable[Mapping[str, Any]], query: str, top_k: int = 5
) -> list[dict[str, Any]]:
    """对 SOP 做 BM25-lite 排序，返回可引用的命中片段。"""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query 不能为空")
    query = query.strip()
    if len(query) > 200:
        raise ValueError("query 过长（上限 200 字符）")

    top_k_int = clamp_top_k(top_k)

    documents: list[dict[str, Any]] = []
    for sop in sops:
        title = str(sop.get("title") or "")
        body = str(sop.get("body") or "")
        documents.append(
            {
                "doc_id": str(sop.get("id")),
                "title": title,
                "version": str(sop.get("version") or ""),
                "body": body,
                "title_lower": title.lower(),
                "body_lower": body.lower(),
            }
        )

    if not documents:
        return []

    tokens = _tokenize(query)
    if not tokens:
        return []

    total = len(documents)
    average_length = sum(len(document["body"]) for document in documents) / total or 1.0
    k1, b = 1.2, 0.75

    hits: list[dict[str, Any]] = []
    for document in documents:
        score = 0.0
        for token in tokens:
            title_tf = document["title_lower"].count(token)
            body_tf = document["body_lower"].count(token)
            weighted_tf = 3 * title_tf + body_tf
            if weighted_tf == 0:
                continue
            doc_frequency = sum(
                1
                for candidate in documents
                if token in candidate["title_lower"] or token in candidate["body_lower"]
            )
            if doc_frequency == 0:
                continue
            idf = math.log((total + 1) / (doc_frequency + 0.5))
            length_norm = 1 - b + b * (len(document["body"]) / average_length)
            score += idf * (weighted_tf * (k1 + 1)) / (weighted_tf + k1 * length_norm)
        if score > 0:
            hits.append(
                {
                    "doc_id": document["doc_id"],
                    "title": document["title"],
                    "version": document["version"],
                    "snippet": _make_snippet(document["body"], tokens),
                    "score": round(score, 4),
                }
            )

    hits.sort(key=lambda item: (-item["score"], item["doc_id"]))
    return hits[:top_k_int]
