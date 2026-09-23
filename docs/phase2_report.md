# Phase 2 阶段报告

日期：2026-09-23。项目：EcomAgent，基于LangChain + RAG的智能商品数据分析Agent。

## 本阶段目标与实际完成

目标是让普通Python函数能够从四份CSV读取、筛选和计算可靠的业务结果，为后续Tool封装提供基础。本阶段已实现商品查询、销售汇总、两期比较、库存历史与简单可售天数估算、评价统计与低分评价查询。没有引入额外业务模块，没有实现Tool装饰器、Agent、RAG、向量库、Memory或界面。

Phase 1提交为 `2e10cd1 feat: initialize product mock dataset`，开始时工作区干净。沿用用户的PyCharm独立 `.venv`：Python 3.12.10、Pandas 2.3.3。本阶段没有安装新依赖、修改原始数据或自动Commit。

## 重要新增与修改文件

| 文件 | 实际作用 |
|---|---|
| src/services/data_loader.py | CsvDataStore一次读取四表；验证字段、类型、主键、日期、SKU引用及销售公式，返回副本保护内部数据 |
| src/services/common.py | 日期与SKU校验、区间筛选、每日覆盖检查、变化率及记录序列化 |
| src/services/product_service.py | 查询商品快照，提示历史信息限制 |
| src/services/sales_service.py | 销售聚合、完整性状态、两期比较、百分点变化、日均指标 |
| src/services/inventory_service.py | 期末库存、历史、首尾净变化与可售天数估算 |
| src/services/review_service.py | 按评价事件求均分、前一等长区间比较、最近低分内容 |
| src/services/__init__.py | 导出普通Python服务函数，不是工具注册器 |
| scripts/demo_services.py | 离线演示各服务及缺失数据返回 |
| tests/test_services.py | 27个新增测试，使用可手算的小数据和现有模拟数据 |
| AGENTS.md | 保存用户的阶段汇报、练习答案、阅读顺序、提交确认和最终复盘规则 |
| README.md、src/__init__.py | 更新当前阶段、Python环境、运行命令与项目说明 |
| docs/phase2_report.md | 本阶段报告、契约、限制、阅读建议和理解题 |

## 核心执行流程

1. 创建 `CsvDataStore()`，读取项目data目录中的四份CSV，验证后保存为内存快照。传入其他目录也可使用，路径默认不依赖终端工作目录。
2. 调用具体服务函数，校验SKU与日期，筛选指定商品和包含首尾日期的区间。
3. 每日销售和库存检查期望天数、实际天数和缺失日期；评价按事件处理。
4. 使用Pandas汇总原始记录，生成Python字典、数字、列表及None。日期以ISO字符串返回，可以严格序列化成JSON，不返回NaN或Infinity。
5. 调用方根据status、coverage和必要的原因字段判断结果是否可用。当前演示只是打印结果，没有模型决策过程。

文件只在创建store时读取一次。外部调用拿到的是副本，修改它不会污染共享快照。数据文件改变后需重新创建store；本阶段没有自动刷新和缓存失效机制。

## 接口与输出契约

所有接口第一个参数都是store。金额单位人民币元，变化率为小数比例，0.10表示增长10%，不是10个百分点。

| 函数 | 主要参数 | 主要输出 |
|---|---|---|
| get_product_info | sku | product中的名称、类目、单价、评分、评价数；snapshot_note |
| get_sales_data | sku、start_date、end_date | metrics中的orders、units、revenue、sessions、conversion_rate；coverage |
| compare_sales_periods | sku、current_start、current_end、previous_start、previous_end | current、previous、changes、转化率百分点差及日均指标 |
| get_inventory_data | sku、可选start_date与end_date | 期末库存与日期、history、inventory_change、trend、estimated_stock_days |
| get_review_data | sku、可选start_date与end_date、low_rating_limit默认5 | 评价数、均分、低分数、前期指标、评分差及最近低分内容 |

查询SKU会去掉前后空格并转大写。格式必须为SKU加三位数字。日期必须明确写成YYYY-MM-DD；服务不会解析“上个月”等自然语言。单次区间最多3660天，防止意外创建极大的每日日期列表。

库存和评价默认截至四表中带日期记录的最晚日期，回看30天。若各表截止时间不同，结果会暴露缺失端点或日期范围问题，不用电脑当天补足数据，也不推断过期库存。若没有任何带日期记录，调用方必须显式传入查询日期。

### 数据状态与异常

