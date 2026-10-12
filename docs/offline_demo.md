# 可复现离线 Demo

在项目根目录运行：

```bash
.venv/bin/python -m scripts.demo_phase9
```

脚本显式注入 `LocalHashEmbeddings`、本地 CSV 数据和脚本化 Fake Model。它会运行两轮同一 Agent：第一轮查询 SKU003 库存；第二轮用“它”追问库存可售时间，并触发当前轮库存工具查询和运营知识 RAG 检索。输出包含真实本地工具调用状态、库存结果和检索片段，并显示 Memory 保留的轮数。

此 Demo 不读取 `.env` 或环境变量中的云端 Provider 配置，不创建 Chat 客户端，也不发送网络请求。Fake Model 固定选择演示工具并返回固定说明文本，因此它验证的是本地 Agent/Tool/RAG/Memory 控制流，不代表真实模型理解、工具选择或答案质量。示例库存查询的 `days_of_supply` 可能为 `null`；这是 Service 对当前数据窗口/计算条件的真实返回，演示不补造估算值。若要演示真实 LLM 问答，需使用项目的 `scripts.run_agent` 并自行配置 Chat API；这不属于离线 Demo。
