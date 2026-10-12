# Phase 9 阶段报告：项目展示与面试准备

## 目标与完成范围

Phase 9 的目标是让项目架构、可复现 Demo、检索验收边界和面试表达更容易理解。本阶段更新 README，新增架构图、完全离线 Agent Demo 指南及脚本、简历和面试材料。未新增业务功能、未引入 LangGraph、未改动业务 Service/Tool/Agent/RAG 核心实现，也未调用真实 Embedding 或 Qwen API。

Phase 8 的真实云端 Embedding/RAG 检索结果已先通过补充提交 `f099c04de5b0ef76588baaf2d079fd382a61fdc3` 单独记录；Phase 9 只在展示文档中链接并准确说明其范围，没有重复云端验收。

## 重要文件

- `README.md`：更新项目状态、145项离线测试基线、架构/离线 Demo/面试材料入口，说明 Demo 不调用 API。
- `docs/architecture.md`：Mermaid 架构图和组件职责、普通问答数据流、离线与云端验收边界。
- `scripts/demo_phase9.py`：脚本化 Fake Model 驱动实际 `ProductAgent`，调用真实本地库存 Tool 和 LocalHash/Chroma RAG，复用 Memory 演示连续两轮。
- `docs/offline_demo.md`：可复制运行命令、演示流程、Fake Model 和离线数据的准确边界。
- `docs/resume_and_interview.md`：简历项目要点、1分钟介绍、5道面试问题和参考答题内容。

## 执行流程与技术选择

离线 Demo 显式构造 `EmbeddingSettings(provider="local_hash")` 并注入 `LocalHashEmbeddings`，不读取 `.env` 或 `EMBEDDING_PROVIDER`；Fake Model 仅实现 `bind_tools`/`invoke` 接口，按固定脚本选择工具。工具和业务 Service 仍执行项目真实本地逻辑；知识工具使用本地 Markdown、LocalHash 向量及进程内 Chroma。两轮运行共用 `ConversationMemory`，第二轮仍重新查询当前库存，并另外检索库存规则。采用 Fake Model 的目的是不需要密钥、网络或费用即可稳定展示 Tool Calling 消息循环，不将它误称为模型效果测试。

## 验证结果

- `.venv/bin/python -m scripts.demo_phase9`：成功，完成两轮 Agent 调用；显示库存 Tool 返回和第二轮的 RAG 命中，并报告同一 Memory 保留两轮。
- `EMBEDDING_PROVIDER=aliyun .venv/bin/python -m scripts.demo_phase9`：成功。脚本仍显式注入 LocalHash，没有 Embedding 或 Chat 云端调用，验证环境中的云端 provider 变量不会改变 Demo 行为。
- `.venv/bin/python -m unittest discover -s tests`：**145项通过**。
- `.venv/bin/python -m scripts.check_secrets`：通过；`.env` 被忽略且未跟踪，87个可提交文件、Diff 和 index 未发现密钥。
- `git diff --check`：通过。
- 未调用真实 Embedding 或 Qwen Chat API；没有安装依赖。

## 问题记录与限制

本阶段没有遇到需要修复的 Bug 或设计问题。Demo 的 Fake Model 回答是固定说明文本，不会推断工具返回内容；展示的工具输出来自真实本地执行。示例 `days_of_supply` 在当前数据条件下为 `null`，脚本如实呈现，不能将此演示当作完整的自然语言问答质量验证。Phase 8 的真实检索结果仅来自固定 C07–C09 三条查询：云端 Mean Recall@3 为1.0、Mean MRR为1.0；LocalHash 分别为1.0和0.7778。C08 虽然来源排位提高到第1，Top-3 证据仍不足以支持明确的优先处理措施。完整 LLM Agent + Qwen Chat 云端问答链路仍未在这次检索验收中验证。

## 我现在应该重点看哪些代码

1. `src/agent/runner.py::ProductAgent._run`：理解消息组装、工具往返、有界循环和 Memory 写入时机。
2. `src/tools/factory.py::build_tools`：看业务工具如何委托给 Service，以及可选 RAG 工具如何接入。
3. `src/rag/knowledge_base.py::build_knowledge_base` 和 `KnowledgeBase.search`：看 Markdown/Embedding/Chroma/Retriever 的连接和 Provider 隔离。
4. `scripts/demo_phase9.py::DemoFakeModel`、`main`：对照真实 Agent 接口理解离线演示，不把 Fake 行为与真实 LLM 混淆。

## 理解与面试题

1. 为什么业务 CSV 查询和运营知识 RAG 分成两类工具？
2. 为什么 Phase 8 的真实 Embedding 检索成功不代表完整 Agent 云端问答成功？
3. `LocalHashEmbeddings` 和 `text-embedding-v4` 为什么不能共用同一个 Chroma collection？
4. Memory 如何帮助多轮对话而不让历史业务数据替代最新查询？
5. C08 的 Recall@3 为1.0，为什么仍保留证据不足限制？

### 【参考答案】

1. CSV 是结构化业务事实，交由确定性的 Pandas Service 查询；RAG 是非结构化运营规则的语义检索。职责分开后可追踪数据来源，也避免把文档检索当成实时库存数据。
2. Embedding 验收只覆盖向量生成、索引构建和 Retriever 排名，没有执行 Qwen Chat 的消息生成、工具选择与最终答案整合。
3. 两个 Provider 输出维度分别为384和1024，向量空间也不同；维度和 Provider 隔离能避免混合向量导致索引异常或错误距离比较。
4. Memory 只保留最近4轮已完成的用户问题和最终回答，用于解析指代；本轮业务事实仍需要当前 Tool 查询，失败轮次和工具消息不写入 Memory。
5. Recall@3 只统计目标来源是否出现在前三名，不判断片段是否含有具体可执行措施。C08 的来源命中成立，但支持具体行动的证据仍不足。

## Git 变化摘要

Phase 9 提交内容：更新 `README.md`，新增 `docs/architecture.md`、`docs/offline_demo.md`、`docs/resume_and_interview.md`、`docs/phase9_report.md` 和 `scripts/demo_phase9.py`。Phase 8 的补充提交与功能提交均保持原样。建议提交信息：`docs: add project architecture and offline demo guide`。

## 阶段边界

Phase 9 展示和学习材料已完成并按用户授权提交。没有开始新阶段；后续工作由用户发起全项目代码复盘和面试准备。
