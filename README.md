# EcomAgent

基于 LangChain + RAG 的智能商品数据分析 Agent 学习项目。当前已完成 Phase 1 数据基础、Phase 2 Pandas 查询服务和 Phase 3 Agent Tools 层。项目用于学习和面试展示，所有数据均为人工设计的模拟数据，不代表真实商家经营情况。

V1业务范围只有商品、销售、库存、评价。当前有5个真实LangChain StructuredTool，可离线调用并生成ToolMessage。尚未接入LLM或验证模型自主选工具，也没有实现完整Agent、RAG、ChromaDB、Memory或Streamlit。

## 当前交付

- 15 个 SKU，180 天每日销售和库存记录。
- 四份 CSV：商品15行、销售2700行、库存2700行、评价5400行。
- 固定随机种子42、固定截止日2026-09-22，可复现生成结果。
- 独立CSV校验脚本、57个自动化测试（Phase 1共11个、Phase 2新增27个、Phase 3新增19个），以及15个SKU的比较证据。
- 五个明确场景和十个正常对照商品，具体见 [数据设计](docs/mock_data_design.md)。
- 商品、销售、周期比较、库存、评价的普通Python查询函数；区分未知商品、无数据、部分数据和数值零。
- [Phase 2阶段报告](docs/phase2_report.md)：接口、执行流程、设计问题、测试、阅读顺序及带参考答案的练习。
- [Phase 3阶段报告](docs/phase3_report.md)：普通函数与Tool的区别、名称/描述/schema、调用与返回、实际Bug和参考答案。
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

Windows 激活命令为 `.venv\Scripts\activate`。创建环境和安装依赖只需首次进行。安装依赖需要网络；验证和数据生成完全离线，无需 API Key。

本机已存在PyCharm项目虚拟环境，Phase 3依赖已安装，不需要重建环境。其他克隆环境请先运行 `python -m pip install -r requirements.txt`。本机直接运行：

```bash
.venv/bin/python -m scripts.demo_services
.venv/bin/python -m scripts.demo_tools
.venv/bin/python -m unittest discover -s tests -v
```

请不要再使用系统的Python 3.9运行Phase 2。PyCharm中选择本项目 `.venv/bin/python`；其他平台按实际环境选择解释器。

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

同一代码、种子、截止日及运行环境产生逐字节一致的数据和清单。修改参数后，生成器仍会检查场景是否满足要求；失败会报错，不会为了输出数据跳过校验。依赖文件固定直接依赖 Pandas，尚不是所有传递依赖的完整锁文件。

## 预期结果

Phase 1验证命令打印PASS。服务演示打印业务JSON；工具演示输出五个工具的调用结果、未知SKU和参数错误示例，以及人工构造tool_call得到的ToolMessage。它不是模型自主选择演示。全部测试显示 `Ran 57 tests` 和 `OK`。

比较基准来自数据截止日而不是电脑当天日期。默认最近30天是2026-08-24至2026-09-22；之前30天是2026-07-25至2026-08-23，两个窗口均包含首尾日期，互不重叠。

## 文件与学习资料

```text
data/                  四份CSV和生成参数清单
scripts/               生成与独立验证脚本
src/services/          Pandas数据加载及五类查询服务
src/tools/             参数schema、工具工厂和返回封装
tests/                 数据、服务、工具的离线测试
docs/                  设计、口径、运行结果及阶段讲解
requirements.txt       Pandas、LangChain Core、Pydantic的固定版本
.env.example           说明本阶段不需要密钥
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

## Git 阶段提交

Phase 1已提交为 `2e10cd1`，Phase 2已按用户授权提交为 `279c627 feat: implement pandas product data services`。Phase 3尚未提交；以下命令仅为验收并确认提交后的建议：

```bash
git add README.md requirements.txt src/tools scripts/demo_tools.py tests/test_tools.py docs/phase3_report.md docs/tool_catalog.json
git commit -m "feat: wrap product data services as langchain tools"
```

本阶段结束后停止。只有用户验收并明确要求继续，才进入Phase 4。Git Commit前仍须取得明确确认。
