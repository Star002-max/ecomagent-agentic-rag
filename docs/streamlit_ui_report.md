# Streamlit Web UI 阶段报告

## 目标与完成范围

新增单页 Streamlit 应用，包含 AI Chat 和 Dashboard 两个 Tab。Chat 默认组装现有真实 `ProductAgent` 与配置的 Qwen `ChatOpenAI`，使用现有 Tool Calling Loop、RAG Tool 和最多4轮 `ConversationMemory`。Dashboard 使用现有 CSV snapshot、库存/销售/评价 Service 和 Streamlit 原生图表。默认 Embedding 为 LocalHash；Aliyun Embedding 索引只在侧栏显式勾选确认并点击初始化后构建。

Codex 的开发与自动化测试未调用真实 Qwen 或 Aliyun API，未改已有业务逻辑/CSV，未修改 Phase 1–9 的 Commit，未引入 LangGraph、FastAPI、前端框架或数据库。用户随后在浏览器完成真实 Qwen Agent 验收；Aliyun Embedding 的 Streamlit 页面初始化与查询链路尚未做真实验收。Git 改动尚未 Commit。

## 重要文件

- `streamlit_app.py`：页面、真实 Agent runtime 生命周期、聊天记录、Tool/RAG 证据、Dashboard 指标与趋势图。
- `src/config.py`：`load_embedding_settings(provider_override=...)` 支持 UI 在不改环境变量的情况下选择 Provider，凭据仍从环境或 `.env` 读取。
- `requirements-ui.txt`：唯一新增直接依赖 `streamlit==1.65.0`；项目核心 `requirements.txt` 保持不变。
- `tests/test_streamlit_app.py`：Fake Model 通过真实 `ProductAgent` 执行本地 Tools/RAG，验证轨迹和 Memory；覆盖页面渲染、Aliyun 确认门控与 Provider 配置。
- `README.md`：安装和本机启动命令、Provider 与费用说明。

## 执行流程

首次进入时加载本地 CSV store，并用 LocalHash 建立本地知识索引；构造真实配置 Chat Model，但不发送 Chat 请求。发送消息后，页面调用 `ProductAgent.run()`；成功结果直接展示 `AgentResult.answer`、`status`、`model_calls`、`tool_calls`，RAG Tool 的实际 source、section 和 content 由返回结果展开显示。成功完整轮次沿用 Agent 写入的 Memory。清空时重置当前 Provider runtime 的 Memory 与 UI transcript。

Aliyun 被选中时页面只展示费用提示和未勾选的确认框；确认按钮初始禁用。用户勾选并点击后才加载 Aliyun Embedding 配置并建立 1024维索引。该 runtime 缓存在当前 Streamlit session_state，输入问题造成的页面重跑不会重建索引；切换回已建立的其他 Provider 会恢复该会话对应的 runtime 和 Memory。Dashboard KPI 由 `get_inventory_data`、`get_sales_data`、`get_review_data` 返回；趋势图使用现有 CSV 日记录或库存 Service 历史，未改写 Service 指标计算。

## 测试与检查

- `.venv/bin/python -m unittest tests.test_streamlit_app -v`：本次 **5项通过**。Fake Model 只注入自动化测试；应用的 `build_runtime()` 默认调用 `create_model()` 创建配置的真实 Chat Model。
- `.venv/bin/python -m unittest discover -s tests`：本次 **150项通过**（此前 UI 开发验收为149项）。
- Streamlit `AppTest`：页面无异常渲染，出现 AI Chat/Dashboard 两个 Tab 和 Dashboard 指标；选择 Aliyun 后，在确认前初始化按钮为 disabled。
- 连续对话 `AppTest`：Fake Model 完成两轮 Agent/Tool 调用；两轮后输入框仍存在，且同一个 `ConversationMemory` 保留两轮完整对话。
- 本机 Streamlit 服务健康检查：服务仅绑定 `127.0.0.1`，`/_stcore/health` 返回 HTTP 200 / `ok`；随后停止服务。无 Chat/Embedding API 调用。
- `.venv/bin/python -m scripts.check_secrets`：检查 `.env` 忽略/未跟踪及待提交 Diff；`git diff --check` 通过。
- 用户浏览器真实验收：Qwen Agent 成功回答 SKU003 库存问题，`get_inventory_data` 返回真实业务数据；第二轮追问结合 SKU003 上下文；RAG `search_operation_knowledge` 返回 success；连续对话输入框仍可用。用户确认 Dashboard 指标和趋势图正常，切换 SKU 后内容同步更新，SKU003 期末库存50、估算可售约0.65天与 Agent Tool 结果一致。
- Aliyun Embedding 的 Streamlit 页面真实初始化与查询：**尚未验收**。页面保留显式确认门控；本报告不把此前独立的 RAG 云端评估算作 Web UI 验收。

## 安全、费用与限制

