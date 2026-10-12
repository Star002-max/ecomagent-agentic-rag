# EcomAgent

基于 LangChain + RAG 的智能商品数据分析 Agent 学习项目。Phase 1至Phase 6已完成，Phase 7 Agent Evaluation Baseline 已开发并完成 Fake 回答人工复核，等待最终验收。项目用于学习和面试展示，所有数据均为模拟数据，不代表真实商家经营情况。

V1业务范围只有商品、销售、库存、评价。模型可从5个业务数据Tool和1个运营知识检索Tool中自主选择；CSV Service负责确定性数据，RAG负责非结构化规则。综合分析使用Pydantic校验最终JSON；没有跨问题Memory或Streamlit，也没有使用LangGraph。

## 当前交付

- 15 个 SKU，180 天每日销售和库存记录。
- 四份 CSV：商品15行、销售2700行、库存2700行、评价5400行。
- 固定随机种子42、固定截止日2026-09-22，可复现生成结果。
- 107个离线测试，另有各阶段显式真实API验收记录及15个SKU的模拟数据比较证据。
- 五个明确场景和十个正常对照商品，具体见 [数据设计](docs/mock_data_design.md)。
- 商品、销售、周期比较、库存、评价的普通Python查询函数；区分未知商品、无数据、部分数据和数值零。
- [Phase 2阶段报告](docs/phase2_report.md)：接口、执行流程、设计问题、测试、阅读顺序及带参考答案的练习。
- [Phase 3阶段报告](docs/phase3_report.md)：普通函数与Tool的区别、名称/描述/schema、调用与返回、实际Bug和参考答案。
- [Phase 4阶段报告](docs/phase4_report.md)：真实连接、模型选工具、消息往返、错误与安全处理、阅读顺序及参考答案。
- [Phase 4真实验收记录](docs/phase4_live_results.json)：模型实际选择的工具、参数、数据和答案，无密钥或内部推理内容。
- [Phase 5阶段报告](docs/phase5_report.md)：Multi-Tool流程、Structured Output、测试、问题记录和练习答案。
- [Phase 5真实验收记录](docs/phase5_live_results.json)：SKU001和SKU005的工具证据与结构化结果。
- [Phase 6阶段报告](docs/phase6_report.md)：Markdown加载、切分、本地Embedding、Chroma检索和RAG Tool集成。
- [Phase 6真实验收记录](docs/phase6_live_results.json)：SKU003库存数据与库存规则的真实综合回答。
- [Phase 7阶段报告](docs/phase7_report.md)：13个固定评估案例、Offline/Live边界、指标、结果、RAG检索基线和学习题。
- [Phase 7评估案例](evals/phase7_cases.json)：固定问题、必需/允许工具、数据证据及人工复核项。
- [Phase 7 Offline结果](docs/phase7_offline_results.json)：Fake Model执行、真实本地Tools/RAG证据和Top-3检索记录。
- [Phase 7 Live结果](docs/phase7_live_results.json)：限定的Qwen验收记录；连接失败后按规则停止，没有重试。
- [工具定义快照](docs/tool_catalog.json)：可查看后续模型将接收的工具名称、用途和JSON参数schema，不含数据对象或文件路径。

## 运行

