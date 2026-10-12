# Phase 7 阶段报告：Agent Evaluation Baseline

## 目标与边界

建立一个轻量、可重复、可解释的评估基线：用固定案例运行现有 Agent，核对工具选择、本地业务证据、RAG 来源、结构化输出和失败处理，并把机器可判定结果与人工复核分开。本阶段没有添加 Agent 能力，也没有修改稳定的 Service、Tools、Agent Loop、Structured Output 或 RAG 生产模块。继续使用 Qwen Chat Model 配置、`LocalHashEmbeddings`、内存 ChromaDB、CSV/Pandas 和现有循环限制。

## 新增与修改文件

- `evals/phase7_cases.json`：13 个固定用例 C01–C13；含问题、入口、必需/允许工具、适用指标、期望事实/来源，以及相互独立的事实复核和证据限制复核项。业务预期按当前 CSV Service 与知识文档核对。
- `scripts/evaluate_agent.py`：Offline/Live 执行器、独立编排的脚本 Fake Model、指标判定、每次工具调用的有界证据、RAG Top-3记录、案例/基线异常隔离、共享资源初始化错误分类、脱敏保存和资源测量。
- `tests/test_evaluation.py`：16 项 Phase 7 测试，覆盖固定案例、指标独立性、N/A、结构校验、可审计工具证据、证据大小上限、真实本地检索、脚本回答与当前证据一致性、案例和RAG故障隔离、共享资源初始化失败及Live案例白名单。
- `docs/phase7_offline_results.json`：本次 13 个 Offline 用例的工具轨迹、确定性证据、指标、RAG Top-3 和资源测量。
- `docs/phase7_live_results.json`：本次 Live 尝试的脱敏错误、未执行指标的 N/A 状态及停止记录。
- `docs/phase7_report.md`：本报告。
- `README.md`：加入 Phase 7 状态、评估命令和结果链接；更新测试数和提交前说明。

## 执行流程

`phase7_cases.json` → 按 `entrypoint` 调用当前 `ProductAgent` → 读取 `AgentResult` 中的工具轨迹、结构化结果及模型调用数 → 对工具响应信封和实际 RAG 命中做确定性检查 → 将自然语言事实与证据边界列为待人工复核 → 写入独立 Offline 或 Live JSON 结果。

Offline 使用脚本中按案例 ID 独立编排的 Fake Model 响应，不从 `required_tools` 推导工具计划。Agent 实际执行 CSV Service、LangChain Tools 和本地 `LocalHashEmbeddings` + 内存 ChromaDB。C13 单独使用故障注入 Retriever，其余检索案例均走真实本地 RAG。Live 复用既有 Qwen 工厂和 Agent 默认上限：每题最多 6 次模型调用、8 次 Tool 调用；仅放行 C06 和 C09，不自动重试。

## 指标定义与解释

结果指标提供 `numerator`、`denominator`、比率（适用时）、通过/失败案例数、待复核案例数和原因。`answer_fact_checks` 与 `evidence_limit_checks` 分别驱动答案事实和证据限制指标；空数组记为 N/A。N/A 不进入分母；待人工复核不被当作失败或通过。

| 指标 | 判定与分母 | 限制 |
|---|---|---|
| Required Tool Recall | 必需 Tool 名集合中实际出现的名称数 / 必需 Tool 名数；另记录实际调用轨迹 | 集合避免重复调用掩盖漏工具，重复次数另行保留 |
| Tool Selection Precision | 允许范围内的不同实际 Tool 名数 / 不同实际 Tool 名数；报告另记录总调用次数和额外调用数 | 这是工具种类选择指标，同一工具重复调用不会降低该比率；额外调用也不必然冗余 |
| RAG Source Hit Rate | Top-K Tool 返回来源中命中的预期来源数 / 预期来源数 | 来源命中不证明内容或最终答案正确 |
| Structured Output Validity | 通过现有 `AnalysisReport` Pydantic 校验的结果数 / 适用结果数 | Schema 有效不代表事实正确 |
| Tool Evidence Check | 满足预期事实断言数 / 预期事实断言数；核对真实 Tool 响应路径和值（支持数值容差） | 只验证列出的确定性断言，不替代完整业务复核 |
| Answer Fact Review | 逐项使用 `answer_fact_checks` 检查 Agent 回答与实际 Tool 证据的一致性 | 结果初始为 `pending_manual_review`，不会用字符串匹配冒充判断 |
| Evidence Limit Compliance | 独立使用 `evidence_limit_checks` 检查估算、数据覆盖和相关性/因果边界 | 语义判断保留人工复核，不自动计分；无检查时为 N/A |
| Failure Handling | 自动核对预期状态及错误码；再对说明和不伪造成功的回答做人工复核 | 本地工具错误可自动核对；API 不可用时相关 Agent 指标为 N/A |

