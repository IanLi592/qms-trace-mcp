# 架构说明

本文说明 qms-trace-mcp 的数据模型、只读边界、审计设计、确定性保证，以及为什么这个场景不使用 LLM。所有描述都对应仓库中的实际代码。

## 1. 分层

```
合成夹具 (scripts/build_fixtures.py)
        │  写入 data/qms.db（离线、一次性）
        ▼
db.py        只读 SQLite + 命名查询白名单 + 参数名精确匹配
        │  返回 list[dict]
        ▼
rules.py     纯函数规则：DHF / 追溯 / 缺陷影响 / 需求质量 / BM25-lite 检索
        │  返回确定性 dict
        ▼
evidence.py  把规则结果渲染成待人工签署的 markdown 草稿
        │
        ▼
server.py    FastMCP 工具 / 资源 / 提示词；每次工具调用经 _audited() 写 JSONL
        │
        ▼
audit.py     脱敏参数、耗时、ok/error、结果 sha256
```

关键点：**规则层不碰数据库**。`rules.py` 的函数只接收普通 dict / list，因此可以脱离 SQLite 做纯单元测试；数据库访问集中在 `db.py`，MCP 编排集中在 `server.py`。

## 2. 数据模型

### 表与关系

| 表 | 主键 | 关系 |
| --- | --- | --- |
| `projects` | `id` | 所有业务表的项目维度 |
| `requirements` | `id` | `project_id → projects.id`；`design_id / test_id` 是显式链接 |
| `design_items` | `id` | `project_id → projects.id`；`requirement_id → requirements.id`（可为空/悬空） |
| `test_records` | `id` | `project_id → projects.id`；`design_id → design_items.id`（可为空/悬空） |
| `dhf_items` | `(project_id, category, doc_ref)` | `present ∈ {0,1}`；0 表示「已声明但不完整」 |
| `sops` | `id` | 独立文档表，供检索与引用 |
| `defects` | `id` | `project_id → projects.id`；`requirement_id` 可为空 |
| `meta` | `key` | 数据集标记，当前含 `dataset=synthetic-fixtures-v1` 与合成数据警告 |

### 为什么存在悬空链接

夹具刻意包含几类「脏数据」，用来覆盖真实遗留系统的常见问题：

- `requirements.design_id` / `test_id` 为空：需求未建立下游链接。
- `design_items.requirement_id` 为空或指向不存在的需求：孤儿设计项。
- `test_records.design_id` 为空，或其设计项没有需求：测试无法回溯需求。
- `defects.requirement_id` 为空：缺陷没有需求上下文。

因此数据库**不启用外键强制**（`PRAGMA foreign_keys` 默认关闭），否则这些夹具无法写入。只读连接本身也不会执行写操作，悬空链接只参与规则判定。

### 缺口样例 PRJ-1003

规则测试对其断言精确计数，避免「大概有几个问题」这种不可回归的结论：

| 维度 | 固定结果 |
| --- | --- |
| DHF | 已具备 2、不完整 2、缺失 1 |
| 追溯 | 缺设计 3、缺测试 3、孤儿设计 2、无需求测试 3 |
| 需求质量 | 缺验收标准 1、缺验证方法 2、模糊措辞 5、不可测试 2 |
| 缺陷 | 未关闭 3，其中 1 个挂在追溯不完整的需求上 |

## 3. 只读边界

### 3.1 SQLite URI

`db.connect_readonly()` 使用：

```text
file:///D:/projects/qms-trace-mcp/data/qms.db?mode=ro&immutable=1
```

- `mode=ro`：操作系统层只读；`INSERT / UPDATE / DELETE / DDL` 会抛 `OperationalError`。
- `immutable=1`：告诉 SQLite 文件不会被其他进程修改，跳过锁与变更检测，读路径更简单。
- 代价：如果服务运行期间重新生成了 `data/qms.db`，连接可能看到旧快照；当前实现每次调用新建连接，重新生成后重启服务即可。

测试 `tests/test_db.py::test_sqlite_rejects_write_on_readonly_connection` 在真实连接上尝试 `INSERT` 与 `DELETE`，断言失败。

### 3.2 命名查询白名单

`db.QUERIES` 是唯一的 SQL 来源，共 10 条，全部为 `SELECT`。`fetch_all(name, params)` 的行为：

1. `name` 不在 `QUERIES` → `UnknownQueryError`。
2. SQL 不以 `SELECT` / `WITH` 开头 → `DatabaseError`（防御未来误改）。
3. 参数集合由 SQL 中的 `:param` 反向推导；多传、漏传 → `InvalidQueryParamsError`。
4. 用 `sqlite3` 的命名参数绑定执行，字符串永远不拼进 SQL。

