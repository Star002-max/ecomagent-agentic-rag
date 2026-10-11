# Phase 6 阶段报告：RAG Knowledge Base

## Phase 目标

为 EcomAgent 增加一个本地运营知识库，使模型能自主检索销售、库存、评价规则和综合分析 SOP，并与现有 CSV 业务 Tool 组合。业务数字仍由 Pandas Service 计算；RAG 只返回非结构化知识片段；LLM 负责选 Tool 和综合证据。

## 实际完成内容

- 新增四份小型 Markdown 知识文档，分别覆盖销售规则、库存规则、评价规则和综合分析 SOP。
- 实现 Markdown 加载、按标题与字符长度切分、本地 Embedding、ChromaDB 向量存储和 Retriever。
- 新增 `search_operation_knowledge` StructuredTool，返回知识片段及 `source`、标题、章节、chunk ID。
- `build_tools()` 通过可选依赖注入添加 RAG Tool；原有五个业务 Tool 和 Service 计算没有复制或改写。
- `run_agent` 和 `run_analysis` 初始化知识库并把六个 Tool 交给现有 Phase 4/5 Agent Loop。
- 新增离线测试和一个真实 Qwen 综合验收。

## 重要新增/修改文件

- `knowledge/product_analysis_sop.md`：综合分析证据顺序、输出结构和证据限制。
- `knowledge/sales_analysis_rules.md`：期间比较、指标解释及因果边界。
- `knowledge/inventory_management.md`：可售天数风险阈值、补货建议和限制。
- `knowledge/review_management.md`：评分、低分评价及处理规则。
- `src/rag/knowledge_base.py`：RAG Pipeline、Embedding、Chroma和Retriever的集中实现。
- `src/tools/schemas.py`：RAG Tool 的 `query`、`k` 输入 schema。
- `src/tools/factory.py`：创建 RAG Tool，并在传入知识检索器时注册为第六个 Tool。
- `src/prompts/basic.py`、`src/prompts/analysis.py`：规定知识建议必须来自本次 RAG Tool 结果并标注 source。
- `scripts/run_agent.py`、`scripts/run_analysis.py`：生产入口初始化本地知识库。
- `scripts/verify_rag_live.py`：一个真实综合问题的验收脚本。
- `tests/test_rag.py`：10 个 Phase 6 离线测试。
- `requirements.txt`：固定 Chroma 和文本切分依赖版本。

## RAG Pipeline 的实际实现

```text
knowledge/*.md
  → load_markdown_documents：读取为 LangChain Document，保存文件名 source
  → MarkdownHeaderTextSplitter：按 # / ## 标题保留主题元数据
  → RecursiveCharacterTextSplitter：长章节限制为 420 字符，重叠 60 字符
  → LocalHashEmbeddings：中文字符 1/2/3-gram 转 384 维归一化向量
  → Chroma.from_documents：建立内存向量集合
  → as_retriever(k=3) / similarity_search
  → 返回 content、source、title、section、chunk_id
```

当前四份文档被切成 12 个知识片段。标题优先切分让每个 chunk 保留清晰主题；字符长度切分只处理过长章节。

## 使用的 Embedding

本阶段使用 `LocalHashEmbeddings`，实现 LangChain `Embeddings` 接口。它把标准化文本转换成中文字符 unigram、bigram、trigram，再用稳定哈希投影到 384 维并归一化。

选择原因：知识库很小、主题边界明确；方案无需下载大型模型、不新增密钥、不消耗 Embedding API，离线测试和不同机器运行都可复现，也兼容 LangChain/Chroma 的 Embeddings 接口。当前 Qwen Chat Model 完全没有更换。

这是一种教学型检索基线，不等同于理解语义的生产 Embedding。知识量增大、同义表达变多时，应换成经过验证的中文语义 Embedding；接口边界无需改变。

## ChromaDB 在哪里初始化和使用

`build_knowledge_base()` 是统一组合入口：加载和切分文档后创建 `KnowledgeBase`。`KnowledgeBase.__init__()` 使用 `Chroma.from_documents()` 初始化内存 collection `ecomagent_operations`，随后创建 `retriever`。本阶段知识很少且可快速重建，因此没有生成或提交持久化数据库目录。

`KnowledgeBase.search()` 使用 Chroma `similarity_search(query, k)`，默认返回 3 个、最多 5 个 chunk。Retriever 测试也直接调用 `knowledge_base.retriever.invoke()`，确认库存问题优先返回 `inventory_management.md`。

## RAG Tool 如何接入 Agent

`search_operation_knowledge` 的输入只有自然语言 `query` 和结果数 `k`。Tool description 明确说明它检索运营规则、不查询 CSV、不计算 SKU 指标、不完成最终分析。`build_tools(store, knowledge_searcher)` 把它与五个业务 Tool 一起交给现有 `ProductAgent`；LLM 根据 Tool name、description 和 schema 自主选择，没有关键词 `if/else` 路由。

Tool 统一返回 Phase 3 的 JSON envelope。检索异常被转换成 `retrieval_error` ToolMessage，Agent 可以基于其他证据继续回答并说明限制，异常内部文本不会泄露给模型。

## 综合问题如何使用业务 Tool + RAG Tool

真实问题“分析 SKU003 当前库存风险，并根据我们的库存管理规则给出建议”中，Qwen 在同一轮自主调用：

1. `get_inventory_data(sku=SKU003)`：得到当前库存 50 件、日均销量约 77.07 件、估算可售约 0.65 天及数据限制。
2. `search_operation_knowledge(query=库存风险分级和补货建议, k=3)`：得到小于 7 天为高风险、核对在途补货等规则，来源为 `inventory_management.md`。

