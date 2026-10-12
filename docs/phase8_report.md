# Phase 8 阶段报告：Embedding 对照与会话内 Memory

## 目标与完成范围

Phase 8 完成 Embedding provider 配置、LocalHash 与百炼 `text-embedding-v4` 的适配边界、固定检索评估，以及最多保留4轮的会话内 Memory。Step 1–6 的离线代码与验收已经完成。此前 Codex 运行环境中出现过 tokenizer 导入问题和一次 API 连接失败；之后用户在 Mac Terminal 使用项目虚拟环境和 `.env` 成功运行了完整 C07–C09 对照，本报告根据提交到项目中的真实结果文件更新最终云端验收结论。没有在本次文档更新中再次调用 API，也没有调用 Qwen Chat API。

## 重要文件与执行流程

- `src/config.py`：独立读取 `EMBEDDING_PROVIDER`、`EMBEDDING_API_KEY`、`EMBEDDING_BASE_URL`、`EMBEDDING_MODEL` 和 `EMBEDDING_DIMENSIONS`。默认 provider 为 `local_hash`。
- `src/rag/knowledge_base.py`：保留 384 维 `LocalHashEmbeddings`；显式 `aliyun` 时用已有 `langchain-openai` 的 `OpenAIEmbeddings` 配置北京 OpenAI-compatible endpoint、v4、1024维、20秒超时、0次 SDK 重试及每批10条。Provider、模型、维度和北京 URL 不一致时拒绝构建；不同 provider/维度使用不同的内存 Chroma collection。Embedding 异常会脱敏。
- `scripts/evaluate_retrieval.py`：读取 Phase 7 的 C07–C09 固定 query，记录 Top-3、Recall@3、MRR、宏平均以及两 provider 差值；C08 的证据充分性独立标为 `pending_manual_review`。默认只运行 LocalHash；只有显式指定 `--provider aliyun` 才会发真实请求。
- `src/agent/memory.py`：保存最多4轮完整 user/assistant 文本对，纯内存，不写磁盘。
- `src/agent/runner.py`：每轮输入按 System Prompt → 最近历史 → 当前问题组装；仅 `completed` 轮写入 Memory。Tool Call、ToolMessage 和结构修正过程仍只保留在单轮执行列表。
- `scripts/run_agent.py`、`scripts/run_analysis.py`：新增 `--interactive`，同一进程只创建一次 Agent/Memory，循环处理追问；单问题用法仍可用。
- `src/prompts/basic.py`：明确历史只用于上下文消歧；当前业务事实必须来自本轮 Tool 结果，历史数字不能代替查询。
- `tests/test_memory.py`、`tests/test_rag.py`、`tests/test_retrieval_evaluation.py`：覆盖会话行为、provider隔离、脱敏和评估指标。
- `README.md`、`.env.example`：记录交互入口、Embedding 配置及真实 API 调用边界。

数据流：交互入口创建单个 Memory 和 Agent → 每轮把最近最多4轮文本放在 System Prompt 与新问题之间 → Agent 继续走原有有界 Tool Calling Loop → Structured Output 仍按原 Pydantic 校验 → 仅成功完成后保存最终答案。工具证据、历史 Tool 往返和失败堆栈都不会写进 Memory。

## 验收结果