因此 MCP 客户端（包括其背后的模型）能影响的只有「选哪条预定义查询」和「标量参数值」。加入新查询必须改代码，而不是让模型生成 SQL。

### 3.3 文件写入边界

唯一会写文件的是 `draft_compliance_evidence(confirm=True)`：

- 输出目录由 `QMS_OUTPUT_DIR` 或默认 `output/` 决定，**不接受模型传入路径**。
- 文件名中的项目 ID 经过 `safe_project_token()` 过滤（只留字母、数字、`.`、`_`、`-`），避免路径穿越。
- 写入前检查同名文件，必要时追加 `_1`、`_2`，不覆盖已有草稿。

## 4. 审计设计

### 4.1 记录时机

`server._audited(tool_name, args, fn)` 包住每个工具：

- 开始计时。
- 成功：调用 `audit.record(..., ok=True, result=result)`，计算 `result_sha256`。
- 失败：调用 `audit.record(..., ok=False, error="<异常类型>: <消息>")`，然后把异常原样抛给 MCP 客户端。

因此失败调用同样有审计记录，且 `result_sha256 = null`。

### 4.2 字段与脱敏

`audit.record()` 写入一行 JSONL：

```json
{
  "schema_version": 1,
  "timestamp": "2026-01-01T00:00:00.000Z",
  "tool": "search_sop",
  "args": {"query": "DHF", "top_k": 5},
  "ok": true,
  "error": null,
  "duration_ms": 1.234,
  "result_sha256": "…"
}
```

脱敏规则（`audit.sanitize()`）：

- 字符串超过 120 字符：保留前 120 字符并附 `…<truncated N chars>`。
- 键名命中 `body / text / content / document / doc_body / sop_body / full_text`：直接写 `<redacted>`。
- 列表最多 20 项、字典最多 20 键、递归深度最多 4。
- 错误消息也截断，避免异常里夹带大段内容。

**完整文档正文不会进入审计日志。** `get_audit_log` 返回的也是这些脱敏记录。

### 4.3 结果哈希

`audit.result_sha256(result)` = `sha256(canonical_json(result))`，其中 `canonical_json` 使用：

```python
json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
```

同一份输入得到同一份工具结果，就得到同一个哈希。离线复现时可以重跑工具并对比哈希，而不是人工比对整段 JSON。

注意：`timestamp` 和 `duration_ms` 本身不确定，但它们不影响结果哈希；审计文件明确不参与确定性比较。

## 5. 确定性保证

### 5.1 规则层

- 所有输出列表都有显式排序键：需求按 id、DHF 按 `REQUIRED_DHF_CATEGORIES` 顺序、缺陷按「严重度 + id」、检索按「分数降序 + doc_id」。
- 不使用 `set` 迭代顺序作为输出顺序；需要集合时先 `sorted()`。
- 不把当前时间、随机数、进程信息写入工具结果。
- 浮点分数统一 `round(score, 4)`。

### 5.2 证据草稿

- 预览模式（`confirm=False`）调用 `build_draft(..., generated_at=None, preview=True)`，不包含任何时间戳，连续两次调用逐字节一致。
- 写入模式才注入 UTC 时间戳，且时间戳同时用于文件名和正文。
- 测试 `tests/test_evidence.py::test_preview_is_byte_identical_across_calls` 与 `tests/test_server_tools.py::test_tool_calls_are_deterministic` 覆盖这一点。

### 5.3 明确的不确定项

- 审计日志中的 `timestamp`、`duration_ms`。
- `draft_compliance_evidence(confirm=True)` 返回的文件名与 `sha256`（文件名含时间戳；内容含时间戳）。
- `get_audit_log` 的返回内容（日志在增长）。

除此之外，同一份夹具上的同一工具调用结果一致。

## 6. 人在回路（HITL）

`draft_compliance_evidence` 是两阶段接口：

| 调用 | 行为 | 返回 |
| --- | --- | --- |
| `confirm=False`（默认） | 只构建预览，不创建目录、不写文件 | `status=preview`, `written=false`, `path=null`, `preview=<markdown>` |
| `confirm=True` | 构建正文并写入 `output/evidence_<project>_<timestamp>.md` | `status=written`, `written=true`, `path`, `absolute_path`, `sha256`, `preview` |

草稿结构：

1. 审核结论：审核人、审核日期、结论（通过 / 有条件通过 / 退回）、签署，全部留空。
2. DHF 完整性。
3. 需求 → 设计 → 测试追溯与缺口明细。
4. 需求质量问题。
5. 缺陷影响面。
6. 引用的 SOP（文档编号、版本、命中片段）。
7. 声明：草稿不构成自动合规判定，不能替代评审、批准与归档记录。

