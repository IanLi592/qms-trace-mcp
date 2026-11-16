"""构建合成测试夹具 data/qms.db。

所有项目、需求、设计项、测试、缺陷、SOP 均为手工编造的合成数据，
不含任何真实患者、产品、公司或体系文件内容。PRJ-1003 被刻意设计为
"缺口样例"，其核查结果固定，供 pytest 断言精确计数。

用法：
    python scripts/build_fixtures.py
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "qms.db"

SCHEMA = """
CREATE TABLE projects (
    id    TEXT PRIMARY KEY,
    name  TEXT NOT NULL,
    phase TEXT NOT NULL
);

CREATE TABLE requirements (
    id                  TEXT PRIMARY KEY,
    project_id          TEXT NOT NULL,
    source_doc          TEXT,
    text                TEXT NOT NULL,
    verification_method TEXT,
    acceptance_criteria TEXT,
    design_id           TEXT,
    test_id             TEXT
);

CREATE TABLE design_items (
    id             TEXT PRIMARY KEY,
    project_id     TEXT NOT NULL,
    requirement_id TEXT
);

CREATE TABLE test_records (
    id         TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    design_id  TEXT,
    result     TEXT,
    status     TEXT
);

CREATE TABLE dhf_items (
    project_id TEXT NOT NULL,
    category   TEXT NOT NULL,
    doc_ref    TEXT,
    present    INTEGER NOT NULL CHECK (present IN (0, 1)),
    PRIMARY KEY (project_id, category, doc_ref)
);

CREATE TABLE sops (
    id      TEXT PRIMARY KEY,
    title   TEXT NOT NULL,
    version TEXT NOT NULL,
    body    TEXT NOT NULL
);