| 情况 | 行为 |
|---|---|
| 商品存在且相关数据满足查询条件 | status为ok |
| SKU格式合法但商品不存在 | not_found，商品或指标为None，并返回说明 |
| 已知商品在区间内没有记录 | no_data；销售指标为None；评价条数为0、均分为None |
| 每日数据缺日期 | partial，列出missing_dates，销售只汇总已观察记录，不补零 |
| 两期任一不完整或无数据 | insufficient_data，保留两期明细，changes为None |
| 日期错误、起止反转、比较重叠或顺序错误 | 抛出带说明的ValueError |
| 文件缺失、字段/数值/主键/公式不合法 | 抛出DataValidationError，指明文件或字段 |

status不是“所有结论都可以计算”的保证：库存记录完整但销售缺失时，status仍描述库存自身，estimate_unavailable_reason会说明不能估算天数。评价同理使用comparison_status说明比较是否可用。

### 聚合口径

- 周期转化率为总orders/总sessions。零访问时为None，有访问但零订单时为0。
- 金额先转整数分求和，再转回元；固定单价与revenue关系在加载时验证。
- 变化同时提供absolute_change和relative_change。上期为0时不计算相对变化，reason为zero_baseline；分子或分母数据缺失时为missing_value。
- 转化率百分点差单独输出，例如6%至3.6%是下降2.4个百分点，相对下降40%。
- 两个比较区间必须不重叠，previous必须更早。不同天数允许比较，但有明确警告，同时返回各期日均数量与金额。
- 库存取请求结束日的实际值，没有当天数据就为None，不沿用更早库存。trend只代表完整区间首尾净变化，不代表每天单调增减；单日查询无趋势。
- 可售天数=结束日库存/所选区间日均销量。必须有完整销售天数与结束日库存；销量为0时无法估算；库存为0且有销量时，可售天数为0。
- 评价均分按每条记录计算。低分定义为1至2分，按最近日期返回至多N条，并显示是否截断。评分比较使用紧邻的前一个等长区间。
- 评价没有每日固定条数约束。日期落在文件已观察范围内也不能证明采集完整；范围外的比较或没有评价时，不输出评分变化。

## 技术及使用原因

Pandas负责读取、筛选、关联、聚合；Python标准库datetime负责日期；pathlib负责路径；json用于展示；unittest和tempfile用于离线测试。一个简单的CsvDataStore类共享已验证数据，没有引入继承框架、数据库或复杂抽象。

需补充理解的少量知识是：实例保存数据快照、返回副本、异常与业务空结果的区别、类型注解中的 `str | None`、单元测试的临时目录。这些都有直接用途，不是为了堆砌技术。

## 实际遇到的设计问题

本阶段首次执行演示成功，首轮37个测试全部通过。复核时发现库存边界测试的名称同时提到“零销量和零库存”，实际上只覆盖零销量，因此更正名称并补充独立零库存测试；最终38个测试全部通过。未遇到需要修复的运行失败，不虚构Bug记录。

| 问题 | 原因 | 定位过程 | 解决方式 |
|---|---|---|---|
| Phase 1验证器不能直接作为服务加载器 | 它固定要求15个SKU、180天、每日两条评价及预设异常 | 阅读validate_tables，确认它验证的是模拟实验设计，而非通用查询输入 | 保留原验证器不动；新增仅验证通用结构和数值约束的CsvDataStore |
| 不同数据粒度不能套用同一种完整性检查 | 销售和库存是每日快照，评价是事件 | 检查原始数据字典，并用不等每日评价数量、稀疏评价日期的小样本测试 | 每日表列出缺失日期，评价按已有事件统计并声明已观察日期范围的局限 |
| 零库存边界未被对应名称的测试真正覆盖 | 首次测试只构造了零销量场景 | 首轮测试后逐项复核测试名与断言 | 重命名零销量测试，新增有销量但期末库存为0的测试，确认估算结果为0 |

## 验证结果

最终在用户的 `.venv` 中运行38个测试，全部通过：Phase 1原有11个，Phase 2新增27个。

覆盖：单日边界、两期方向与重叠、天数不同、空数据、缺日期、未知SKU、零分母、零基数、加权转化、整数分金额、库存结束日缺失、销售缺失、零销量、零库存、评价事件加权、低分截断、稀疏评价、字段/主键/数值错误、读取失败、快照副本及JSON序列化。实际CSV场景测试确认SKU001访问下降、SKU002转化下降、SKU004销量增长、SKU003库存风险和SKU005评分下降。

实测样例：SKU003库存50件，最近30天销量2312件，估算可售天数为50/(2312/30)，约0.6488天；SKU005近期均分2.1，前期约4.6833。结果来自服务计算，没有硬编码服务回答。

演示命令成功返回可严格序列化JSON。Phase 1原有数据和生成器保持不变；本次未修改依赖版本。

## 如何运行与复核

在项目根目录执行：

```bash
.venv/bin/python -m scripts.demo_services
.venv/bin/python -m unittest discover -s tests -v
```

