# Phase 3 阶段报告

项目：EcomAgent，基于LangChain + RAG的智能商品数据分析Agent。

## 目标与实际完成

本阶段将Phase 2的五个普通Service接口封装为真实的LangChain StructuredTool。重点是理解工具描述、参数验证、Service委托执行和模型可读取的返回结果，而不是提前构建Agent。

已实现：get_product_info、get_sales_data、compare_sales_periods、get_inventory_data、get_review_data。没有新增业务计算，没有修改Service、原始CSV或之前阶段的测试。知识检索工具仍留到RAG阶段，不创建空壳或假检索结果。

起始Git工作区干净，基于Phase 2提交279c627。最终57个测试通过，其中新增19个工具测试。工具描述导出和离线调用演示均通过，依赖检查无冲突。本阶段未执行Git暂存、Commit或上传。

## 普通函数与Agent Tool的区别

普通Python函数通过函数名和Python参数被程序调用。模型并不会自动读取项目文件、理解函数签名或扫描CSV目录。

本项目的Tool由四部分组成：名称、用途描述、参数schema、实际可执行的函数。模型侧可获得前三者，应用侧保留执行函数和数据对象。StructuredTool提供输入校验与统一invoke接口，并支持接收tool_call后生成对应的ToolMessage。

这不意味着“函数加了包装就会自主决策”。模型决定是否调用什么工具、应用真正执行工具并把结果传回模型，是后续Agent或工具调用流程要完成的工作。

### name、description、schema各自的职责

| 部分 | 本项目例子 | 作用 |
|---|---|---|
| name | get_inventory_data | 稳定且唯一的调用标识，应用用它找到对应工具 |
| description | 查询期末库存、历史趋势和可售天数；日期省略时用数据截止日 | 帮助模型判断适用问题、限制及何时改用其他工具 |
| 参数schema | sku必填，start_date/end_date可选，日期为字符串 | 告诉模型应提供哪些字段、类型、默认值和约束，并供本地验证 |
| 执行函数 | run调用Phase 2的get_inventory_data | 在应用进程中实际执行，模型不能仅靠描述读取CSV |

工具名称用于定位，描述用于表达用途，schema用于输入契约。描述写得清楚能帮助选工具，但无法保证模型每次都选对。

## LLM后续如何知道与选择工具

当前build_tools返回五个工具对象；describe_tools导出包含名称、描述和parameters的function-calling定义。docs/tool_catalog.json是本次实际导出的快照。

Phase 4接入模型时，应用需将这些定义通过模型支持的tools参数或LangChain模型适配器的绑定接口提供给模型。工具定义不包含store、路径、源码或完整CSV。不是把JSON文件保存在目录里，模型就能自动知道工具。

例如用户问“SKU003还有多少库存”，模型结合问题、上下文和工具说明，可能输出工具名get_inventory_data以及参数sku=SKU003。应用按名称找到工具，执行.invoke(args)，再把结果作为对应的工具消息交给模型。模型得到实际结果后才能组织自然语言答案。

模型也可能选错工具、漏参数或选择多个工具；本阶段验证的是定义与执行机制，不验证模型决策能力，也没有通过关键词规则假装实现模型自主选择。

## 核心执行流程

```text
创建CsvDataStore
  → build_tools把同一store绑定到五个工具
  → 工具接收参数字典（演示由脚本手工指定）
  → Pydantic验证字段、类型、格式和范围
  → run调用call_service
  → 原有Service校验业务参数并读取快照、筛选和计算
  → results模块包装原样Service结果为JSON字符串
  → 普通invoke返回字符串；tool_call形式invoke返回ToolMessage
```

工具工厂用一个小闭包保存store。闭包只是“内部函数记住外层变量”，不需要把数据对象作为模型输入，也不需要重新读取CSV。build_tools只注册能力，没有选工具、调度多步任务或循环调用LLM。