- API Key 仅由本机 Python 进程从 `.env`/环境变量读取，不展示或发给浏览器代码。Agent 可见异常沿用既有脱敏边界；未预期异常只显示错误类型，不在页面输出堆栈。
- LocalHash 只避免 Embedding API 费用；每条 Chat 用户问题仍会调用真实 Chat Model，Agent 一轮可发起多次模型请求。Aliyun 初始化会嵌入知识库文本，后续每个 RAG 搜索需嵌入查询，可能产生费用；页面不猜测费用金额。
- Chroma 是进程内索引，按 session/provider 缓存；应用进程退出或 session 被清除后，Aliyun 索引重建会再次发送文档 Embedding 请求。没有跨会话/持久化索引。
- `AgentResult` 仅在 Agent 正常返回或达到循环上限时包含现有 `tool_calls`。若 Tool 执行后下一次 Chat 请求异常，当前 Agent 接口不会向 UI 返回部分轨迹；页面如实显示失败且不伪造记录。
- Codex 自动化测试只验证离线页面、真实本地数据/Service Dashboard 和 Fake Model 驱动的 Agent 协议；用户另行完成了真实 Qwen Chat 浏览器验收。真实 Aliyun Web UI 初始化/查询仍未验证。

## SKU001 库存趋势核对

只读对照了 `data/inventory.csv` 中 SKU001 的每日库存快照，以及 `scripts/generate_mock_data.py` 的库存生成逻辑。默认最近30天区间（2026-08-24 至 2026-09-22）中，库存从 2026-08-31 的 1012 增至 2026-09-01 的 1790（+778），并从 2026-09-20 的 1021 增至 2026-09-21 的 1787（+766）。生成脚本明确写明：SKU003 不补货，其他 SKU 在出货后库存低于1000时，会在当天出货前补至目标库存。因此图表的突然回升来自模拟数据中的补货重置，符合现有生成逻辑。

`inventory.csv` 本身只有日期、SKU 和库存快照，没有单独的补货事件/数量字段；所以它能直接证明库存快照发生上升，补货原因则由对应生成脚本规则确认。本次没有修改 CSV 或图表逻辑。

## 连续聊天输入框问题

首次真实 Qwen 对话完成后，聊天记录和 Tool 轨迹正常显示，但 Tab 内的输入框不再可见。定位发现 `_render_chat()` 在 `st.tabs()` 的聊天 Tab 内调用 `st.chat_input()`，导致输入框属于 Tab 容器布局；页面重跑并累积聊天记录后，输入框未固定在应用视口底部。没有发现跳过输入框的 rerun 条件分支，也没有清空或替换 Memory 的状态逻辑；页面没有自定义 CSS 或固定高度容器。

将输入框改为 `st.bottom.chat_input()`，由 Streamlit 将其固定在页面底部。新的离线 AppTest 连续提交两条问题，断言每轮完成后输入框仍存在、历史 Memory 对象仍被 runtime 复用，且两轮问答均被保留。此次修复没有变更 Agent、Tool、RAG 或业务 Service。

## 建议阅读顺序

1. `streamlit_app.py::build_runtime`：如何使用真实 Chat Model、所选 Embedding、现有 Tools 创建 Agent。
2. `streamlit_app.py::_render_chat`：Memory、结果状态、工具调用和 RAG 证据如何映射到页面。
3. `streamlit_app.py::_render_dashboard`：如何复用 Service 和 CSV 时间序列绘图。
4. `src/agent/runner.py::ProductAgent._run`：确认页面没有重写 Agent Loop。
5. `src/config.py::load_embedding_settings`：Provider 覆盖与密钥读取规则。

## 理解与面试题

1. Streamlit 的 session_state 为什么缓存 Agent runtime 和 Chroma 知识库？
2. 如何保证 Aliyun Provider 不会因为 Streamlit rerun 被重复初始化？
3. 为什么页面展示实际 AgentResult 轨迹，而不自行预测模型可能调用了什么 Tool？
4. Chat API Key 如何避免出现在浏览器端？

### 【参考答案】

1. Streamlit 每次交互会重跑脚本；缓存 runtime 可保留同一个 Agent/Memory/索引，避免会话断裂和重复 Embedding 初始化费用。
2. 云端索引只有在用户勾选确认并点击按钮后构建，创建后放入当前 session_state 的 Provider runtime；普通 rerun 只复用缓存对象。
3. Agent 才是 Tool 调度的真实执行方；只有 `AgentResult.tool_calls` 能证明实际调用、参数、结果和 RAG 证据，预测会造成伪造轨迹。
4. Python 服务端读取 `.env` 并构造 LangChain Chat Model；浏览器只访问本机 Streamlit 页面，不接触 Key，错误也通过现有脱敏边界处理。

## Git 摘要与阶段边界

当前待提交改动包括新增 `streamlit_app.py`、`requirements-ui.txt`、`tests/test_streamlit_app.py`、本报告，并修改 `src/config.py` 与 `README.md`；还包括聊天输入框连续对话修复及本次验收报告核对。建议提交信息：`feat: add Streamlit interface for EcomAgent`。未 Commit。
