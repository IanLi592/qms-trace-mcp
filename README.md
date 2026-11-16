# qms-trace-mcp · 研发文档追溯核查 MCP Server

给「医疗器械研发质量体系」提供一组**只读、可审计、可复现**的**文档追溯核查**工具（MCP 形态）：DHF 完整性、需求—设计—测试追溯链路断点、需求质量、SOP 检索、合规佐证草稿，以及每次调用的审计日志。

> **数据声明：仓库中的全部项目、需求、设计、测试、缺陷、SOP 都是合成的测试夹具，不含任何真实患者、产品、公司或体系文件内容。** 本项目未接入 DOORS / ALM / ClearQuest / Windchill / 真实 DHF 系统。

> **为什么做这个项目：** 本仓库是围绕飞利浦（Philips）苏州「AI / 大语言模型应用工程师」一职的 JD 逐条搭建的工程样例。JD 中的 DHF 完整性核查、追溯链路缺失识别、需求质量校验、合规佐证初稿、只读对接通道、审计日志、人工审核、自动化测试与回归，在这里各有一个可运行、可测试的最小实现。
>
> 它演示的是**工程切面**，不是医疗体系经验，也不是生产系统——当前没做什么、接真实体系还缺什么，见文末「边界」。

## 为什么是这个形态

- **确定性优先**：所有检查都是规则代码。同一份输入运行两次，结果逐字节一致（写入文件涉及的路径/时间戳/哈希与审计日志除外），审计日志里的 `result_sha256` 可以直接比对。
- **只读不是提示词约束**：SQLite 以 `file:...?mode=ro&immutable=1` 打开；SQL 只来自 `db.py` 中的命名查询白名单。模型能给数据库的只有查询名和标量参数，拼 SQL 没有入口。
- **全程无 LLM 调用**：没有 OpenAI / Anthropic / LangChain 等 SDK 依赖，测试 `test_no_llm_sdk_imports_in_source` 会扫描源码。这个项目的价值是「可审计」，不是「让模型自由发挥」。
- **人在回路**：`draft_compliance_evidence` 默认只返回预览；只有显式 `confirm=True` 才写文件，且草稿含审核人签署区，不构成自动合规判定。

## 快速开始

```bash
# 1. 安装依赖（建议 Python 3.12；CI 固定 3.12）
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# 2. 生成合成数据库 data/qms.db
python scripts/build_fixtures.py

# 3. 启动 MCP 服务（stdio）
#    bash:
PYTHONPATH=src python -m qms_mcp.server
#    Windows cmd:
#    set PYTHONPATH=src && python -m qms_mcp.server
#    PowerShell:
#    $env:PYTHONPATH="src"; python -m qms_mcp.server

# 4. 运行测试
python -m pytest -q
```

当前测试结果：**67 passed**（`python -m pytest -q`）。

MCP 客户端配置示例（把路径换成你的实际路径）：

```json
{
  "mcpServers": {
    "qms-trace": {
      "command": "python",
      "args": ["-m", "qms_mcp.server"],
      "env": {
        "PYTHONPATH": "D:/projects/qms-trace-mcp/src"
      }
    }
  }
}
```

## MCP 工具（7 个）

| 工具 | 作用 | 关键返回值 |
| --- | --- | --- |
| `list_projects()` | 列出 3 个合成项目 | `id / name / phase`，按 id 排序 |
| `check_dhf_completeness(project_id)` | 按 `REQUIRED_DHF_CATEGORIES` 核查 DHF | 每类 `present / incomplete / missing`、文档引用、汇总计数 |
| `find_traceability_gaps(project_id)` | 需求 → 设计 → 测试链路 | 缺设计、缺测试、孤儿设计项、无需求测试、**缺陷影响面**、计数 |
| `check_requirement_quality(project_id)` | 需求可验证性 | 缺验收标准、缺验证方法、模糊措辞、不可测试，附 `requirement_id` |
| `search_sop(query, top_k=5)` | SOP 关键词检索（BM25-lite） | 文档编号、标题、版本、命中片段、分数 |
| `draft_compliance_evidence(project_id, confirm=False)` | 合规佐证草稿 | 默认预览、`written=false`；`confirm=true` 写入 `output/evidence_<project>_<UTC时间戳>.md` |
| `get_audit_log(limit=20)` | 审计日志尾部 | 记录列表（旧 → 新） |

`find_traceability_gaps` 同时承担「缺陷影响分析」：`defect_impact` 段按严重度排序，标出每个缺陷关联需求的下游链路是否完整。变更影响则通过 DHF 的「变更记录」类别核查覆盖。没有单独再造一个缺陷工具。

## 资源与提示词

- `qms://dhf/index`：全部项目的 DHF 必需类别清单（已具备 / 不完整 / 缺失计数）。
- `qms://trace/matrix/{project_id}`：需求 → 设计 → 测试矩阵（markdown），附孤儿设计项与无需求测试。
- `qms://sop/{doc_id}`：SOP 全文、版本号。
- `review_gate_checklist`：设计评审 gate 前的检查提示词模板，按顺序要求调用上面 5 个工具并引用返回的 ID。