Service继续负责日期合法性、区间顺序、加权转化率、库存估算和评价计算。Tool负责公开输入契约、调用Service和转换边界错误。这样业务规则只有一份，服务测试可继续独立运行，也便于日后通过不同界面复用。

## 工具清单

| Tool | 输入 | 服务返回要点 |
|---|---|---|
| get_product_info | sku | 商品当前快照与历史限制 |
| get_sales_data | sku、start_date、end_date | 销售汇总、日期覆盖、缺失数据状态 |
| compare_sales_periods | sku、本期和前期各自起止日期 | 两期指标、变化率、百分点差、警告和日均指标 |
| get_inventory_data | sku、可选起止日期 | 期末库存、历史、可售天数及无法估算的原因 |
| get_review_data | sku、可选起止日期、low_rating_limit | 评价统计、评分差、低分内容与截断标记 |

日期schema只约束YYYY-MM-DD字符串形状，日期是否存在和先后关系仍由Service验证。SKU沿用Service的去空格、转大写处理。Pydantic设置strict=True与extra="forbid"，避免把字符串“5”或布尔值当整数，以及悄悄忽略多余参数。

默认日期沿用Service：结束日使用数据截止日，开始日为结束日前29天。描述中明确给出本快照截止日2026-09-22，避免模型日后误用电脑日期。更新数据后必须重新创建store和工具，并重新导出工具定义。

## 返回契约与错误边界

所有正常结果和可预期调用错误使用同一JSON外层：

```json
{
  "schema_version": "1.0",
  "tool": "get_product_info",
  "status": "not_found",
  "data": {
    "status": "not_found",
    "sku": "SKU999",
    "message": "当前数据源中没有找到该商品。",
    "product": null
  },
  "error": null
}
```

外层status镜像Service状态；data原样保留Service结果，不删掉coverage、warnings、limitations或null，不重新计算指标。error非空时status为error，data为null。status的稳定结构有助于后续模型区分数据缺失与调用失败，也便于应用和测试检查结果。

| 情况 | 工具行为 |
|---|---|
| 缺参数、多余参数、错误类型、超出数量限制 | invalid_arguments，提供出错字段，不调用Service |
| 日历错误、区间反转等Service ValueError | 转为ToolException，输出invalid_arguments与原有说明 |
| Service DataValidationError | 单独标记data_error，避免误判为模型参数问题 |
| 商品不存在、无数据、partial、insufficient_data | 属于执行成功后的业务结果，原样保留，不伪造数字 |
| 未预期RuntimeError、程序错误、不可JSON序列化输出 | 继续抛出，保留定位机会，不吞掉或伪装成正常答案 |

DataValidationError继承ValueError，所以必须先捕获前者。JSON使用allow_nan=False，避免将NaN/Infinity输出给模型。序列化放在捕获输入错误的代码块之外，防止坏输出被误报成“请模型改参数”。

store初始化失败属于应用准备阶段的问题，会直接报错；并不是已经创建的工具返回值。

使用包含type、id、name和args的tool_call调用时，LangChain会生成ToolMessage，tool_call_id对应原调用。执行成功但商品不存在时，消息执行状态可以是success，而JSON业务状态是not_found；这是两个不同层面的状态。参数或预期执行错误对应消息状态error。

稳定返回不等于模型必然理解正确。后续还需要系统提示词、模型能力与验收案例共同验证。

## 使用技术及原因

- langchain-core==1.6.4：提供StructuredTool、ToolException、ToolMessage。只使用核心工具能力，不安装完整langchain或LangGraph。
- pydantic==2.13.5：用少量BaseModel、Field、ConfigDict定义工具输入，并生成JSON Schema。这是输入参数校验，不是Phase 6的分析报告结构化输出。
- Python闭包：在应用内保存store，避免模型可见参数暴露路径或对象。
- JSON、unittest、unittest.mock：稳定输出、独立调用、验证委托次数与异常路径。

