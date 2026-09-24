"""Grounded multi-tool prompt with an explicit final JSON contract."""

import json

from src.models import AnalysisReport

from .basic import system_prompt


def analysis_system_prompt(as_of_date: str) -> str:
    schema = json.dumps(AnalysisReport.model_json_schema(), ensure_ascii=False)
    return system_prompt(as_of_date) + f"""

当前任务是单个SKU的综合分析。根据问题自主组合必要工具；不要固定调用全部工具。
分析最近表现时，优先用compare_sales_periods取得最近30天与之前30天的可比证据。
涉及评价变化时，再使用get_review_data；只有问题需要时才查询商品或库存。
综合结论必须区分三类内容：已确认数据事实、同期变化或相关性、现有数据无法证明的因果关系。
工具返回not_found、no_data、partial、insufficient_data或error时必须反映在报告中，不得补造数值。
至少成功调用一个相关业务工具后才能提交分析报告。

最终回复只能是一个符合下列JSON Schema的JSON对象，不要使用Markdown或附加解释：
{schema}

findings中的每项必须是工具已确认的事实；若写相关性，明确使用“同期”“相关”或“同时变化”等措辞。
summary和findings不要使用“导致”“驱动”“主要原因”“根因”“归因于”等因果措辞。
例如只能说“Sessions与销量同期下降，Conversion Rate相对稳定”，不能说“流量下降驱动销量下滑”。
evidence_limits必须写出当前数据不能证明的原因或数据限制；即使数据完整，也要说明不能据此确认外部原因或因果。
risk_level只允许low、medium、high、unknown；证据不足或商品不存在时使用unknown。
recommendations只能与findings直接对应，不能假装已查询运营知识库。
不要把工具没有提供的搜索排名、广告投放、活动曝光等信息写成已知事实。
"""


def analysis_structure_repair_prompt(error: str) -> str:
    """Request one format-only retry without changing evidence or using tools."""

    return f"""上一条最终答案未通过AnalysisReport校验：{error}
请仅修正JSON格式和字段，使其符合既定schema。
保留已经获得的工具事实，不新增数字、事实或因果判断，不再调用任何工具。
只输出一个JSON对象，不要输出Markdown或解释。"""
