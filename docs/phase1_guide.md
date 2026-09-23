# Phase 1 学习与运行指南

## 本阶段目标与理由

完成项目初始化、四类模拟数据及可重复验证。后续模型只能解释工具提供的业务事实，因此必须先确保底层数据可信、指标有统一含义。此时无需模型API或界面。

用到的主要知识是Python函数、循环、列表与字典、日期、随机数、Pandas DataFrame及CSV。额外补充标准库argparse、pathlib、unittest和虚拟环境基础，没有引入额外业务框架。

## 新增文件与职责

| 文件 | 职责 |
|---|---|
| scripts/generate_mock_data.py | 生成相关联的四类数据、写入CSV和参数清单 |
| scripts/validate_mock_data.py | 校验文件结构、指标、日期、跨表关系和预设现象 |
| tests/test_phase1.py | 11个测试，包含错误数据、口径边界和可复现性 |
| data/products.csv | 15个商品的当前信息 |
| data/sales.csv | 2700行每日销售数据 |
| data/inventory.csv | 2700行每日期末库存 |
| data/reviews.csv | 5400行评价明细 |
| data/dataset_manifest.json | 保存种子、日期范围、行数、版本等复现信息 |
| docs/mock_data_design.md | 每个SKU的设计和验收阈值 |
| docs/metric_definitions.md | 数据字典、聚合口径和已知限制 |
| docs/validation_evidence.csv | 全部SKU的两期实际指标和变化 |
| docs/phase1_validation.md | 默认数据的验证摘要 |
| README.md | 环境、运行、测试、常见错误和Git说明 |
| requirements.txt | 固定当前直接依赖Pandas版本 |
| .gitignore、.env.example | 版本管理排除项及当前无需密钥的说明 |
| scripts、tests、src下的__init__.py | 标识Python包；src目前没有业务实现 |

## 核心执行流程

入口main读取命令参数，然后generate检查目标文件是否已经存在。build_tables在内存中按商品依次生成销售与评价，再根据销量生成库存，最后汇总商品信息。validate_tables检查内存数据，全部通过才写出CSV和清单。

单独执行validate_mock_data时，validate_directory会从磁盘重新加载四份CSV和清单，再调用验证逻辑。这能发现序列化、手动修改和缺失文件的问题，而不只证明内存中的数据正确。

period_summary和relative_change是验证脚本内部的辅助函数，用于展示正确的汇总和变化口径。它们没有SKU查询接口、工具封装或模型调用，不是提前实现Phase 2数据服务。

## 怎样亲自运行与观察

1. 按README进入项目目录并选择Python环境。运行验证脚本，确认出现PASS。
2. 打开四份CSV和数据字典，区分每张表一行代表什么，尤其是评价明细与每日销售的不同粒度。
3. 打开validation_evidence.csv，查看previous和recent两组指标。change列是相对变化小数，conversion_pp_change是百分点差。
4. 运行11个测试，确认OK。测试会在临时目录重建数据，不覆盖交付数据。
5. 需要重新生成时使用--overwrite；若只是练习，优先用--output-dir指定另一个目录。
6. 理解后创建本阶段Git提交，再说明已经运行成功。

## 本阶段必须理解

- 可复现性：固定种子控制随机波动；固定截止日避免今天运行和明天运行数据范围不同。
- 数据粒度：商品是静态快照，销售与库存是SKU/天，评价是逐条事件。不同粒度直接连接可能造成重复计数。
- 依赖关系：访问量和转化率生成订单，订单生成件数，件数生成收入与库存消耗；不要独立随机生成所有列。
- 正确汇总：数量与金额可求和；比率要先汇总分子分母；库存要取时点；评分要按明细或条数加权。
- 验证层次：字段、范围、主键、跨表一致性、日期完整性、场景阈值和异常处理都要检查。
- 证据边界：生成规则可以设定关联，未来Agent必须用实际指标支持判断，不能把相关性当作因果证据。
- 测试不等于模型能力：当前测试只证明数据基础满足设计，不证明尚未实现的Agent能分析正确。

## 面试练习

先尝试回答，当前不附标准答案。

1. 为什么不能直接对每天的conversion_rate取平均？当每天访问量差异很大时会有什么问题？
2. 为什么orders与units要分开？转化率和销售额各自应该使用哪个字段？
3. 如果每列都独立随机生成，销售、库存、评价可能出现哪些矛盾？你如何避免？
4. 固定随机种子是否足以保证完整复现？为什么还需要固定日期、代码与依赖环境？
5. SKU005的评分与转化率同时下降，为什么还不能直接断定评分导致销量下降？需要什么额外证据？

完成本阶段后停止，等待学习者确认理解并运行成功，不自动进入下一阶段。