新增直接依赖只有LangChain Core和Pydantic；pip会安装它们的传递依赖，包括LangSmith库，但本项目没有配置追踪或接入LangSmith服务。依赖检查确认langgraph、完整langchain、chromadb和streamlit均未安装。requirements固定直接版本，并非全部传递依赖的完整锁文件。

## 实际问题与解决过程

| 问题 | 原因 | 定位过程 | 解决方式 |
|---|---|---|---|
| Python urllib查询PyPI元数据时SSL证书校验失败 | 该Python调用的默认TLS上下文无法建立本地证书信任链 | 错误栈为SSLCertVerificationError；随后pip依赖预检查正常成功 | 使用正常启用TLS校验的pip解析和安装依赖；没有关闭证书验证，也没有修改系统证书。仅绕开该次元数据查询，未声称修复urllib证书配置 |
| 首轮工具测试发生KeyError: additionalProperties | LangChain默认工具转换使用重建的tool_call_schema，丢失原Pydantic模型extra="forbid"对应的JSON标记 | 对照args_schema.model_json_schema、tool_call_schema.model_json_schema及已安装BaseTool相关实现；本地多余参数拒绝测试仍通过 | describe_tools直接以原始args_schema生成parameters，保留additionalProperties=false；重新执行57个测试全部通过 |

这里的导出修复适用于当前纯公开参数schema。后续模型接入应使用并核对该导出定义；若直接将工具对象交给其他转换器，不能假设该标记必然保留。未在本阶段通过子类改写LangChain内部行为，也未实现模型绑定。

## 测试结果

环境为项目独立.venv，Python 3.12.10、Pandas 2.3.3、LangChain Core 1.6.4、Pydantic 2.13.5。

首轮57个测试中有1个schema导出检查报错；修复后最终57个全部通过：原有38个保持通过，新增19个工具测试。pip check输出No broken requirements found。schema导出与手动工具演示成功。

新增测试覆盖真实StructuredTool与五个唯一名称、公开字段与私有对象隔离、每个工具只调用对应Service一次、服务结果完整保留、可选参数、未知SKU、空数据、部分区间、不完整比较、必填/额外/严格类型/限制校验、日期格式与Service日期规则、SKU标准化、ToolMessage调用ID和成功/错误状态、数据错误分类、未预期异常传播、NaN输出拒绝。

测试中的Mock用于确认调用次数和故意触发错误，不用于演示成功结果。正常演示与结果相等测试均读取真实的本地模拟CSV。

这些测试证明工具定义、验证和服务执行正确，不证明LLM能够自主选对工具；模型选择和Qwen适配留在Phase 4验证。

## 如何运行