## Offline Evaluation 结果

命令：`.venv/bin/python -m scripts.evaluate_agent --mode offline`

13/13 案例均由 Fake Model 完成 Agent 协议运行，0 个评估执行错误，0 个循环上限退出。该数量表示脚本执行成功，不是 Agent 回答正确率。

| 自动指标 | 结果 | 说明 |
|---|---:|---|
| Required Tool Recall | 15/15 = 100% | 所有用例需要的不同 Tool 名均被脚本计划调用 |
| Tool Selection Precision | 15/15 = 100% | 所有被调用的不同 Tool 名均在用例允许范围内 |
| RAG Source Hit Rate | 3/3 = 100% | C07、C08、C09 命中预期 `inventory_management.md` |
| Structured Output Validity | 4/4 = 100% | 4 个适用结构化回答均通过 `AnalysisReport` |
| Tool Evidence Check | 27/27 = 100% | 9 个案例中的 27 条列明事实均与实际 Tool 响应一致 |
| Failure Handling 自动状态/错误码 | 4/4 = 100% | C10 `not_found`、C11 `partial`、C12 参数错误、C13 检索错误均符合预期；8项回答检查在自动 JSON 中仍为 pending，人工建议另见下文 |
| Answer Fact Review | 13 个案例待复核，共 13 项 | 不是机器通过率；需人工核对最终答案与工具证据 |
| Evidence Limit Compliance | 6 个案例待复核，共 6 项 | 估算限制、数据不足及因果边界需要人读回答确认 |

案例执行摘要：

| 案例 | Agent工具轨迹 / 状态 | 自动核对 |
|---|---|---|
| C01 | `get_product_info` / ok | 商品名、价格和评分事实通过 |
| C02 | `get_inventory_data` / ok | 库存 50、估算可售 0.6488 天通过 |
| C03 | `compare_sales_periods` / ok | 销量、Sessions、Conversion百分点变化通过 |
| C04 | `compare_sales_periods` / ok | Sessions 和 Conversion 两期值通过 |
| C05 | `get_review_data` / ok | 均分、低分数、评分变化通过 |
| C06 | `compare_sales_periods` + `get_review_data` / ok | 销售两期销量、Sessions与评价证据通过 |
| C07 | `search_operation_knowledge` / ok | 预期来源命中 |
| C08 | `search_operation_knowledge` / ok | 预期来源在 Top-3 第 3 位命中 |
| C09 | `get_inventory_data` + `search_operation_knowledge` / ok | 库存事实及预期来源通过 |
| C10 | `get_product_info` / not_found | 未知 SKU 状态通过，答案仍待复核 |
| C11 | `get_sales_data` / partial | observed 1 / expected 2 天通过 |
| C12 | `get_inventory_data` / error | `invalid_arguments` 错误码通过 |
| C13 | `search_operation_knowledge` / error | 注入失败返回 `retrieval_error`，未中断其他用例 |

Fake Model 只证明固定输入下的 Agent 消息协议、Tool 执行和评估器逻辑；不能说明 Qwen 会选择同样的工具，也不代表真实模型准确率。

## Fake Model 回答人工复核（与自动指标分开）

以下复核仅针对脚本化 Fake Model 的固定回答，以及本次 Offline 结果文件所保留的真实本地 Tool 返回值。它不是 Qwen 回答质量评估。自动结果 JSON 中 `answer_fact_review`、`evidence_limit_compliance` 和失败场景的回答检查仍标为 `pending_manual_review`；下表是单独记录的人工复核建议，不回写或冒充自动 PASS。