激活虚拟环境后也可以使用 `python`。在PyCharm中选择项目的Python 3.12解释器，将运行模块设为 `scripts.demo_services`，工作目录设为项目根目录。不要用系统Python 3.9运行这些新服务。

正确结果：演示输出商品、销售、比较、库存、评价和缺失示例；测试末尾为 `Ran 38 tests`、`OK`。

常见报错：`No module named src`通常是未在项目根目录按模块运行；`No module named pandas`表示未选择项目虚拟环境；DataValidationError需按报错字段检查CSV，不能把数据错误转换为“正常无数据”；已有store不会自动感知文件修改，应重新创建实例。

## 最值得亲自阅读的五处

1. `scripts/demo_services.py::main`：先看如何创建store及调用五类服务，不必先读所有校验细节。
2. `src/services/sales_service.py::summarize_sales/get_sales_data/compare_sales_periods`：重点理解分子分母先汇总、空值与零、区间完整性和变化率。
3. `src/services/data_loader.py::CsvDataStore`：看构造函数、table和as_of_date；理解一次加载、校验后共享、副本隔离及基准日来源。
4. `src/services/inventory_service.py::get_inventory_data`：理解时点库存与期间销量如何组合，哪些条件不满足就拒绝估算。
5. `tests/test_services.py`：重点读weighted_sales_conversion、partial_dates、review_event_weighting及zero_baseline四个测试；理解如何用小样本手算，而不是仅检查“不报错”。

## 面试与理解题

1. 为什么查询服务不直接调用Phase 1的完整模拟数据验证器？二者各自应该保证什么？
2. 两天分别1单/10次访问、9单/900次访问，整体转化率是多少？为什么不能平均两天转化率？面试官可能追问：上期为0时如何表示增长率？
3. 一段30天查询只有29天数据，你会返回0补足、忽略缺失还是报出缺失？对两期比较和库存可售天数有什么影响？
4. 为什么评价均分按事件计算，而评价没有出现的日期不直接算作数据缺失？面试官可能追问：范围内没有记录能否证明没有评价？
5. 当前函数返回了JSON兼容字典，为什么还不能叫Agent Tool？后续封装Tool时，哪些逻辑应该保留在服务层？

## 【参考答案】

1. Phase 1验证器检查特定实验设计，包括SKU数量、天数和人为设置的异常；服务加载器检查通用数据是否合法。若复用实验约束，一个正常的新商品或更短的数据集也会被拒绝。场景验证继续保留，查询服务不依赖预设答案。
2. 总转化率是10/910≈1.0989%。每日转化率简单平均得到5.5%，错误地给10次访问和900次访问同等权重。上期为0时相对增长未定义，应返回None并说明zero_baseline，而不是0%或无限增长；绝对变化仍可计算。
3. 返回partial、实际记录汇总及明确缺失日期，不把未知当零。本实现不对不完整周期计算比较变化；估算库存天数也要求完整销售日期。若库存结束日缺失，不能把前一天库存当作当天库存。
4. 每条评价是一个观测事件，按明细求均值才能正确体现不同日期评价数量。没有评价的日期可能是正常无事件，也可能是采集遗漏，仅凭文件无法分辨，因此应报告观测范围和局限，不能声称已验证事件采集完整。
5. 当前只有普通函数、参数和返回值，没有面向模型的工具描述、参数契约、注册或调用机制。下一阶段可封装工具接口，但CSV读取、筛选、计算、日期覆盖和异常判断应留在服务层，避免模型参与指标计算。

## 当前限制与下一阶段目标

- 当前处理明确SKU及日期，不理解自然语言或进行原因推理。
- 产品表是当前快照；价格固定，不支持历史价格分析。商品汇总评分不当作历史评分，也不强制其等于某个可能不完整的评价文件。
- 加载器不验证现实库存补货是否合法，库存服务只报告已有观察值；没有补货流水、预测或通用风险阈值。
- 数据全部加载内存，小规模学习数据适用；没有自动更新、并发数据编辑保证或数据库。
- JSON兼容字典属于普通服务返回值，不代表已实现Pydantic结构化报告或模型输出校验。
- 下一阶段仅在用户确认后封装Phase 3业务Tools，说明工具名称、描述、参数、结果和错误处理。本阶段不提前实现。

## Git变化摘要与建议提交

新增AGENTS.md、src/services下7个文件、scripts/demo_services.py、tests/test_services.py和本报告；修改README.md及src/__init__.py。原有四份CSV、Phase 1生成验证脚本与测试、requirements.txt均无改动。

建议Commit Message：`feat: implement pandas product data services`。

尚未执行git add或git commit。请先在你的环境运行并阅读重点代码，再明确确认是否提交。完整项目最终复盘和求职材料留待全部阶段完成后，根据实际实现整理。