## JD 对应表

| 岗位要求 | 本仓库的实际实现（文件 + 函数 + 测试） |
| --- | --- |
| DHF 完整性核查 | `src/qms_mcp/rules.py::check_dhf_completeness()`，类别常量 `REQUIRED_DHF_CATEGORIES`；工具 `check_dhf_completeness`；测试 `tests/test_rules_dhf.py::test_gap_project_dhf_exact_counts` |
| 追溯链路缺失识别 | `src/qms_mcp/rules.py::find_traceability_gaps()`；工具同名；测试 `tests/test_rules_trace.py::test_gap_project_trace_exact_counts`、`test_orphan_design_items_exact`、`test_tests_without_requirement_reasons` |
| 缺陷与变更影响分析 | 缺陷影响：`find_traceability_gaps()` 的 `defect_impact` 段，按严重度排序并判断下游链路；变更影响：DHF 必需类别中的「变更记录」核查；测试 `tests/test_rules_trace.py::test_traceability_defect_impact_section`、`tests/test_rules_dhf.py::test_gap_project_dhf_statuses_and_doc_refs` |
| 合规佐证初稿 | `src/qms_mcp/evidence.py::build_draft()` / `write_draft()`；工具 `draft_compliance_evidence`；测试 `tests/test_evidence.py::test_confirm_writes_file`、`test_evidence_contains_synthetic_notice_and_signoff` |
| 只读对接通道 | `src/qms_mcp/db.py::connect_readonly()`（`mode=ro&immutable=1`）+ `QUERIES` 命名查询白名单 + `fetch_all()`；测试 `tests/test_db.py::test_sqlite_rejects_write_on_readonly_connection`、`test_unknown_query_name_rejected`、`test_readonly_uri_is_mode_ro_immutable` |
| 审计日志 | `src/qms_mcp/audit.py::record()` / `tail()`；工具 `get_audit_log`；测试 `tests/test_audit.py::test_audit_record_shape_and_hash`、`test_every_tool_call_appends_audit_record` |
| 人工审核 | `draft_compliance_evidence(confirm=False)` 拒绝写盘，草稿含审核人/日期/签署区；测试 `tests/test_evidence.py::test_preview_writes_nothing`、`test_confirm_writes_file` |
| 自动化测试与回归 | `tests/` 下 67 个 pytest 用例 + `pytest.ini` + `.github/workflows/ci.yml`（push/PR 跑 `pytest -q`）；确定性测试 `tests/test_server_tools.py::test_tool_calls_are_deterministic`、`tests/test_audit.py::test_same_call_produces_same_result_hash` |
| 结果可复现 / 审计追溯 | 每次**成功**调用的审计记录 `result_sha256` 是规范化 JSON 的 sha256（失败调用为 `null`）；测试 `tests/test_audit.py::test_result_hash_matches_manual_canonical_json` |

## 安全设计

### 只读边界

- 连接串：`file:<abs path>?mode=ro&immutable=1`。SQLite 层直接拒绝 `INSERT / UPDATE / DELETE`，测试会在真实连接上尝试写入并断言 `OperationalError`。
- 每次工具调用打开新连接、用完关闭，避免长连接持有旧快照。
- `immutable=1` 的前提是数据库文件在服务运行期间不被替换；如果重新运行 `build_fixtures.py`，请重启 MCP 服务。

### 命名查询白名单

- `db.QUERIES` 是唯一的 SQL 来源；`fetch_all(name, params)` 只接受白名单里的名字。
- 参数名从 SQL 的 `:param` 反向推导，调用方多传或漏传都会抛 `InvalidQueryParamsError`。
- 加载/取用时再次检查 SQL 以 `SELECT` / `WITH` 开头，防止未来有人误加写语句。

### 审计日志

每次工具调用追加一行 JSONL 到 `logs/audit.jsonl`（可用 `QMS_AUDIT_PATH` 覆盖），字段固定：

| 字段 | 说明 |
| --- | --- |
| `schema_version` | 当前为 1 |
| `timestamp` | UTC ISO-8601，毫秒精度 |
| `tool` | 工具名 |
| `args` | 脱敏参数：>120 字符截断；`body/text/content` 等字段直接记 `<redacted>` |
| `ok` / `error` | 成功与否；错误含异常类型和消息 |
| `duration_ms` | 耗时（毫秒） |
| `result_sha256` | 规范化 JSON 结果的 sha256；失败为 `null` |

**不会记录完整文档正文。** 日志本身不参与确定性比较。

### 人工审核（HITL）