本轮建议结果：答案事实 **13/13 PASS**；证据边界 **6/6 PASS**；失败场景回答 **8/8 PASS**。C08 的 PASS 仅表示它忠实承认本轮检索证据不足，没有满足用户意图所需的具体操作建议；该限制已在答案中披露，并不是 RAG 已成功回答该问题。

### 13 项答案事实

| Case | 实际 Tool 证据摘要 | Fake Model 最终回答要点 | 人工判断与依据 |
|---|---|---|---|
| C01 | 商品 Tool：桌面收纳盒，¥39.9，评分4.5833；当前商品快照 | 商品名、价格、评分与 Tool 相同 | **PASS**：数值一致，未超出快照口径 |
| C02 | 库存 Tool：50件、历史均销77.0667件/日、估算0.6488天 | 50件、约0.65天，并说明历史静态估算限制 | **PASS**：数量及四舍五入结果正确 |
| C03 | 两期销量1833→1205、Sessions 28021→18226、转化率5.96695%→5.99144% | 指出销量和 Sessions 同期下降、转化稳定；risk_level=`unknown` | **PASS**：指标和边界正确；项目没有统一商品风险分级规则，`unknown` 比编造 medium 等级稳妥 |
| C04 | Sessions 29038→29018；转化率6.5018%→3.9079% | 指出访问稳定、转化下降，原因无法证明；risk_level=`unknown` | **PASS**：数值、趋势和原因边界正确；没有虚构综合风险规则 |
| C05 | 评价 Tool：均分2.1、低分47条，前期均分4.6833，变化-2.5833；完整性未知 | 报均分2.1、低分47、下降约2.58 | **PASS**：数值正确，未声称已有评价记录覆盖完整总体 |
| C06 | 销量2130→1276；Sessions变化+0.056%；均分2.1、低分47；同期本身不证明因果 | 描述同期恶化、Sessions近乎持平，建议核查低分；risk_level=`unknown` | **PASS**：事实和建议有 Tool 依据，明确否认已证明因果；风险标签不再声称有统一分级 |
| C07 | RAG `inventory_management.md` 风险分级片段：<7天高、7–14天中、>14天低；库存0为缺货高风险 | 逐项给出以上阈值 | **PASS**：阈值与实际检索片段一致，回答了所问规则 |
| C08 | 本轮 Top-3 为综合分析 SOP、销售指标解释、库存风险分级；没有具体处理建议片段 | 明确本次片段没有具体处理建议，因此不能据此判断优先措施 | **PASS（带限制）**：没有把未检索到的规则写成建议；诚实说明证据不足。语义改写的检索相关性仍较弱，来源命中不代表回答已能提供具体操作 |
| C09 | 库存 Tool：50件、估算0.6488天；RAG：<7天高风险，核对在途补货/预计到货并结合近期销量安排补货 | 报库存、约0.65天、高风险和该建议，并说明估算不考虑在途及需求变化 | **PASS**：数字、阈值、建议均可追溯至本轮实际工具返回；静态估算限制已明确 |
| C10 | 商品 Tool 返回`not_found`、`product=null` | 说明不存在、risk_level=`unknown`、无指标可分析 | **PASS**：未伪造数据，未知状态正确 |
| C11 | 销售 Tool 返回`partial`，覆盖1/2天，缺少2026-09-23，缺失日未补零 | 说明只覆盖1天，不能视为完整两天 | **PASS**：与实际覆盖及缺失处理一致 |
| C12 | 库存 Tool 因空参数返回`error / invalid_arguments`，无数据 | 说明参数不完整、未取得库存数据 | **PASS**：未声称查询成功或编造库存 |
| C13 | RAG Tool 返回`error / retrieval_error`，无片段 | 说明检索失败、无法引用内部规则 | **PASS**：未伪造检索成功或规则结论 |

### 6 项证据边界