在项目根目录、使用已有虚拟环境：

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m scripts.demo_tools --schemas-only
.venv/bin/python -m scripts.demo_tools
.venv/bin/python -m unittest discover -s tests -v
```

本机依赖已安装。其他环境需要第一条命令并联网；后续演示和测试无需模型API Key。预期：导出五项工具定义；演示打印五种业务结果、未知SKU、缺参数错误及人工构造tool_call的ToolMessage；测试显示Ran 57 tests和OK。

只运行本阶段测试可用 `.venv/bin/python -m unittest tests.test_tools -v`。需要更新工具定义快照时执行 `.venv/bin/python -m scripts.demo_tools --schemas-only > docs/tool_catalog.json`。

常见问题：找不到langchain_core/pydantic时，在正确虚拟环境安装requirements；找不到src时，在项目根目录按模块运行；工具返回invalid_arguments时按字段说明修正参数；data_error或未预期异常应检查数据或代码，不靠重试模型掩盖。

## 核心代码阅读顺序

1. scripts/demo_tools.py：先看构造工具、按名字选取、invoke和人工tool_call；明确每个例子的名字与参数是谁决定的。
2. src/tools/schemas.py：比较必填销售日期与可选库存日期，理解Field描述、strict和extra约束。
3. src/tools/factory.py：重点看_make_tool与build_tools；理解name/description/args_schema如何与已有Service连接，闭包怎样隐藏store。
4. src/tools/results.py：重点看call_service与validation_error_json；理解数据结果、参数错误和程序Bug的区别，以及为何原样保留Service结果。
5. tests/test_tools.py：重点读each_tool_calls_its_service_once、missing_arguments_rejected_before_service、tool_call_returns_correlated_success_message三处，理解测试如何证明调用链。

可以先观察docs/tool_catalog.json中的一个工具定义，再回到上述代码对照，不要求阅读所有依赖源码。

## 理解题

1. 普通Python函数成为Tool后，增加了什么？模型能直接读取函数源码或CSV吗？
2. name、description、参数schema分别解决什么问题？如果描述与函数实际能力不符，会发生什么？
3. 模型如何知道可用工具？为什么本阶段手动.invoke成功，不能证明模型会正确选工具？面试官可能追问：tool_call_id有什么用？
4. 工具为何只调用Service而不复制转化率或库存算法？store为什么不出现在参数schema里？
5. 商品不存在、缺少必填参数、程序RuntimeError分别如何处理？为什么必须区分业务status与ToolMessage执行status？

## 【参考答案】

1. 增加模型可见的名称、用途与参数契约，以及应用侧的统一调用和校验接口。模型通常只收到工具定义，不会自动读本地源码或CSV；实际数据由应用执行函数后返回。
2. name用于准确定位，description表达用途和边界，schema说明字段、类型和约束。描述与能力不符可能诱导模型误选工具或错误解释结果；输入校验只能约束格式，不能保证语义选择正确。
3. 应用在模型请求中提供工具定义或通过模型适配器绑定。当前工具名由演示代码指定，尚无模型参与选择。tool_call_id把返回消息与原始调用关联，多个调用时尤其重要。
4. 算法留在Service形成单一事实来源，避免两份实现口径分叉。store由应用控制并通过闭包持有，模型只需提供业务参数；让模型传对象或路径既没有必要，也会模糊数据边界。
5. 不存在商品是not_found业务结果；缺参数是invalid_arguments并阻止调用Service；未预期RuntimeError继续抛出供开发者定位。ToolMessage的success只表示工具执行成功，不代表查询一定找到数据或数据完整；仍须检查JSON中的业务status和coverage。

## 当前限制与下一阶段目标

当前是同步本地查询工具，没有LLM、自动选工具、多步Agent循环、重试调度、会话或知识检索。库存历史可能较长，尚未基于模型上下文预算裁剪；现阶段为保证证据完整原样返回，未来如裁剪必须显式说明。评价内容属于数据，描述中提醒不把它当作指令，但这不是完整的提示注入防护实现。

导出格式为通用function-calling定义，不代表已验证某个Qwen接口支持全部schema字段。Phase 4再核实模型与适配器兼容性，并验证真实工具选择与结果回传，继续遵守不用LangGraph的技术边界。

下一阶段只有在用户验收并明确要求后，才开始基础LangChain Agent。本阶段到此停止。

## Git变化摘要

新增src/tools下4个文件（__init__、schemas、results、factory）、scripts/demo_tools.py、tests/test_tools.py、docs/tool_catalog.json、docs/phase3_report.md。修改requirements.txt与README.md。原有Service、CSV及之前测试未变。

建议Commit Message：`feat: wrap product data services as langchain tools`。

尚未执行Commit。等待用户验收与明确提交授权。

## 核对资料

- [LangChain Tools官方说明](https://docs.langchain.com/oss/python/langchain/tools)：工具定义、参数schema与返回机制。
- [StructuredTool官方参考](https://reference.langchain.com/python/langchain-core/tools/structured/StructuredTool)：名称、描述、args_schema与函数封装接口。
- [LangChain Core发布信息](https://pypi.org/project/langchain-core/1.6.4/)及本地实际安装版本；实现和测试以本项目固定版本为准。