- 针对性测试：`.venv/bin/python -m unittest tests.test_memory tests.test_agent tests.test_analysis tests.test_rag tests.test_retrieval_evaluation`，**70项通过**。
- 本次 tokenizer 修复针对性测试：`.venv/bin/python -m unittest tests.test_rag`，**18项通过**；Fake OpenAI client 验证建索引和查询路径都发送原始字符串，未导入 `transformers`。
- 全量离线回归：`.venv/bin/python -m unittest discover -s tests`，**145项通过**。相关用例显式走 LocalHash 或 Fake/Mock，没有真实 API 请求。
- 默认本地检索评估实际执行成功：C07–C09 的平均 Recall@3 为 **1.0**，平均 MRR 为 **0.7778**。C08 的预期 source 排名第3，Recall@3 为1.0、MRR为0.3333；其证据充分性仍是待人工复核，source 命中不视为已能支持具体行动建议。
- 用户在 Mac Terminal 使用项目入口完成一次真实云端对照，结果记录在 `docs/phase8_retrieval_live_results.json`：LocalHash 384维与百炼 `text-embedding-v4` 1024维均完成 C07–C09（3/3），`stopped_on_error=false`。LocalHash Mean Recall@3 **1.0**、Mean MRR **0.7778**；百炼 Mean Recall@3 **1.0**、Mean MRR **1.0**。因此固定样例上的 Recall@3 差值为 **0**，MRR 差值为 **+0.2222**。
- 正确来源最佳排名：LocalHash 的 C07/C08/C09 为 **1/3/1**；百炼为 **1/1/1**。特别是 C08 从第3位升至第1位。三条固定查询只反映这组评估案例，不应外推为普遍质量保证。
- C08 证据充分性：云端 Top-3 命中正确的 `inventory_management.md` 来源，但返回片段包含使用限制与风险分级，仍未明确给出“优先处理什么”的具体行动依据。**来源命中已验证，支持具体处理建议的证据仍不足**；应在回答中保留这一限制。
- 本次云端运行由用户在 Mac Terminal 执行；本次 Codex 文档收尾没有重复调用云端 API。实际响应成功并完成三条检索案例，结果文件的 `stopped_on_error` 为 `false`。
- 本次真实验收配置校验通过：Provider=`aliyun`、模型=`text-embedding-v4`、维度=1024，北京兼容地址符合配置校验。固定数据共12个 chunk；按每批10条及3次查询估算上限为5次 Embedding HTTP 请求。云端评估器在首次本地 Embedding 准备阶段报错：`Embedding请求失败（ValueError）：Could not import transformers python package...`。实际发送 **0 次 HTTP 请求**，没有重试，也未执行云端 C07–C09 检索。脱敏后的结果保存在 `docs/phase8_retrieval_live_results.json`。
- 修复 tokenizer 后再次执行获授权的唯一一轮真实对照：配置校验通过，12个索引 chunk 预计最多2批，外加3次查询，上限5次。LocalHash C07–C09 全部完成；云端在索引阶段的首个 Embedding 客户端请求遇到脱敏错误 `Embedding请求失败（APIConnectionError）：Connection error.`。**客户端尝试1次请求；是否到达百炼服务端无法确认**，无自动重试，也未发送第二个索引批次或任何云端查询。结果记录在 `docs/phase8_retrieval_live_results.json`。
- 最后一次验收门槛检查：未发出 API 请求。Codex 沙箱内 Python 对同一 Host 的 DNS 解析失败，直连提供的 IP 到 TCP 443 返回 `Operation not permitted`；经批准的沙箱外诊断中 DNS 解析和 TCP 443 成功，但 TLS 证书验证报 `unable to get local issuer certificate`。当前无代理环境变量；OpenAI/HTTPX 默认信任环境变量并要求证书校验。由于沙箱网络和 TLS 条件仍不满足，按要求跳过最后一次云端评估。
- 本次 LocalHash Top-3 基线：C07/C08/C09 的预期来源名次为 **1/3/1**；Recall@3 均为 **1.0**，MRR 分别为 **1.0/0.3333/1.0**；宏平均 Recall@3 为 **1.0**，宏平均 MRR 为 **0.7778**。云端没有成功返回向量或 Top-3，无法计算云端指标和差值。
- C08 证据判断：LocalHash 命中预期库存来源（第3名），因此来源级 Recall@3 为1.0；但该片段只给出可售天数风险分级，没有说明应优先核对在途补货、到货时间或安排补货。**本次 LocalHash Top-3 证据不足以支持具体处理建议**。云端未得到结果，不能判断云端证据是否充分。
- `scripts.check_secrets`：通过；检查器已覆盖 Chat 与 Embedding 两类 Key，报告 `.env` 被忽略且未跟踪、82个可提交文件、Diff 和 index 未发现密钥。`git diff --check`：通过。工作区仍有 Phase 8 未提交改动。
- 真实百炼 Embedding：用户的 Mac Terminal 运行已成功返回1024维 Embedding，并完成项目内 Chroma → Retriever 的 C07–C09 检索对照。真实 Qwen Chat API：**未执行**。完整 LLM Agent → Tool Calling → Qwen Chat 的云端问答链路不属于本次验收范围，仍未验证。

## 技术选择、问题记录与限制

复用现有 LangChain `Embeddings` 接口及已安装的 `langchain-openai`，没有新增依赖。LocalHash 是默认且完全离线的实现，云端模式必须显式选择；API Key 单独配置，不复用 Chat Key。固定 Top-3、Recall@3 和 MRR 提供可复现的检索对照，不把三个固定案例解释成总体准确率。

发现并修复的问题：