| Case | Tool 限制证据 | 最终回答对应说明 | 人工判断 |
|---|---|---|---|
| C02 | 可售天数是假设未来销量等于历史日均销量的静态估算；不含在途补货、需求变化 | 明确称历史日均销量静态估算、假设未来销量相同、不考虑在途补货或需求变化，且不是需求预测 | **PASS** |
| C03 | 两期指标只显示同期变化，未提供外部原因 | 明确说同期变化不能证明外部原因 | **PASS** |
| C04 | Tool 无页面、价格等原因证据 | 明确说现有数据无法证明转化下降原因 | **PASS** |
| C05 | Tool 明确不能据现有评价记录证明采集完整 | 回答只描述已有评价统计，未推断完整总体 | **PASS** |
| C06 | 销售和评价同期变化不证明销量下降由评价造成 | 回答明确写出不能证明该因果 | **PASS** |
| C09 | 可售天数是历史静态估算，不含在途补货和需求变化 | 回答明确披露假设及两项排除因素 | **PASS** |

### 8 项失败场景最终回答检查

| Case | 检查 | Tool 原始状态/数据 | 最终回答与判断 |
|---|---|---|---|
| C10 | 说明 SKU 不存在、风险 unknown、不编造指标 | `not_found`，`product=null` | 回答明确无 SKU 数据并使用 unknown；**PASS** |
| C10 | 无商品数据时不对表现下结论 | 同上 | 回答说无法分析表现；**PASS** |
| C11 | 说明覆盖1/2天 | `partial`，observed=1、expected=2 | 回答说明只覆盖1天；**PASS** |
| C11 | 不补零、不称完整周期 | 缺失日2026-09-23，Tool 说明未补零 | 回答称不能视为完整两天；**PASS** |
| C12 | 说明参数错误，不伪称查询成功或编造数量 | `error / invalid_arguments`，无数据 | 回答说明参数不完整且未取得数据；**PASS** |
| C12 | 没有库存数据时不下数量结论 | 同上 | 回答没有给出库存数量；**PASS** |
| C13 | 说明检索失败，不伪称取得知识 | `error / retrieval_error`，无结果 | 回答明确说明检索失败；**PASS** |
| C13 | 无检索证据时不把建议称作内部规则结论 | 同上 | 回答没有给出或归因内部规则建议；**PASS** |

这些人工 PASS 只表示当前固定脚本回答在本次保存的证据下符合对应检查。它们不是 Agent 的自动测得通过率，也不构成 Qwen Live 验收。

## Live Qwen Evaluation 结果

命令：`.venv/bin/python -m scripts.evaluate_agent --mode live`。脚本限定 C06、C09，实际先尝试 C06。首次模型请求返回脱敏错误 `OpenAIConnectionError`（连接失败）。按验收规则没有重试、没有切换模型或服务；C09 因连接错误后的停止规则未请求。

- 实际模型请求尝试：1 次；成功完成 Agent 回合：0 次。
- 已执行 Tool：0 次；没有可评估的 Qwen Tool Selection、结构化输出或回答。
- C06 所有依赖模型运行结果的指标记为 N/A，不把网络错误算成模型能力失败。
- C09：未尝试。
- 因 Live 没有完成样本，不能报告“2/2通过”，也没有真实模型样本通过率。

本次修复没有再次请求 Live API；连接恢复后如需 Live 验收，应由用户明确要求重新执行。此前的连接失败记录保留，不能据此判断 Qwen 的工具选择或回答表现。

## RAG Top-3 基线

使用现有 `LocalHashEmbeddings` 与内存 ChromaDB，对评估集的固定检索 query 真实运行；没有 similarity score，因此不记录虚构分数。完整内容、source、section、chunk ID、排名及预期来源命中标记保存在 Offline JSON。

| 案例 | 固定检索词 | Top-3 来源顺序 | 命中预期来源 |
|---|---|---|---|
| C07 | 可售天数库存风险分级 | `inventory_management.md`（风险分级）；`inventory_management.md`（使用限制）；`product_analysis_sop.md`（综合判断） | 是，第 1 位 |
| C08 | 余量按最近销售速度只能卖几天应该优先处理什么 | `product_analysis_sop.md`（综合判断）；`sales_analysis_rules.md`（指标解释）；`inventory_management.md`（风险分级） | 是，第 3 位 |
| C09 | 库存风险分级和补货建议 | `inventory_management.md`（风险分级）；`inventory_management.md`（处理建议）；`product_analysis_sop.md`（输出要求） | 是，第 1 位 |