先进入本 README 所在的 `ecom-agent` 文件夹。当前开发与验证环境为独立虚拟环境中的 Python 3.12.10、Pandas 2.3.3；Phase 2类型注解使用Python 3.10及以上语法，建议沿用已验证的3.12环境。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m scripts.validate_mock_data
python -m scripts.demo_services
python -m scripts.demo_tools --schemas-only
python -m scripts.demo_tools
python -m unittest discover -s tests -v
```

Windows激活命令为 `.venv\Scripts\activate`。数据生成、服务与工具演示、unittest全部离线，无需API Key。Phase 4运行与真实验收需要配置、网络及API调用额度。

本机已存在PyCharm项目虚拟环境，当前Phase不要求重建环境。其他克隆环境请先安装requirements，复制.env.example为.env并自行填入配置。环境变量优先于.env。不要把密钥放入命令参数或提交到Git。Offline Evaluation不调用外部模型；Live Evaluation会请求Qwen API，且只允许固定案例C06和C09。Live遇到API连接错误后停止，不自动重试。

```bash
.venv/bin/python -m scripts.run_agent "SKU003现在有多少库存？" --show-tools
.venv/bin/python -m scripts.run_agent "比较SKU002最近30天和之前30天的销售表现。" --show-tools
.venv/bin/python -m scripts.run_analysis "分析SKU005最近30天的销售和评论变化，有什么值得关注的问题？" --show-tools
.venv/bin/python -m scripts.run_agent "分析SKU003当前库存风险，并根据我们的库存管理规则给出建议。" --show-tools
.venv/bin/python -m scripts.evaluate_agent --mode offline
.venv/bin/python -m scripts.evaluate_agent --mode live
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m scripts.check_secrets
```

PyCharm选择本项目 `.venv/bin/python`，运行模块scripts.run_agent，工作目录设为项目根目录。每次运行是独立问题，不保存上次聊天。数据截止日固定为2026-09-22，不使用电脑当天。

Phase 4、5、6真实验收脚本分别为 `scripts.verify_agent_live`、`scripts.verify_analysis_live`、`scripts.verify_rag_live`。真实验收会产生API请求并更新记录，不应混入日常离线测试。RAG文档嵌入与检索完全离线，不使用API Key。

## 重建数据

交付中已包含 CSV，可以先验证，无需重新生成。生成器默认拒绝覆盖已有数据。

```bash
python -m scripts.generate_mock_data --overwrite
python -m scripts.validate_mock_data --report docs/validation_evidence.csv
```

也可以输出到新目录并指定种子、截止日：

```bash
python -m scripts.generate_mock_data --output-dir work/sample --seed 7 --end-date 2025-12-31
python -m scripts.validate_mock_data --data-dir work/sample
```

同一代码、种子、截止日及运行环境产生逐字节一致的数据和清单。修改参数后生成器仍检查场景；失败会报错。requirements固定项目直接依赖版本，尚不是全部传递依赖的完整锁文件。模型回答不具备逐字节复现保证。

## 预期结果

Phase 1验证打印PASS；demo_services与demo_tools仍是离线演示。run_agent和run_analysis实际调用模型，show-tools打印模型选中的工具及状态。Phase 7当前全量离线测试显示 `Ran 123 tests`、`OK`。Offline Evaluation的自动结果只验证脚本化Fake响应、Agent协议和本地证据，不代表真实Qwen准确率；人工复核也只适用于固定Fake回答；Live结果只代表实际完成的固定样本。

比较基准来自数据截止日而不是电脑当天日期。默认最近30天是2026-08-24至2026-09-22；之前30天是2026-07-25至2026-08-23，两个窗口均包含首尾日期，互不重叠。

## 文件与学习资料

```text
data/                  四份CSV和生成参数清单
knowledge/             四份运营知识Markdown文档
scripts/               生成与独立验证脚本
src/services/          Pandas数据加载及五类查询服务
src/tools/             参数schema、工具工厂和返回封装
src/agent/             基础模型适配与Tool Calling Loop
src/prompts/           基础与综合分析提示词
src/models/            最终结构化输出模型（不含业务计算）
src/rag/               文档加载、切分、本地Embedding与Chroma检索
src/config.py          本地配置读取
tests/                 数据、服务、工具、循环与安全的离线测试
docs/                  设计、口径、运行结果及阶段讲解
requirements.txt       固定直接依赖版本
.env.example           配置变量与占位示例，不含真实密钥
.gitignore             排除环境、缓存及真实密钥
AGENTS.md              后续阶段固定协作与提交规则
```

- [数据设计与每个SKU的预设现象](docs/mock_data_design.md)
- [指标口径与数据字典](docs/metric_definitions.md)
- [阶段讲解与面试练习](docs/phase1_guide.md)
- [本次验证结果](docs/phase1_validation.md)
- [完整比较证据](docs/validation_evidence.csv)

## 常见问题

- `No module named pandas`：执行 `python -m pip install -r requirements.txt`。使用同一个 `python` 安装和运行；用 `python -c "import sys; print(sys.executable)"` 检查实际环境。
- `No module named langchain_core` 或 `pydantic`：在项目虚拟环境中安装更新后的requirements；本阶段只用LangChain Core，不需要安装完整langchain包。
- `No module named scripts`：先进入项目根目录，再使用 `python -m scripts...`，不要直接运行脚本文件。
- “数据文件已存在”：验证已有数据即可；确实要重建时添加 `--overwrite`，不要随意覆盖手工改动。
- 日期格式报错：使用 `YYYY-MM-DD`，例如 `2026-09-22`。
- “验证失败”：脚本退出码为1，并说明失败项目。检查被修改的CSV或参数；不要通过放宽断言掩盖错误。
- 模型鉴权、接口或网络错误：按脱敏错误检查当前配置；不自动换模型或服务。
- limit_reached：达到6次模型请求或8次工具调用上限，表示未完成；不能当作正常回答。
- 修改CSV后需重新创建数据快照；CLI每次运行会重新读取。

## Git 阶段提交

Phase 1至Phase 6已完成。Phase 7尚未提交，需先人工复盘与验收；不要自动提交。提交前运行check_secrets并核对Git Status和Diff，确认`.env`仍被忽略且没有敏感信息。Phase 7建议Commit Message：`feat: add agent evaluation baseline`。
