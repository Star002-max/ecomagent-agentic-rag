# Phase 4 阶段报告

项目：EcomAgent，基于LangChain + RAG的智能商品数据分析Agent。

## 目标与实际完成

本阶段接入用户指定的真实模型qwen3.7-plus，使模型能够自行提出工具调用，由应用执行Phase 3工具并回传结果，最终生成基于商品数据的回答。基于Phase 3提交6a55137开展开发。

已实现真实模型适配、单问题Tool Calling Loop、基础查询提示词、命令行运行、离线测试、显式真实API验收，以及提交前密钥检查。只覆盖基础商品查询和两期比较；没有实现复杂多因素诊断、分析报告schema、RAG、Memory或Streamlit。

采用LangChain ChatOpenAI、AIMessage、ToolMessage和既有StructuredTool构建可读的Python循环。没有使用create_agent、AgentExecutor或LangGraph，也没有声称使用了这些未实现组件。此处的Agent行为来自模型按描述选择工具与循环执行，而不是程序按关键词固定路由。

## 配置与真实连接

真实API Key只保存在本地.env，文件权限为600，已被现有.gitignore排除，未加入Git。代码从.env或环境变量读取配置，环境变量优先；配置对象repr不显示密钥，.env.example仅包含占位示例。没有把密钥复制到报告、测试、Python源码或运行日志。

用户提供的HTTP地址首次返回308。检查Location后确认仅升级为同一主机、同一路径的HTTPS，没有改域名、模型或服务。按服务端要求使用HTTPS后，实际聊天请求返回HTTP 200，qwen3.7-plus回复“连接成功”。本地.env已保存该HTTPS地址。没有关闭证书验证。

模型请求timeout为60秒、SDK自动重试次数为0；发生鉴权、模型不存在、接口或网络错误时停止当前运行，不自动换模型或服务。使用Chat Completions兼容接口，显式关闭Responses API路由；未加入未经验证的供应商扩展参数。

## 重要新增及修改文件

| 文件 | 作用 |
|---|---|
| src/config.py | 读取.env与环境变量，检查必要配置和HTTPS地址，隐藏密钥repr |
| src/agent/model.py | 创建LangChain模型适配器；按HTTP状态与供应商错误信息生成脱敏异常 |
| src/agent/runner.py | 模型调用、工具分发、ToolMessage回传、次数上限与本次调用记录 |
| src/prompts/basic.py | 数据截止日、必须使用工具、指标口径、基础比较与因果表述边界 |
| scripts/run_agent.py | 命令行运行一个真实问题，可显示工具名、参数及状态 |
| scripts/verify_agent_live.py | 用户显式执行的四个真实集成验收，保存实际工具记录与答案 |
| scripts/check_secrets.py | 检查.env排除、可提交文件、工作区/暂存Diff及整个Git index |
| tests/test_agent.py | 新增25个离线协议、配置、限额及安全测试 |
| docs/phase4_live_results.json | 最新一次真实验收的工具调用、数据与模型答案，不含密钥或推理内容 |
| docs/phase4_report.md | 本阶段报告、实际问题、阅读顺序与参考答案 |
| .env.example、requirements.txt、README.md | 配置占位、固定新依赖、运行和阶段状态说明 |

src/agent与src/prompts中的__init__.py用于Python包标识。src/services、src/tools、原始数据及原有测试保持不变。本地.env属于忽略文件，不是交付给Git的源码。

## 核心执行流程

```text
读取本地配置 → CsvDataStore → build_tools
  → ChatOpenAI绑定五个公开工具定义
  → SystemMessage + HumanMessage
  → 模型返回AIMessage
      ├─ 有tool_calls：校验调用ID/数量 → 按名称执行注册工具
      │                  → Tool → Service → CSV计算结果
      │                  → 追加带tool_call_id的ToolMessage → 再请求模型
      └─ 没有tool_calls：提取可见答案，结束当前问题
```

模型看到Phase 3导出的工具定义，参数保留additionalProperties=false；数据对象、路径和密钥不作为工具参数。模型生成sku、日期等业务参数，程序不根据问题关键词指定工具，也不预先调用全部工具。

一次模型回复可以包含多个工具调用，程序按顺序执行并为每个调用返回对应ID的消息。这只是基础协议支持，不代表本阶段已经验收复杂诊断能力。

每次run重新创建消息列表，只有当前问题内的工具往返上下文。多次run不共享历史，所以不是Phase 8的会话Memory。可复用的数据快照也不是聊天记忆。

返回AgentResult包含status、answer、model_calls和tool_calls，这是程序执行记录，不是Phase 6的模型分析报告schema。不会打印模型reasoning_content或完整HTTP响应。

## 错误、上限及安全处理