1. 注入的 Embeddings 可能与 Settings provider/维度不一致，导致 collection 标签错误。通过显式类型/metadata 校验、维度核对及 provider/维度隔离 collection 修复；不匹配时明确拒绝。
2. Embedding 错误没有使用 Embedding 专用 Key 脱敏。扩展 `redact()` 支持多个 secret，并在 Embedding adapter 初始化和请求边界脱敏；评估报告只写错误类型，不保存异常正文。Fake 异常回归测试确认 Key 不出现在可见异常。
3. 原命令行入口一次只处理一个问题，无法实际复用 Memory。增加显式 `--interactive` 循环，由同一 Agent/Memory 处理多轮；原一次性运行仍兼容。
4. 实时评估原先会在单个云端检索错误后继续后续案例。加入仅对显式云端评估启用的首错停止，并在结果中记录脱敏错误；新增离线用例验证只尝试首个查询。首次真实尝试实际在该查询前因 tokenizer 导入失败而中止。
5. 本地 Embedding 实际验收尝试触发缺少的 `transformers`。锁定的 `langchain-openai==1.6.5` 在 `check_embedding_ctx_length=True` 时调用长度安全 tokenizer；当 `tiktoken_enabled=False` 时会导入 `transformers.AutoTokenizer` 并以 `text-embedding-v4` 为模型名加载。将兼容端点配置为发送原始文本（`check_embedding_ctx_length=False`），并在 `ProtectedEmbeddings` 增加 4096 UTF-8 字节/条的本地拒绝上限；不截断输入、不下载 tokenizer，也不假设 cl100k 与 v4 Tokenizer 一致。Mock 测试覆盖索引和查询两条路径，并确认没有导入 `transformers`、请求参数仍是字符串。官方兼容接口文档列明 v4 单行上限 8192 Token、每批最多10行；项目 `chunk_size=10` 负责每批文本数，不负责单条长度。字节上限属于保守输入护栏，不是精确 Token 映射。

限制：Memory 以轮数而非精确 Token 预算裁剪；长回答仍可能增加上下文长度。会话仅在当前进程存在，进程退出即清空。检索评估只有3个固定案例；C08 需要人工判断证据是否充分。tokenizer 依赖路径已通过 Mock 修复；此前云端首个请求尝试返回连接错误，服务端是否收到未知。最后一次验收因沙箱 DNS/TCP 限制及沙箱外 TLS 证书验证失败而跳过。4096 UTF-8 字节上限是保守护栏，不是 v4 精确 Token 计数。真实云端检索排名仍未验收；Qwen API 未验收。

## 我现在应该重点看哪些代码

1. `src/agent/memory.py`：看 Memory 的数据结构、4轮边界和只生成 user/assistant 消息的约束。
2. `src/agent/runner.py::ProductAgent._run`：看历史注入点，以及只在完成后提交 Memory 的位置；确认原 Tool Calling 和结构校验循环未被替换。
3. `scripts/run_agent.py` 与 `scripts/run_analysis.py`：看 `--interactive` 如何复用单个 Agent 和 Memory。
4. `src/rag/knowledge_base.py::create_embeddings`、`build_knowledge_base`：看 provider 配置、异常脱敏和 Chroma 维度隔离。
5. `scripts/evaluate_retrieval.py::evaluate_provider`：看 Recall@3/MRR 与 C08 人工证据复核如何分开记录。

## 理解与面试题

1. 为什么 Memory 只存完整 user/assistant 轮次，不保存 Tool Call 和 ToolMessage？
2. Agent 异常或达到调用上限时，为什么不能提交本轮到 Memory？
3. Recall@3 命中 C08 的预期文件，为什么仍不能判断证据足够？
4. 为什么 LocalHash 384维和云端 1024维要使用独立 collection？

### 【参考答案】

1. Tool Call/ToolMessage 属于一次执行协议和证据轨迹；复用它们容易形成不完整的调用链或把旧工具证据混入新轮。保留最终文本历史足以辅助指代理解。
2. 未完成轮次可能没有可靠最终答案；写入会让后续问题看到不完整或错误上下文。当前实现只在 `completed` 返回路径写入。
3. 文件级 source 命中只说明有相关文件的 chunk 出现在 Top-K，不能说明 chunk 含具体可执行措施。C08 需单独人工检查内容。
4. Chroma collection 中向量维数必须一致；分离 provider/维度可避免混用、错误检索或插入维度异常。

## Git 变化摘要

Phase 8 功能实现已由既有提交 `c26e800d0f4f60a55f411805be6352350ef64b82` 保存。本次补充提交只包含用户运行产生的真实检索结果 JSON 以及 README/本报告对最终结果的准确记录，不修改或回退既有 Phase 8 功能提交。建议补充提交信息：`docs: record live embedding retrieval validation`。

## 下一阶段边界

Embedding Provider → Chroma → Retriever 的离线/Mock 验收及一次真实百炼检索对照均已完成。真实云端检索在 C07–C09 上的排名和指标已记录；C08 的具体行动证据仍不足。完整 Qwen Chat/LLM Agent 云端问答链路未验证。Phase 8 范围到此结束。
