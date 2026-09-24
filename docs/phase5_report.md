# Phase 5 阶段报告：Multi-Tool 综合分析与 Structured Output

## Phase 目标与完成内容

本阶段在 Phase 4 Tool Calling Loop 上增加单问题多 Tool 综合分析，并用简单的 Pydantic `AnalysisReport` 规范最终结果。业务范围仍只有商品、销售、库存和评价；没有加入 RAG、Memory、Streamlit、广告模块或新的业务计算。

完成内容：

- 新增 `ProductAgent.run_analysis()`，继续由模型依据 Tool 的 name、description 和 schema 自主选择必要工具，没有按 SKU 或关键词写固定路由。
- 支持同一模型响应中的多个 Tool Call，也支持跨轮补充 Tool；每个结果以匹配 `tool_call_id` 的 `ToolMessage` 回传。
- 新增 `AnalysisReport`：`sku`、`summary`、`findings`、`risk_level`、`recommendations`、`evidence_limits`。
- 最终文本必须通过严格 JSON/schema 校验。不合规时只允许一次纯格式修正，修正阶段禁止新增 Tool Call，并继续计入原有 6 次模型调用上限。
- 综合分析至少要有一次成功的业务 Tool 调用，避免模型跳过数据直接生成报告。
- 新增综合分析 CLI、离线测试和真实 API 验收脚本。

## 核心执行流程

```text
用户复杂问题
  → run_analysis 加载综合提示词与 AnalysisReport schema
  → Qwen 自主选择一个或多个 Tool
  → Phase 3 Tool 校验参数并调用 Phase 2 Service
  → Service 通过 CsvDataStore 读取 Mock Data、计算业务指标
  → 多个 ToolMessage 回传 Qwen
  → Qwen 综合证据生成 JSON
  → Pydantic 校验并返回稳定结构及工具审计记录
```

SKU001 的真实验收使用 `compare_sales_periods`：最近 30 天销量下降 34.3%、Sessions 下降 35.0%，Conversion Rate 从 5.97% 到 5.99%，基本稳定。结果只描述同步变化，当前数据不能证明 Sessions 下降的外部原因。

SKU002 的离线场景测试确认 Sessions 变化绝对值小于 2%，Conversion Rate 相对降幅超过 25%，所以恶化体现在转化和销量指标，而不是访问量。

SKU005 的真实验收组合 `compare_sales_periods` 与 `get_review_data`：销量下降约 40.1%、Sessions 基本持平、Conversion Rate 下降约 2.39 个百分点；平均评分从 4.68 降到 2.10，低分评价增至 47 条。销售与评价同期恶化是事实，但现有数据不能证明两者存在因果关系。

## Structured Output 的作用和边界

自由文本字段位置和类型不稳定，下游代码难以可靠读取。`AnalysisReport` 固定字段、类型、必填项、风险等级枚举及列表数量，让 CLI、测试和后续界面可以稳定消费结果。它只是最终结果的展示契约，不计算销量、转化率、评分或期间变化，也不能自动确认模型写出的每个业务数字；业务证据仍必须来自 Tool。

Phase 3 Tool Input Schema 约束“模型调用一个 Tool 时要传什么参数”，位于 LLM → Tool 的输入边界。Phase 5 Structured Output 约束“全部工具调用完成后 Agent 返回什么”，位于 Agent → 调用方的输出边界。

## 业务职责边界

CSV 加载与校验、日期窗口、销量和销售额汇总、加权 Conversion Rate、期间差值与相对变化、库存估算、评价均分和低分计数仍属于 Phase 2 Service。Tool 只负责输入 schema、调用 Service 和结果包装；LLM 负责选 Tool、组织证据和标注限制。Structured Output 不承担业务计算。

## 新增/修改文件及作用

- `src/agent/runner.py`：共享 `_run()`，增加 `run_analysis()`、结构校验、一次格式修正和成功 Tool 要求。
- `src/models/analysis_report.py`：`AnalysisReport` 与严格解析函数。
- `src/models/__init__.py`：导出输出模型接口。
- `src/prompts/analysis.py`：综合分析、证据边界、因果措辞及 JSON 规则。
- `scripts/run_analysis.py`：运行一次真实综合分析。
- `scripts/verify_analysis_live.py`：两条代表性真实验收并保存脱敏记录。
- `tests/test_analysis.py`：Multi-Tool、ToolMessage、结构验证、无数据、Tool 失败、格式失败、调用上限及 SKU002 场景测试。
- `docs/phase5_live_results.json`：最终真实验收记录。
- `README.md`：当前能力、测试数量和运行方式。

## 新技术及原因

本阶段使用 Pydantic 输出模型，因为最终 JSON 需要在运行时检查必填字段、类型、枚举和多余字段。没有采用更复杂的 LangChain 原生 Structured Output 接口：当前 Qwen OpenAI 兼容接口已经稳定支持消息和 Tool Calling，用“提示词提供 schema + 本地 Pydantic 校验”改动更小，失败路径也更容易教学和测试。