- 默认最多6次模型请求、8次工具调用。超限返回limit_reached并标明未完成，不制造最终成功答案。
- 未注册工具名返回unknown_tool消息，模型可以在剩余额度内改选已注册工具。
- 参数schema或Service预期错误使用Phase 3错误返回，供模型修正；未预期的工具程序错误停止执行。
- 无法解析的tool call、缺失或重复调用ID、空答案、finish_reason=length截断都不当作成功完成。
- 模型请求异常只保留类型、HTTP状态和供应商错误code/message，先脱敏再对外展示，不直接打印请求、头部或原始异常栈。
- 真实配置密钥和常见密钥/Bearer形式均经过输出脱敏。工具记录和最终答案也做脱敏。
- 禁用本循环的外部LangSmith tracing，避免继承环境设置后意外上传调用内容；没有接入追踪服务。
- 密钥检查脚本仅打印失败文件名或检查项，不打印匹配文本。它检查当前可提交文件、两种Diff和index，不是通用历史秘密扫描器。

## 技术与原因

新增langchain-openai==1.6.5，用ChatOpenAI访问用户提供的兼容接口，不表示使用OpenAI模型。新增python-dotenv==1.2.3，将凭据读取与代码分离。依赖继续使用langchain-core==1.6.4，Pandas与Pydantic版本不变；没有安装LangGraph。

Python循环使模型消息、工具消息与停止条件清晰可见，符合当前学习阶段。dataclass只是保存配置和执行记录，unittest.mock用于离线模拟模型响应；真正的API验收单独执行，不把脚本模型的测试结果冒充真实调用。

## 实际遇到的问题

| 问题 | 原因 | 定位过程 | 解决方式 |
|---|---|---|---|
| 指定HTTP地址未直接返回聊天响应 | 服务端要求升级HTTPS，返回308 | 检查状态与Location，确认主机和路径一致 | 本地配置改用同一地址的HTTPS，实际请求200成功，未更换服务 |
| 周期比较数值正确但因果措辞过强 | 第一轮模型答案将转化变化称为“主要原因”，基础提示仍不够明确 | 人工阅读真实回答并对照数据；第一次补充约束后仍出现“导致订单”等变体，原来只匹配特定词组的检查漏过了它 | 再明确比较回答只列指标表、完整性和来源，不另写归因结论；扩大针对该问题的措辞检查，再做真实验收。仍不把简单关键词检查视为完整语义验证 |

开发中的首轮82个离线测试全部通过，没有虚构代码运行Bug。上述第二个问题说明“工具与数据检查通过”不等于自然语言表达已经完全符合要求；已保存的JSON为修正后的最新验收，不将第一轮结果隐藏成从未发生的问题。

## 测试与真实验收

独立.venv环境：Python 3.12.10。最终离线测试共82个全部通过，包含原有57个和新增25个。

新增覆盖：两轮实际工具执行与结果回传、同批多个工具、未知工具与参数错误纠正、无效工具JSON、缺失/重复调用ID、模型和工具上限、独立问题隔离、空回答、截断回答、HTTP错误和超时停止、答案与错误脱敏、隐藏推理字段、未预期工具异常、配置优先级、密钥repr、URL校验和模型工厂不重试。

真实模型使用qwen3.7-plus。连接检查返回HTTP 200；另外先跑通一条独立库存查询，再执行四例验收。提示词修正后重新执行四例，将最终记录写入phase4_live_results.json。

| 真实问题 | 模型实际选择工具 | 核对重点 |
|---|---|---|
| SKU003现在有多少库存 | get_inventory_data | 50件；估算可售约0.6488天；工具结果回传后生成回答 |
| SKU001最近30天销量、销售额与转化率 | get_sales_data | 2026-08-24至2026-09-22，1205件，48079.50元，转化率约5.9914% |
| SKU002最近30天与之前30天比较 | compare_sales_periods | 两个不重叠30天区间，件数2081→1245，区分相对变化与百分点 |
| 查询SKU999基本信息 | get_product_info | not_found，回答不存在，不编造商品 |

自动验收检查关键工具、日期和部分事实/措辞，不是完整语义验证。最终自然语言答案仍需人工复核；报告不承诺模型对所有未来提问都正确。实际工具调用次数和模型轮数以保存的JSON为准。

数据涉及访问、销售、库存、评价时已验证模型会调用工具。但程序仍允许不调用工具的澄清回答，目前没有逐句证据绑定机制，不能声称已经从系统层面完全消除幻觉。

## 如何运行

在项目根目录，使用已有.venv：

```bash
.venv/bin/python -m scripts.run_agent "SKU003现在有多少库存？" --show-tools
.venv/bin/python -m scripts.run_agent "比较SKU002最近30天和之前30天的销售表现。" --show-tools
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m scripts.check_secrets
```

前两条会调用真实API；测试和密钥检查不会请求模型。模型返回带事实的中文回答，show-tools显示实际工具名、参数、状态和模型轮数，不打印API Key。