工具只负责把规则结果整理成可审阅文本；是否引用、是否归档、结论是什么，都由授权审核人决定。

## 7. 为什么不用 LLM

这是刻意的设计选择，不是能力缺失：

1. **可复现性**：QMS 核查结论需要能被复现和解释。规则函数对同一输入永远给同一输出；LLM 输出受采样、模型版本、上下文影响。
2. **审计友好**：每个结论可以定位到具体规则、具体字段和具体测试。审计日志记录的是确定性结果哈希，而不是一段无法重放的生成文本。
3. **避免幻觉进入合规链路**：DHF 缺失、追溯断裂这类结论如果由模型「总结」，可能漏项或编造。规则引擎只声明它检查过的字段。
4. **数据不出本机**：服务不调用任何外部 API，合成夹具与后续真实适配都可以留在本地网络。
5. **成本与延迟**：67 个测试在本地约 1 秒跑完（pytest 计时）；测试运行不需要密钥，也不访问外部 API。

需要明确的是：**MCP 客户端可以是 LLM 驱动的**。本项目保证的是「服务端工具本身确定性、无模型调用」；客户端如何组织调用、如何解释结果，不在服务端控制范围内，也不应被当作合规判定。

## 8. 威胁模型与非目标

### 已考虑

| 风险 | 缓解 |
| --- | --- |
| 模型通过参数注入 SQL | SQL 只来自命名白名单；参数走绑定；不存在字符串拼接 |
| 模型试图写库 | `mode=ro&immutable=1`；SQLite 层拒绝 |
| 模型试图写任意路径 | 输出目录来自环境变量；文件名过滤项目 ID；不接受路径参数 |
| 日志泄露文档正文 | `SENSITIVE_KEYS` 脱敏 + 长字符串截断 |
| 超大输入拖垮服务 | query ≤200 字符、`top_k` ≤20、`limit` ≤200 |
| 失败调用无迹可查 | 异常路径同样写审计记录 |

### 未覆盖（生产前必须补）

- 身份认证、授权、多租户隔离：当前是本地 stdio 服务，信任本机调用方。
- 审计日志的轮转、签名链、集中采集、防篡改。
- 静态数据库文件的完整性与来源校验；`immutable=1` 假设文件可信。
- 真实系统适配器的限流、重试、凭据管理。
- 真实文档解析、电子签名、版本库与工作流集成。

## 9. 测试策略

测试运行在**真实生成的 SQLite 夹具**上，不 mock 数据库：

| 测试文件 | 覆盖点 |
| --- | --- |
| `test_db.py` | 命名查询白名单、参数精确匹配、只读写入失败、URI 形状 |
| `test_fixtures.py` | 合成数据标记、项目/需求/设计/测试/缺陷/SOP 的不变量 |
| `test_rules_dhf.py` | DHF 完整与缺口样例的精确计数、未知类别、稳定顺序 |
| `test_rules_trace.py` | 追溯缺口精确集合、孤儿设计、无需求测试原因、缺陷影响排序 |
| `test_rules_quality.py` | 四类质量问题、模糊词（含「等」与「等级」的区分）、干净项目 |
| `test_sop_search.py` | 关键词排序、引用字段、top_k 收敛、空查询 |
| `test_evidence.py` | 预览不落盘、确认写入、固定时间戳确定性、签署与合成声明 |
| `test_audit.py` | 记录字段、脱敏、七类工具均留痕、错误留痕、结果哈希一致 |
| `test_server_tools.py` | 7 工具注册、资源/模板/提示词、确定性、未知项目、无 LLM SDK |

CI（`.github/workflows/ci.yml`）在 Python 3.12 上执行：

```bash
pip install -r requirements.txt
python scripts/build_fixtures.py
pytest -q
```

## 10. 扩展路径

1. **接真实系统**：为 DOORS / ALM / Windchill 等实现只读适配器，把结果映射成当前 `rules.py` 接受的普通 dict。规则层无需改动。
2. **加规则**：在 `rules.py` 增加纯函数与常量，在 `tests/` 用固定 dict 覆盖；若需要新数据，在 `db.py` 增加命名查询并更新参数白名单。
3. **加工具**：在 `server.py` 用 `@mcp.tool()` 注册，并确保经 `_audited()` 包装。
4. **合规化审计**：给 JSONL 增加链式哈希或签名，接入集中日志平台；保留 `result_sha256` 的复现语义。