## 实际问题 → 原因 → 定位 → 解决

### 1. SKU005 首次真实结果没有通过结构校验

- 原因：Tool Calling 成功不等于最终文本一定是合法、完整的 JSON。
- 定位：首次真实验收中 SKU001 完成，SKU005 在 `parse_analysis_report()` 处失败；Tool 层无错误，因此问题位于模型最终文本与 Pydantic 的边界。
- 解决：允许最多一次仅修正格式的模型请求，明确不得新增事实或 Tool Call；第二次仍失败就停止。修正请求仍占用模型轮数。

### 2. SKU001 首次输出把同步变化写成“驱动”

- 原因：JSON schema 能约束结构，不能保证因果措辞正确。
- 定位：人工检查真实报告时，summary 使用因果表达，而 `evidence_limits` 同时承认不能证明原因。
- 解决：收紧综合提示词，并在真实验收中检查 summary/findings 的因果词。最终结果改为销量与 Sessions 同期、同幅下降且转化率稳定的证据表述。

## 测试结果

- Phase 5 针对性离线测试：15 个，全部通过。
- 全量离线回归：97 个，全部通过；Phase 1–4 无回归。
- 最终真实 Qwen 验收：2 个问题全部通过，共 5 次模型请求、3 次 Tool 调用。
  - SKU001：2 次模型请求、1 次 Tool 调用。
  - SKU005：3 次模型请求、2 次 Tool 调用。
- `.env` 保持 Git ignored；验收记录不含 API Key。

开发中还有一次失败的真实诊断运行：执行了 SKU001 和 SKU005 两个问题；SKU001 使用 2 次模型请求，SKU005 在最终结构校验处停止。旧脚本没有在异常中记录该失败问题的准确模型请求次数，因此这里不虚构数字。修正后只进行了上述最终两题验收。

## 当前限制

- Pydantic 验证结构，不能逐句核验所有数字；验收脚本只核对关键已知事实和因果边界。
- 风险等级由模型基于当前证据做简单分类，没有独立业务评分规则。
- 每个问题独立运行，没有 Memory。
- 仅使用本地模拟数据，没有 RAG、外部知识或实时业务数据。
- 格式修正只允许一次，仍失败会明确终止。

## 下一 Phase 边界

Phase 5 到此停止。下一 Phase 必须由用户明确指定；本阶段不实现 RAG、ChromaDB、Memory、Streamlit、LangGraph、MCP、Multi-Agent、Redis、Docker或数据库迁移。

## 理解/面试题

1. 为什么 Multi-Tool 不需要为每个复杂问题写固定 `if/else`？Tool 哪些信息帮助模型选择？
2. `AnalysisReport` 与 Tool Input Schema 分别位于哪条数据边界？
3. 为什么业务指标仍由 Service 计算，而不是让 LLM 从 CSV 推算？
4. 为什么“Sessions 与销量同期下降”不能直接写成“Sessions 下降导致销量下降”？面试官可能追问：怎样增强因果判断？
5. 为什么最终 JSON 不合法时只允许一次格式修正，并禁止继续调用 Tool？

## 参考答案

1. 模型会收到 Tool 的 name、description 和 JSON 参数 schema，可根据问题组合能力与参数。固定路由难以覆盖自然语言组合。应用层仍负责校验和执行，模型不能直接访问 Service。
2. Tool Input Schema 位于 LLM → Tool，校验单次工具调用输入；`AnalysisReport` 位于 Agent → 调用方，校验综合后的最终输出。
3. Service 计算可复现、可单测，并集中维护加权口径、空值和日期覆盖。LLM 推算容易产生算术错误并重复已有逻辑；它更适合选 Tool 和解释证据。
4. 同期变化只说明相关，可能存在季节、价格、渠道等混杂因素。可补充更细的来源与变更数据、对照组、时间序列控制，或设计 A/B 实验。
5. 一次修正能处理偶发格式错误；无限重试会浪费额度并可能死循环。此时证据已齐，再调 Tool 会改变任务内容和审计轨迹，所以直接拒绝。

## 我现在应该重点看哪些代码

1. `src/agent/runner.py` 的 `run_analysis()` 和 `_run()`：Multi-Tool、ToolMessage、成功 Tool 要求及格式修正。
2. `src/prompts/analysis.py`：模型怎样获得证据规则、schema 和因果边界，同时保持自主选 Tool。
3. `src/models/analysis_report.py`：最终结构契约及 Pydantic 失败路径。
4. `tests/test_analysis.py`：依次看同轮多 Tool、跨轮、SKU002、无数据、Tool 失败和格式修正。
5. `scripts/verify_analysis_live.py`：真实验收如何核对 Tool 事实与证据限制。

## Git 变化摘要

新增结构化输出模型、综合提示词、运行/验收脚本、Phase 5 测试和文档；最小扩展 `src/agent/runner.py` 与 `README.md`。没有修改 Mock Data、Service 或 Tool 的业务实现。

建议 Commit Message：`feat: add multi-tool structured product analysis`