CREATE TABLE defects (
    id             TEXT PRIMARY KEY,
    project_id     TEXT NOT NULL,
    requirement_id TEXT,
    severity       TEXT NOT NULL,
    status         TEXT NOT NULL
);

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX idx_requirements_project ON requirements(project_id);
CREATE INDEX idx_design_project       ON design_items(project_id);
CREATE INDEX idx_tests_project        ON test_records(project_id);
CREATE INDEX idx_dhf_project          ON dhf_items(project_id);
CREATE INDEX idx_defects_project      ON defects(project_id);
"""

PROJECTS = [
    ("PRJ-1001", "Cardiac Monitor CM-300", "设计转移"),
    ("PRJ-1002", "Infusion Pump IP-500", "设计验证"),
    # 缺口样例：DHF、追溯、需求质量、缺陷影响四类问题都集中在这里。
    ("PRJ-1003", "Patient Monitor PM-900", "概念"),
]

REQUIREMENTS = [
    # ---- PRJ-1001：干净样例 ----
    ("R-1001", "PRJ-1001", "SRS-CM300-001",
     "心率测量范围应为 30–250 bpm", "测试",
     "30–250 bpm 范围内误差不大于 ±3 bpm", "D-1001", "T-1001"),
    ("R-1002", "PRJ-1001", "SRS-CM300-002",
     "设备在满电状态下应连续工作不少于 8 小时", "测试",
     "连续工作 8 h 后电量不低于 10%", "D-1002", "T-1002"),
    ("R-1003", "PRJ-1001", "SRS-CM300-003",
     "报警音量应不小于 65 dB(A)", "检查",
     "1 m 处测量不低于 65 dB(A)", "D-1003", "T-1003"),
    # ---- PRJ-1002：干净样例 ----
    ("R-2001", "PRJ-1002", "SRS-IP500-001",
     "输液流速范围应为 0.1–999 mL/h", "测试",
     "0.1–999 mL/h 范围内误差不大于 ±5%", "D-2001", "T-2001"),
    ("R-2002", "PRJ-1002", "SRS-IP500-002",
     "阻塞报警触发时间应不大于 15 秒", "测试",
     "阻塞后 15 s 内触发声光报警", "D-2002", "T-2002"),
    ("R-2003", "PRJ-1002", "SRS-IP500-003",
     "电池续航时间应不少于 6 小时", "测试",
     "满电连续输液 6 h 后仍可运行", "D-2003", "T-2003"),
    # ---- PRJ-1003：缺口样例 ----
    ("R-3001", "PRJ-1003", "SRS-PM900-001",
     "报警响应时间应不大于 2 秒", "测试",
     "报警触发后 2 s 内发出声光报警", "D-3001", "T-3001"),
    ("R-3002", "PRJ-1003", "SRS-PM900-002",
     "设备应支持连续 72 小时无中断运行", "测试",
     "连续运行 72 h 无重启、无数据丢失", None, None),
    ("R-3003", "PRJ-1003", "SRS-PM900-003",
     "系统应尽量降低待机功耗", "测试",
     "待机功耗不大于 0.5 W", "D-3002", None),
    ("R-3004", "PRJ-1003", "SRS-PM900-004",
     "操作界面应友好，满足要求", None, None, None, "T-3002"),
    ("R-3005", "PRJ-1003", "SRS-PM900-005",
     "电池电量低于 20% 时应提示更换", "检查",
     "电量 20% 时界面出现更换提示", "D-3003", "T-3003"),
    ("R-3006", "PRJ-1003", "SRS-PM900-006",
     "适当提高报警音量，适配 ICU、急诊等环境", None,
     "音量不低于 65 dB(A)", None, None),
    ("R-3007", "PRJ-1003", "SRS-PM900-007",
     "开机自检应较快完成", "测试",
     "自检在 15 s 内完成", "D-3004", "T-3004"),
    ("R-3008", "PRJ-1003", "SRS-PM900-008",
     "系统应支持多种报警等级", "演示",
     "良好", "D-3005", "T-3005"),
]

DESIGN_ITEMS = [
    # PRJ-1001
    ("D-1001", "PRJ-1001", "R-1001"),
    ("D-1002", "PRJ-1001", "R-1002"),
    ("D-1003", "PRJ-1001", "R-1003"),
    # PRJ-1002
    ("D-2001", "PRJ-1002", "R-2001"),
    ("D-2002", "PRJ-1002", "R-2002"),
    ("D-2003", "PRJ-1002", "R-2003"),
    # PRJ-1003
    ("D-3001", "PRJ-1003", "R-3001"),
    ("D-3002", "PRJ-1003", "R-3003"),
    ("D-3003", "PRJ-1003", "R-3005"),
    ("D-3004", "PRJ-1003", "R-3007"),
    ("D-3005", "PRJ-1003", "R-3008"),
    ("D-3006", "PRJ-1003", None),        # 孤儿设计项：没有需求来源
    ("D-3007", "PRJ-1003", "R-9999"),    # 孤儿设计项：指向不存在的需求
]

TEST_RECORDS = [
    # PRJ-1001
    ("T-1001", "PRJ-1001", "D-1001", "通过", "已完成"),
    ("T-1002", "PRJ-1001", "D-1002", "通过", "已完成"),
    ("T-1003", "PRJ-1001", "D-1003", "通过", "已完成"),
    # PRJ-1002
    ("T-2001", "PRJ-1002", "D-2001", "通过", "已完成"),
    ("T-2002", "PRJ-1002", "D-2002", "通过", "已完成"),
    ("T-2003", "PRJ-1002", "D-2003", "通过", "已完成"),
    # PRJ-1003
    ("T-3001", "PRJ-1003", "D-3001", "通过", "已完成"),
    ("T-3002", "PRJ-1003", None, "待定", "进行中"),
    ("T-3003", "PRJ-1003", "D-3003", "通过", "已完成"),
    ("T-3004", "PRJ-1003", "D-3004", "通过", "已完成"),
    ("T-3005", "PRJ-1003", "D-3005", "通过", "已完成"),
    ("T-3006", "PRJ-1003", "D-3006", "未执行", "待执行"),
    ("T-3007", "PRJ-1003", None, "未执行", "待执行"),
]

DHF_ITEMS = [
    # PRJ-1001：完整
    ("PRJ-1001", "需求规格", "DHF-1001-需求规格", 1),
    ("PRJ-1001", "风险管理", "DHF-1002-风险管理", 1),
    ("PRJ-1001", "验证报告", "DHF-1003-验证报告", 1),
    ("PRJ-1001", "设计评审记录", "DHF-1004-设计评审记录", 1),
    ("PRJ-1001", "变更记录", "DHF-1005-变更记录", 1),
    # PRJ-1002：完整
    ("PRJ-1002", "需求规格", "DHF-2001-需求规格", 1),
    ("PRJ-1002", "风险管理", "DHF-2002-风险管理", 1),
    ("PRJ-1002", "验证报告", "DHF-2003-验证报告", 1),
    ("PRJ-1002", "设计评审记录", "DHF-2004-设计评审记录", 1),
    ("PRJ-1002", "变更记录", "DHF-2005-变更记录", 1),
    # PRJ-1003：风险管理与设计评审记录不完整；变更记录整类缺失
    ("PRJ-1003", "需求规格", "DHF-3001-需求规格", 1),
    ("PRJ-1003", "风险管理", "DHF-3002-风险管理", 0),
    ("PRJ-1003", "验证报告", "DHF-3003-验证报告", 1),
    ("PRJ-1003", "设计评审记录", "DHF-3004-设计评审记录", 0),
]

SOPS = [
    (
        "SOP-QMS-001",
        "设计控制程序",
        "3.2",
        "【合成测试数据】本程序规定设计输入、设计输出、设计评审、设计验证、"
        "设计确认和设计转换的控制要求。设计输入必须可验证，设计输出必须可追溯"
        "到设计输入。设计评审应保留评审记录并纳入 DHF。设计变更按变更控制程序执行。",
    ),
    (
        "SOP-QMS-002",
        "设计历史文档（DHF）管理规程",
        "2.1",
        "【合成测试数据】DHF 应覆盖需求规格、风险管理、验证报告、设计评审记录、"
        "变更记录五类文件。DHF 完整性由项目负责人定期核查，缺失或不完整的类别"
        "必须在设计评审 gate 前关闭。DHF 归档后不得随意修改，修订需保留版本记录。",
    ),
    (
        "SOP-QMS-003",
        "风险管理程序",
        "4.0",
        "【合成测试数据】风险管理贯穿产品生命周期，包括风险分析、风险评价、"
        "风险控制、剩余风险评价和生产后信息收集。风险管理文件应可追溯到需求、"
        "设计项和验证活动。风险控制措施的有效性必须通过验证或确认。",
    ),
    (
        "SOP-QMS-004",
        "设计验证与确认程序",
        "2.4",
        "【合成测试数据】设计验证确认设计输出满足设计输入，设计确认确认产品满足"
        "预期用途。验证方案应规定样本量、接受准则和测试方法。测试记录应关联"
        "设计项和需求，形成可追溯的证据链。未通过项应开出缺陷并跟踪关闭。",
    ),
    (
        "SOP-QMS-005",
        "变更控制程序",
        "1.8",
        "【合成测试数据】变更申请应说明变更原因、影响范围和风险评估。变更实施前"
        "必须完成影响分析，识别受影响的 DHF 文件、需求、设计和测试。重大变更需"
        "重新验证并执行回归测试，变更记录纳入 DHF 的变更记录类别。",
    ),
    (
        "SOP-QMS-006",
        "缺陷管理与纠正预防措施（CAPA）",
        "2.0",
        "【合成测试数据】缺陷按致命、严重、一般、轻微分级。缺陷应关联需求或设计项，"
        "以便评估影响面。未关闭缺陷应在设计评审 gate 前完成风险评价。重复缺陷"
        "或系统性缺陷应启动 CAPA，分析根本原因并验证纠正措施有效性。",
    ),
]

DEFECTS = [
    ("BUG-1001", "PRJ-1001", "R-1001", "轻微", "关闭"),
    ("BUG-2001", "PRJ-1002", "R-2002", "一般", "打开"),
    ("BUG-3001", "PRJ-1003", "R-3001", "严重", "打开"),
    ("BUG-3002", "PRJ-1003", "R-3003", "一般", "关闭"),
    ("BUG-3003", "PRJ-1003", "R-3004", "致命", "打开"),
    ("BUG-3004", "PRJ-1003", None, "轻微", "打开"),
]

META = [
    ("dataset", "synthetic-fixtures-v1"),
    (
        "warning",
        "全部数据为合成测试夹具，不含任何真实患者、产品、公司或体系文件内容。",
    ),
    ("gap_sample", "PRJ-1003"),
]


def db_path() -> Path:
    raw = os.environ.get("QMS_DB_PATH")
    return Path(raw).expanduser() if raw else DEFAULT_DB


def build() -> Path:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            candidate.unlink()

    connection = sqlite3.connect(path)
    try:
        connection.executescript(SCHEMA)
        connection.executemany("INSERT INTO projects VALUES (?, ?, ?)", PROJECTS)
        connection.executemany("INSERT INTO requirements VALUES (?, ?, ?, ?, ?, ?, ?, ?)", REQUIREMENTS)
        connection.executemany("INSERT INTO design_items VALUES (?, ?, ?)", DESIGN_ITEMS)
        connection.executemany("INSERT INTO test_records VALUES (?, ?, ?, ?, ?)", TEST_RECORDS)
        connection.executemany("INSERT INTO dhf_items VALUES (?, ?, ?, ?)", DHF_ITEMS)
        connection.executemany("INSERT INTO sops VALUES (?, ?, ?, ?)", SOPS)
        connection.executemany("INSERT INTO defects VALUES (?, ?, ?, ?, ?)", DEFECTS)
        connection.executemany("INSERT INTO meta VALUES (?, ?)", META)
        connection.commit()
    finally:
        connection.close()
    return path


def main() -> int:
    path = build()
    connection = sqlite3.connect(path)
    try:
        tables = ["projects", "requirements", "design_items", "test_records", "dhf_items", "sops", "defects", "meta"]
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in tables
        }
    finally:
        connection.close()

    print(f"已生成合成测试数据库: {path}")
    print("表行数: " + ", ".join(f"{name}={count}" for name, count in counts.items()))
    print("缺口样例项目: PRJ-1003（DHF 不完整、追溯缺失、需求质量与缺陷影响均有问题）")
    print("提示: 全部数据为合成测试夹具，不含任何真实数据。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