需要重新做完整真实验收时显式执行：

```bash
.venv/bin/python -m scripts.verify_agent_live
```

此命令会产生真实API请求并覆盖本次验收JSON，遇到错误立即停止后续用例，不换模型。测试集依赖默认模拟数据日期与数值，修改数据后需同步调整验收期望。

其他电脑复制.env.example为.env后自行填入凭据；不要将.env上传或提交。在PyCharm选择本项目解释器，运行模块scripts.run_agent，工作目录为项目根目录，将问题和--show-tools作为参数。密钥不放运行命令参数中。

常见问题：配置缺失时补齐对应变量；401/403、模型不存在或接口错误按脱敏错误检查用户指定服务；limit_reached表示没有完成，不当作正常回答。没有自动重试、服务降级或隐藏失败。文件数据修改后需新建store，命令行每次运行自然会重新创建。

## 最值得亲自阅读的五处

1. scripts/run_agent.py::main：先看配置、模型、store、tools如何组装，不必立即深入异常分支。
2. src/agent/runner.py::ProductAgent.run：重点追踪messages中的AIMessage和ToolMessage，理解工具调用不是模型直接执行Python。
3. src/agent/model.py::create_model/safe_request_error：理解兼容接口、为何不自动重试或换服务，以及如何脱敏。
4. src/prompts/basic.py::system_prompt：理解数据截止日、必须使用工具、数据缺失与事实边界如何传给模型。
5. tests/test_agent.py::test_two_rounds_execute_real_tool_and_return_message_to_model：对照成功路径，再读未知工具修正与轮数上限两个测试。注意ScriptedModel仅用于离线测试。

## 理解题

1. 模型返回tool_calls后，是谁真正执行Python函数？为什么必须把ToolMessage再发送给模型？
2. tool_call_id有什么作用？同一回复要求两个工具时，应回传几条消息？
3. 单次run内保留多轮消息，为什么不算已经实现Memory？
4. 为什么需要模型轮数和工具调用次数两个上限？API自动重试与模型修正错误参数有什么区别？
5. 离线测试全部通过，为什么还需要真实API测试和人工阅读答案？面试官可能追问：这能否证明系统完全不会编造数据？

## 【参考答案】

1. 应用根据工具名找到已注册Tool并执行，Tool再调用Service。模型只提出调用请求；回传工具消息后，模型才能依据真实结果写答案，否则它并不知道函数返回了什么。
2. ID把工具结果与对应调用关联。同批两个调用应各有一条带对应ID的ToolMessage；缺失或重复ID会破坏关联，所以本实现停止执行。
3. 当前消息列表只存在于一个问题的执行过程，用于模型与工具往返。下一次run重新创建列表，没有跨问题保存历史，也不能将“它”解析成上一问题的商品。
4. 一次模型回复可能包含多个工具调用，只限制轮数不足以限制工具数量。API重试重复发送网络请求，本阶段禁用；参数纠正是模型看到明确工具错误后发起新的有效调用，受同一循环预算约束。
5. 脚本模型能检验程序协议，不能证明真实接口兼容或模型选工具正确；真实调用又不保证自然语言每一句都准确，所以还需人工核对。当前依靠工具证据、提示词及验收案例降低编造风险，没有完成形式化逐句证据校验，不能保证所有输入下都不幻觉。

## 当前限制与下一阶段

只有单问题基础查询和比较，没有持久会话、复杂多工具诊断、RAG或结构化分析报告。所有数据仍是模拟数据，价格固定，库存估算未考虑补货。工具返回可能较长，尚未做模型上下文预算管理。未知模型行为可能触发停止条件，模型描述也并非确定性安全规则。

Phase 5将在用户验收并明确要求后，开展复杂多Tool商品分析。本阶段不提前进行。后续Agent相关代码继续遵守不用LangGraph的边界。

## Git变化摘要与建议提交

新增配置模块、agent与prompts包、运行与真实验收脚本、密钥检查脚本、25个测试、阶段报告和脱敏真实验收记录。修改.env.example、requirements.txt、README.md。未改动Service、Tool、CSV和之前测试。

建议Commit Message：`feat: build qwen tool calling agent`。

真实.env保持未跟踪且被忽略。当前未执行暂存或Commit。提交前必须再次检查Git Status、Diff，并运行check_secrets；等待用户明确确认后才提交。

## 参考资料

- [LangChain ChatOpenAI参考](https://reference.langchain.com/python/langchain-openai/langchain_openai)：兼容接口、工具绑定与消息机制，具体行为以本项目版本和实测为准。
- [阿里云Function Calling说明](https://docs.modelstudio.console.alibabacloud.com/en/model-studio/qwen-function-calling)：模型提出工具请求、应用执行并回传结果。