- `confirm=False`：只返回预览 markdown，不创建目录、不写文件。
- `confirm=True`：写入 `output/evidence_<project>_<timestamp>.md`，返回相对路径、绝对路径和文件 sha256。
- 草稿第一段就是「审核结论（由审核人填写）」，含审核人、日期、结论、签署；末尾声明它不构成自动合规判定。

### 输入限制

- `search_sop` 的 query 上限 200 字符；`top_k` 收敛到 1..20。
- `get_audit_log` 的 `limit` 收敛到 1..200。
- 项目不存在、query 为空等**工具调用**会抛 `ValueError`，失败也会进审计日志；未知 SOP 的**资源读取**同样报错（资源读取不属于工具调用，不写工具审计）。

## 数据模型（合成夹具）

| 表 | 字段 | 说明 |
| --- | --- | --- |
| `projects` | `id, name, phase` | 3 个项目；`PRJ-1003` 是缺口样例 |
| `requirements` | `id, project_id, source_doc, text, verification_method, acceptance_criteria, design_id, test_id` | 需求与设计/测试的显式链接 |
| `design_items` | `id, project_id, requirement_id` | 设计项；允许空链接或悬空链接以模拟孤儿 |
| `test_records` | `id, project_id, design_id, result, status` | 测试记录；通过 design_id 回溯需求 |
| `dhf_items` | `project_id, category, doc_ref, present` | DHF 类别与文档引用；`present=0` 表示已声明但不完整 |
| `sops` | `id, title, version, body` | 6 份合成 SOP |
| `defects` | `id, project_id, requirement_id, severity, status` | 缺陷；严重度 `致命/严重/一般/轻微` |
| `meta` | `key, value` | 数据集标记：`dataset=synthetic-fixtures-v1` |

`PRJ-1003` 的固定缺口（测试精确断言）：

- DHF：已具备 2、类内不完整 2（风险管理、设计评审记录）、整类缺失 1（变更记录）。
- 追溯：缺设计 3、缺测试 3、孤儿设计项 2、无需求测试 3。
- 需求质量：缺验收标准 1、缺验证方法 2、模糊措辞 5、不可测试 2。
- 缺陷：未关闭 3，其中 1 个挂在追溯不完整的需求上。

## 目录结构

```
qms-trace-mcp/
├── README.md
├── ARCHITECTURE.md
├── requirements.txt
├── pytest.ini
├── .gitignore
├── .github/workflows/ci.yml
├── scripts/build_fixtures.py       # 生成 data/qms.db（合成数据）
├── src/qms_mcp/
│   ├── __init__.py
│   ├── server.py                   # FastMCP 工具/资源/提示词注册
│   ├── db.py                       # 只读连接 + 命名查询白名单
│   ├── audit.py                    # JSONL 审计 + 脱敏 + 结果哈希
│   ├── rules.py                    # 纯函数规则（DHF/追溯/质量/检索）
│   └── evidence.py                 # 合规佐证草稿构建与落盘
├── tests/                          # 67 个 pytest 用例
├── data/                           # qms.db 生成物（gitignore）
└── logs/                           # audit.jsonl（gitignore）
```

## 边界

**这不是生产系统。** 本项目用来验证「研发文档追溯核查 harness」的几个工程做法在代码层面成立——只读数据通道、确定性规则、审计、人在回路、自动化测试——不用于生产合规决策。下面分两块说明：当前**没做什么**，以及要接上真实体系还**缺什么**。

### 当前不做的

1. **全部数据为合成的测试夹具**，`scripts/build_fixtures.py` 手工编造；没有真实患者、产品、公司或体系文件。
2. **没有接入任何真实系统**：未连接 DOORS、ALM、ClearQuest、Windchill、真实 DHF 或其他 PLM/QMS 数据库。只读通道的对接对象是本地 SQLite 夹具。
3. **`draft_compliance_evidence` 产出的是给审核人复核的草稿**，不是自动合规判定，也不替代体系规定的评审、批准与归档。
4. **缺陷与变更影响分析是规则级追溯影响**，不是完整的 FMEA、变更控制委员会流程或风险评估文档。
5. **没有身份认证、权限模型或多租户隔离**：本地 stdio 服务，默认信任本机调用方。
6. **不解析真实文档**：没有 PDF/Word 解析、OCR、电子签名或版本库集成；SOP 与 DHF 都是结构化夹具。

### 要接真实体系还缺什么

- **只读适配器**：在 `db.py` 外接 DOORS / ALM / Windchill 的只读 API，同时保持「命名查询 + 只读」这条边界不变。
- **规则可配置**：模糊词表、DHF 类别清单、可测量判据目前写在 `rules.py` 常量里，需要外置为配置，才能由质量部门自己维护。
- **审计加固**：本地追加文件没有轮转、签名链或集中采集；进入生产环境应接入日志平台并做防篡改。
- **检索补强**：当前是 BM25-lite 关键词匹配，没有中文分词、向量检索与重排。
- **多人协作**：需要补认证、授权、速率限制与审计完整性保护。
