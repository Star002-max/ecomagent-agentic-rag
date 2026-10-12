# 简历与面试准备

## 简历项目描述

**EcomAgent｜LangChain + RAG 商品数据分析 Agent**

- 基于 LangChain 实现有界 Tool Calling Agent，连接商品、销售、库存、评价等 Pandas Service；工具 schema 校验输入并保留数据覆盖率与证据状态。
- 构建 Markdown → 分段 → Embedding → Chroma → Retriever → RAG Tool 链路；保留离线 LocalHash 基线，并支持百炼 `text-embedding-v4` 云端 Embedding。
- 设计最近4轮、仅保留完整 user/assistant 交互的会话 Memory；工具结果仍要求在当前轮重新查询，避免旧业务事实替代新证据。
- 使用固定 C07–C09 案例对照真实检索结果：LocalHash 平均 Recall@3 1.0、MRR 0.7778；百炼平均 Recall@3 1.0、MRR 1.0。C08 来源名次由第3升至第1，但 Top-3 仍不足以支持具体优先处理建议。
- 通过离线 Fake Model 和 Mock 覆盖 Agent、Memory、检索配置及结构化输出；真实 Embedding/RAG 检索已单独验收，完整 Qwen Chat Agent 云端问答链路未在该验收中验证。

简历数字应限定在固定三条评估查询，不表述为总体准确率或生产效果。所有项目业务数据为模拟数据。

## 1分钟项目介绍

我做了一个基于 LangChain 和 RAG 的商品数据分析 Agent。它把商品、销售、库存和评价查询封装成带参数 schema 的工具，底层仍由 Pandas Service 计算；运营规则通过 Markdown 知识库检索。RAG 默认使用离线 LocalHash，显式选择时可接入百炼 `text-embedding-v4`，两种向量使用不同维度和 Chroma collection。Agent 有界地执行工具调用，并支持最多4轮的会话内上下文；历史只辅助理解指代，当前业务数据每轮重新查工具。离线 Fake Model 和完整单元测试覆盖控制流，另外对 C07–C09 完成过真实云端 Embedding 检索对照。结果显示云端 MRR 更高，但 C08 仍缺乏足以支持具体行动建议的证据。我没有把检索验收说成完整 Qwen Agent 问答验收。

## 面试问题

### 1. 为什么项目同时保留 LocalHash 和云端 Embedding？

LocalHash 让开发和测试不依赖网络、密钥或费用，并提供固定离线基线；云端语义模型用于实际语义检索。Provider 明确切换，collection 按 provider 和维度隔离，避免把384维与1024维向量混在同一索引中。

### 2. 为什么有 Tool 之后还需要 RAG？

Tool 查询结构化业务 CSV，例如库存数量；RAG 查运营规则 Markdown，例如风险分级口径。两种来源回答不同问题。Agent 可在一个问题中调用两个工具，但应分别标注事实和规则依据。

### 3. Memory 保存什么，怎样避免旧信息误导？

只保留最多4轮成功完成的用户问题和最终回答，不存 Tool Call、ToolMessage、异常堆栈，也不持久化。Memory 用于解析“它”等指代；Agent 仍须在当前轮调用业务工具取最新数据。

### 4. C08 的 Recall@3 是1.0，为什么仍说证据不足？

Recall@3 衡量预期 source 是否出现在前三名，不判断片段能否支撑某个具体建议。C08 虽然命中库存规则文件，但 Top-3 片段不足以明确支持优先处理措施，因此来源检索指标与证据充分性分开报告。

### 5. 真实 Embedding 检索通过，是否代表 Agent 云端问答通过？

不是。该验收执行了 Embedding Provider → Chroma → Retriever 的固定检索对照，没有调用 Qwen Chat。完整问答还涉及模型对话、工具选择、证据整合和结构化输出，需要单独的授权与评估。

## 面试表达提醒

- 说明指标样本数为3，报告观察到的结果和局限，不把它包装成泛化结论。
- 清楚区分真实云端 Embedding 检索、Fake Model 离线控制流和真实 Chat 模型验收。
- 强调 CSV 业务计算留在 Service，RAG 提供规则文本，Agent 负责调度。
- 遇到“是否能证明业务因果”问题时，回答不能；项目输出相关线索和数据限制，不把相关性当因果。