此结果是当前 Embedding/知识文档/切分和查询组合的固定基线。C08 的正确来源只出现在 Top-3 第三位，后续 Phase 8 应用相同案例对照新旧排序；不能把来源命中直接等同语义理解或回答正确。

## 测试结果

- Phase 7 针对性测试：16 项通过。
- 全量离线测试：123 项通过（包括 Phase 1–6 回归测试）；使用项目现有 unittest，不新增依赖。
- 13 案例 Offline Evaluation：13 个 Agent 执行完成，全部确定性业务事实、结构字段、来源和注入失败状态均按记录评估。
- Live：因首次请求连接失败，0 个案例完成；一次请求尝试后停止。
- `.env` 被 Git 忽略；项目 `check_secrets` 和新增 Phase 7 文件脱敏扫描均通过；`git diff --check` 通过。最终未提交的变更仅为本报告列出的 Phase 7 文件与 README。

## 本机资源测量

来自脚本本次实际记录，不是估算：

- Offline（本轮修复后的最终运行）：墙钟 0.1191 秒；当前进程 CPU 0.1191 秒；进程生命周期峰值 RSS 182,550,528 字节（约 174.1 MiB）。
- Live 连接失败运行：墙钟 0.3349 秒；当前进程 CPU 0.1543 秒；进程生命周期峰值 RSS 188,416,000 字节（约 179.7 MiB）。
- RSS 包含 Python、依赖导入及本次进程所有工作，不能解释为 Phase 7 增量内存；未下载模型、未启动持久服务或持久化 Chroma 数据库。

## 实际遇到的问题及处理

1. **Fake响应构造读取了不存在的检索字段 →** 响应表在 Python 初始化时会先构造所有案例的列表，即使当前案例不是 C08/C09；普通案例没有 `rag_query` → 首次 Offline 运行在 Fake fixture 处报 `KeyError` → 将 Fake 调用计划改为独立固定文本，避免从案例必需工具推导响应。
2. **事实预期路径与 Service 返回结构不一致 →** SKU001 的 Conversion 百分点差位于比较结果顶层，不在 `changes` 子对象 → Offline 事实核对显示该字段 missing；查阅 Phase 2 Service 输出确认路径 → 修正固定案例 JSON 路径为 `data.conversion_rate_percentage_point_change`。
3. **失败返回的 `data` / `error` 可以是 null →** C13 注入 Retriever 后 Tool 的稳定 envelope 中 `data` 为 null → 首轮评估在压缩工具轨迹时对 null 调用 `.get()` → 对可空 envelope 字段使用空对象回退，并为 API 层连接失败定义 N/A 评估，避免将基础设施故障记为 Agent 能力失败。
4. **Live API 连接失败 →** 本次 C06 首次请求返回 `OpenAIConnectionError` → 从脱敏结果文件确认失败类型，没有打印 Key → 脚本停止、不重试、不切换服务，C09 未请求并在报告标明。
5. **人工检查类别互相复用 →** 两个指标读取同一 `review_checks`，把事实一致性同时计入证据限制 → 对照 C01–C13 检查内容后发现分类和计数重叠 → 拆为 `answer_fact_checks`、`evidence_limit_checks`，增加相互独立和空检查 N/A 测试。
6. **人工复核缺少业务 Tool 返回值 →** 结果压缩时只留下业务 Tool 的状态，C01评分、C06上期销量等没有作为断言保留 → 逐例对照回答和 expected facts 发现不能仅凭结果文件审计 → 每次调用保存实际业务数据或RAG片段，单个数据对象最多5000字符；超限时标明截断并只留有限预览，同时补充 C01 评分、C06 上期销量的断言。
7. **单例准备异常可中断全量 Offline →** Fake响应、Tool和Agent在 try 外创建，RAG基线也未隔离 → 故障边界检查并通过注入测试验证 → 把每例准备及执行纳入独立保护，按例记录 ERROR 后继续；基线逐 query 隔离；共享 CSV/RAG 初始化失败则作为独立的全局错误报告。
8. **Fake回答未充分遵循案例证据 →** 人工复核发现 C07 未复述阈值、C08 使用未在本轮检索结果中的建议、C09 遗漏处理建议和估算限制，且 C02 未写估算限制、C03/C04/C06 使用无统一口径的风险等级 → 对照每条保存的 Tool 返回值及现有风险 Schema → 只调整脚本 Fake 回答：C07 引用实际阈值；C08 对未检索到具体建议时明确证据不足，不硬编码其他片段；C09/C02 补充有来源的建议与估算限制；C03/C04/C06 改用 Schema 已允许的 `unknown`。新增测试约束这些回答和实际返回证据一致，未改案例事实或检查标准。