两个 ToolMessage 回传后，Qwen 判定高风险，给出补货建议并引用知识来源，同时保留历史销量估算不包含在途补货和未来需求的限制。业务数字来自 Service，风险阈值和建议来自 RAG。

## 新技术及为什么使用

- `langchain-text-splitters`：把 Markdown 章节切成适合检索的小块，并保留标题上下文。
- `langchain-chroma` / `chromadb`：存储向量和元数据，提供相似度检索及 Retriever 接口。
- LangChain `Embeddings` 接口：把当前本地方案与向量库解耦，后续可替换语义模型而不改变 Tool 和 Agent。

## 实际遇到的问题 → 原因 → 定位 → 解决

**问题：第一轮 RAG Tool/Agent 针对性测试有 5 个 `NameError`。**

- 原因：新增 RAG Tool 使用了统一的 `result_json()`，但 `src/tools/factory.py` 漏掉对应 import。
- 定位：文档加载、切分和 Retriever 测试先通过；所有失败都在 RAG Tool 执行位置，堆栈指向 `return result_json(...)`，因此不是 Chroma 或 Agent Loop 问题。
- 解决：从现有 `src.tools.results` 显式导入 `result_json`。没有修改业务计算或放宽测试。修正后 10 个针对性测试全部通过。

## 测试结果

- Targeted tests：`tests.test_rag` 共 10 个，全部通过。
- Full offline tests：共 107 个，全部通过；Phase 1–5 无回归。
- 依赖检查：`pip check` 通过，没有损坏的依赖关系。
- Real API acceptance：只执行 1 个综合问题，成功；2 次 Qwen 模型请求、2 次 Tool 调用，分别是库存 Tool 和 RAG Tool。
- 真实验收记录：`docs/phase6_live_results.json`，不包含 API Key。

## 当前限制

- LocalHashEmbeddings 主要依赖字符重叠，对复杂同义词和长文语义的召回能力有限。
- Chroma 使用内存 collection，每次进程启动重新索引；适合当前 12 个 chunk，不适合大型知识库。
- 知识规则是项目内静态 Markdown，没有文档版本审批、增量索引或权限控制。
- Retriever 使用简单 top-k 相似度，没有 reranker、混合检索或检索质量评测集。
- 没有跨问题 Memory、Streamlit、LangGraph、MCP 或其他 Phase 7+ 功能。

## 下一 Phase 边界

Phase 6 到此停止。不会自动开发 Phase 7 Memory；下一阶段内容等待用户明确指定。

## 理解/面试题

1. RAG 中 Document、Chunk、Embedding、Vector Store、Retriever 分别负责什么？
2. 为什么 RAG Tool 不应该直接读取 CSV 或计算可售天数？
3. `search_operation_knowledge` 的 input schema 与返回 metadata 对 Agent 有什么帮助？
4. 为什么真实综合问题需要同时调用库存 Tool 和 RAG Tool？只调用其中一个会缺少什么？
5. LocalHashEmbeddings 的优点和限制是什么？如果替换为语义 Embedding，哪些代码可以保持不变？

## 参考答案

1. Document 表示原始知识及元数据；Chunk 是可检索的小段；Embedding 把文本转成向量；Vector Store 保存向量并比较相似度；Retriever 接收问题并返回相关 Chunk。
2. CSV 计算属于确定性的 Service 职责，已有测试和统一口径。RAG 只负责非结构化规则检索。混在一起会重复逻辑、难以测试，也模糊“数据事实”和“知识建议”的来源。
3. Schema 告诉模型必须给出 query、可选 k，并阻止额外参数；metadata 让模型知道片段来自哪个文件和章节，可以引用来源并保留可追溯性。
4. 库存 Tool 提供 SKU003 的真实库存、销量和可售天数，但不知道公司风险阈值；RAG Tool 提供阈值和处理建议，但不知道 SKU003 当前数字。两种证据结合才能做有依据的判断。
5. 优点是完全离线、确定、依赖少、无密钥；限制是字符匹配为主，语义泛化弱。替换时只需注入另一个 LangChain `Embeddings` 实现，KnowledgeBase、Chroma、Retriever、RAG Tool 和 Agent 接口可保持不变。

## 我现在应该重点看哪些代码

1. `src/rag/knowledge_base.py`：按顺序阅读加载、切分、`LocalHashEmbeddings`、`KnowledgeBase` 和组合入口，理解完整 Pipeline。
2. `src/tools/factory.py` 的 `_make_knowledge_tool()` 与 `build_tools()`：理解 Retriever 怎样变成模型可选 Tool，以及为什么使用依赖注入。
3. `src/tools/schemas.py` 的 `KnowledgeSearchInput`：理解 RAG Tool 输入边界与业务 Tool schema 的区别。
4. `tests/test_rag.py`：重点看真实 Retriever、单 RAG Tool、双 Tool 同轮/分轮和失败 ToolMessage 测试。
5. `scripts/verify_rag_live.py`：理解真实验收怎样同时核对业务数据、知识 source 和 Qwen 综合结果。

## Git 变化摘要

新增四份知识文档、RAG Pipeline、RAG Tool schema/工厂、离线与真实验收测试和 Phase 文档；修改两个运行入口和提示词以启用知识 Tool；新增 Chroma/文本切分依赖。没有修改 CSV、Phase 2 Service、Phase 4 Agent Loop 或 Phase 5 Structured Output 业务逻辑。

建议 Commit Message：`feat: add local rag knowledge base`
