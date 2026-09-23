# EcomAgent

基于 LangChain + RAG 的智能商品数据分析 Agent 学习项目。当前仅完成 Phase 1：项目初始化、模拟数据设计、生成与验证。项目用于学习和面试展示，所有数据均为人工设计的模拟数据，不代表真实商家经营情况。

V1 业务范围只有商品、销售、库存、评价。LangChain Agent、Tool Calling、RAG、ChromaDB、Memory、Streamlit 是后续阶段目标，当前没有实现，也没有安装相应依赖。

## 当前交付

- 15 个 SKU，180 天每日销售和库存记录。
- 四份 CSV：商品15行、销售2700行、库存2700行、评价5400行。
- 固定随机种子42、固定截止日2026-09-22，可复现生成结果。
- 独立 CSV 校验脚本、11个自动化测试，以及15个SKU的比较证据。
- 五个明确场景和十个正常对照商品，具体见 [数据设计](docs/mock_data_design.md)。

## 运行

先进入本 README 所在的 `ecom-agent` 文件夹。建议使用独立虚拟环境；当前代码可在 Python 3.9 及以上运行，本机已验证 Python 3.9.6、Pandas 2.3.3。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m scripts.validate_mock_data
python -m unittest discover -s tests -v
```

Windows 激活命令为 `.venv\Scripts\activate`。创建环境和安装依赖只需首次进行。安装依赖需要网络；验证和数据生成完全离线，无需 API Key。

本机同时存在 Python 3.9 与 Python 3.12，其中已装有 Pandas 的3.9环境可以直接运行：

```bash
/usr/bin/python3 -m scripts.validate_mock_data
/usr/bin/python3 -m unittest discover -s tests -v
```

这两个绝对路径命令仅用于当前这台 Mac，不是其他电脑的通用要求。

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

验证命令打印 `PASS：四表结构、180天完整性、指标口径、库存及15个SKU现象全部通过。`，随后输出15行比较结果。测试命令显示 `Ran 11 tests` 和 `OK`。

比较基准来自数据截止日而不是电脑当天日期。默认最近30天是2026-08-24至2026-09-22；之前30天是2026-07-25至2026-08-23，两个窗口均包含首尾日期，互不重叠。

## 文件与学习资料

```text
data/                  四份CSV和生成参数清单
scripts/               生成与独立验证脚本
src/__init__.py         后续应用代码入口包，当前无业务实现
tests/test_phase1.py    数据与口径测试
docs/                  设计、口径、运行结果及阶段讲解
requirements.txt       当前唯一直接依赖 Pandas
.env.example           说明本阶段不需要密钥
.gitignore             排除环境、缓存及真实密钥
```

- [数据设计与每个SKU的预设现象](docs/mock_data_design.md)
- [指标口径与数据字典](docs/metric_definitions.md)
- [阶段讲解与面试练习](docs/phase1_guide.md)
- [本次验证结果](docs/phase1_validation.md)
- [完整比较证据](docs/validation_evidence.csv)

## 常见问题

- `No module named pandas`：执行 `python -m pip install -r requirements.txt`。使用同一个 `python` 安装和运行；用 `python -c "import sys; print(sys.executable)"` 检查实际环境。
- `No module named scripts`：先进入项目根目录，再使用 `python -m scripts...`，不要直接运行脚本文件。
- “数据文件已存在”：验证已有数据即可；确实要重建时添加 `--overwrite`，不要随意覆盖手工改动。
- 日期格式报错：使用 `YYYY-MM-DD`，例如 `2026-09-22`。
- “验证失败”：脚本退出码为1，并说明失败项目。检查被修改的CSV或参数；不要通过放宽断言掩盖错误。

## Git 阶段提交

项目已初始化本地 Git 仓库，尚未自动提交、创建远程仓库或上传。理解并验证本阶段后，可创建第一笔提交：

```bash
git add README.md requirements.txt .gitignore .env.example data scripts src tests docs
git commit -m "feat: initialize product mock dataset"
```

本阶段结束后停止。只有确认“这一阶段已经理解并运行成功”并要求继续，才进入 Phase 2。