## 限制与下一阶段边界

- 评估集覆盖的是固定的模拟数据问题；13 个样本不足以推断面向真实业务的总体准确率。
- Fake 模型脚本化指定响应，不能检验 Qwen 的自主选择质量；自然语言结论及证据边界仍需人工审查。
- RAG Top-3 当前只有来源记录，没有相似度数值；本 Phase 不改 Embedding。
- Live 因网络连接问题未得到有效 Qwen 样本。
- 下一 Phase 边界：Phase 8 才分别规划 Semantic Embedding Upgrade 与 Simple Memory。本阶段不开发 Memory、不替换 Embedding，也不进入 Phase 9。

## 我现在应该重点看哪些代码

1. `evals/phase7_cases.json`：先理解一个固定案例如何表达入口、必需/允许工具、事实断言、RAG 来源和人工检查项。
2. `scripts/evaluate_agent.py::_fake_responses` 与 `run_offline`：看 Fake Tool Calling 计划如何独立于预期定义，并实际经过现有 Agent、本地 Service/Tools/RAG。
3. `scripts/evaluate_agent.py::evaluate_case` 与 `aggregate_metrics`：看每项指标如何区分分子、分母、N/A、失败和待人工复核。
4. `scripts/evaluate_agent.py::_rag_baseline`：看相同固定 query 如何记录真实 Top-3 来源并用于 Phase 8 对照。
5. `tests/test_evaluation.py`：看评估边界测试如何验证工具证据来源、故障隔离、人工指标不误计以及真实检索结果。

## 理解与面试题

1. Offline 的 Required Tool Recall 100% 能否说明 Qwen 的工具选择准确率是 100%？
2. 为什么 Tool Evidence Check 读取 AgentResult 中的 Tool 响应，而不是在最终答案里搜索“50”或“0.65”？
3. C08 的预期来源只排在 Top-3 第三位，Phase 8 为什么要复用同一问题和知识库记录？
4. API 连接错误时为什么将业务事实与 Tool 选择指标标为 N/A，而不是 Failed？
5. Required Tool Recall 使用名称集合时，如何避免重复调用造成信息丢失？

### 【参考答案】

1. 不能。离线 Agent 使用预先脚本化的 Fake Model；100%只说明这些脚本计划覆盖了预期 Tool。真实模型决策需要 Live 样本验证，而且样本通过也不是整体准确率。
2. 最终答案是模型生成文本，可能漏写、写错或编造。核对 Tool 原始结果可以验证数据源本身是否正确；最终答案是否忠实使用这些结果另由人工复核。
3. 固定 query 和 Top-3 可让 Phase 8 比较 Embedding 改动前后的检索来源、排名及命中变化，减少问题变化带来的混杂因素。命中仍不等同于内容理解正确。
4. 请求没有得到模型输出，Agent 没机会选择工具或生成结论；把不可观测的能力记为失败会混淆系统连接与模型行为。连接错误单独记录，相关指标 N/A。
5. Recall 按必需工具名集合计算覆盖率，同时轨迹仍逐条保留调用；重复调用不会扩大分子，但可以单独统计或人工发现。

## Git 变化摘要

本 Phase 只新增评估数据、脚本、测试和结果报告，更新 README；没有修改既有 Service、Tool、Agent、Prompt、Embedding 或 Memory 生产代码。修复后 Git Status 以交付摘要为准。本阶段不提交。

建议 Commit Message：`feat: add agent evaluation baseline`
