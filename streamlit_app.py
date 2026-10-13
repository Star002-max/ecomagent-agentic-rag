"""Local Streamlit UI for the real EcomAgent Qwen Agent and CSV dashboard."""

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from src.agent.memory import ConversationMemory
from src.agent.model import ModelRequestError, create_model
from src.agent.runner import AgentExecutionError, AgentResult, ProductAgent
from src.config import (EmbeddingSettings, Settings, load_embedding_settings,
                        load_settings)
from src.rag import KnowledgeBase, build_knowledge_base
from src.services import (CsvDataStore, get_inventory_data, get_review_data,
                          get_sales_data)
from src.tools import build_tools


@dataclass
class AgentRuntime:
    """Objects shared across Streamlit reruns for one browser session."""

    chat_settings: Settings
    embedding_settings: EmbeddingSettings
    model: object
    store: CsvDataStore
    knowledge_base: KnowledgeBase
    tools: list
    memory: ConversationMemory
    agent: ProductAgent

    def clear_memory(self) -> None:
        self.memory = ConversationMemory()
        self.agent = ProductAgent(
            self.model, self.tools, self.store.as_of_date,
            api_key=self.chat_settings.api_key, memory=self.memory,
        )


def build_runtime(provider: str, store: CsvDataStore | None = None) -> AgentRuntime:
    """Build a real configured Chat Agent and the selected RAG provider."""
    chat_settings = load_settings()
    embedding_settings = load_embedding_settings(provider_override=provider)
    data_store = store or CsvDataStore()
    model = create_model(chat_settings)
    knowledge_base = build_knowledge_base(settings=embedding_settings)
    tools = build_tools(data_store, knowledge_base)
    memory = ConversationMemory()
    agent = ProductAgent(model, tools, data_store.as_of_date,
                         api_key=chat_settings.api_key, memory=memory)
    return AgentRuntime(chat_settings, embedding_settings, model, data_store,
                        knowledge_base, tools, memory, agent)


def _render_tool_calls(tool_calls: list[dict]) -> None:
    if not tool_calls:
        st.caption("本轮没有返回 Tool 调用记录。")
        return
    for index, call in enumerate(tool_calls, start=1):
        result = call.get("result") or {}
        name = call.get("name", "unknown_tool")
        with st.expander(f"Tool {index}: {name} · {call.get('execution_status', 'unknown')}"):
            st.write("参数")
            st.json(call.get("arguments", {}))
            if name == "search_operation_knowledge":
                data = result.get("data") or {}
                st.caption(f"检索问题：{data.get('query', '')}")
                matches = data.get("matches", [])
                if matches:
                    for match_number, match in enumerate(matches, start=1):
                        st.markdown(
                            f"**证据 {match_number} · {match.get('source', '未知来源')} · "
                            f"{match.get('section') or '未标注章节'}**"
                        )
                        st.markdown(match.get("content", ""))
                else:
                    st.info("该次 RAG 调用没有返回匹配片段。")
            st.write("实际 Tool 返回")
            st.json(result)


def _render_chat(runtime: AgentRuntime | None, active_provider: str) -> None:
    st.subheader("AI Chat")
    if runtime is None:
        st.info("Chat Agent 尚未就绪。请先在侧栏检查配置并初始化 Provider。")
        return

    history_key = f"chat_history_{active_provider}"
    history = st.session_state.setdefault(history_key, [])
    for turn in history:
        with st.chat_message(turn["role"]):
            st.markdown(turn["content"])
            if turn["role"] == "assistant":
                st.caption(
                    f"状态：{turn.get('status', 'unknown')} · "
                    f"模型调用：{turn.get('model_calls', '未知')}"
                )
                _render_tool_calls(turn.get("tool_calls", []))

    if st.button("清空会话", key="clear_chat", disabled=not history):
        runtime.clear_memory()
        st.session_state[history_key] = []
        st.session_state["last_api_status"] = "尚未调用"
        st.rerun()

    # This function runs inside st.tabs(); st.bottom keeps the composer docked
    # to the app viewport instead of placing it after the tab's chat history.
    question = st.bottom.chat_input("输入商品、销售、库存或运营规则问题")
    if not question:
        return

    history.append({"role": "user", "content": question})
    st.session_state["last_api_status"] = "Qwen Chat 请求进行中"
    with st.chat_message("user"):
        st.markdown(question)
    try:
        with st.chat_message("assistant"):
            with st.spinner("正在调用配置的 Qwen Agent…"):
                result: AgentResult = runtime.agent.run(question)
            st.markdown(result.answer)
            st.caption(f"状态：{result.status} · Qwen 模型调用：{result.model_calls}")
            _render_tool_calls(result.tool_calls)
        history.append({"role": "assistant", "content": result.answer,
                        "status": result.status, "model_calls": result.model_calls,
                        "tool_calls": result.tool_calls})
        st.session_state["last_api_status"] = (
            f"已完成 · {result.model_calls} 次模型调用 · "
            f"{len(result.tool_calls)} 次 Tool 调用 · {active_provider} Embedding"
        )
    except (ModelRequestError, AgentExecutionError, ValueError) as exc:
        message = str(exc)  # Existing model and embedding boundaries redact credentials.
        history.append({"role": "assistant", "content": f"请求失败：{message}",
                        "status": "error", "model_calls": "未知", "tool_calls": []})
        st.session_state["last_api_status"] = f"请求失败 · {type(exc).__name__}"
        with st.chat_message("assistant"):
            st.error(message)
            st.caption("失败轮次不会写入 ConversationMemory；本轮未返回 AgentResult 工具轨迹。")
    except Exception as exc:
        # Do not render a traceback or arbitrary exception text in the browser.
        history.append({"role": "assistant", "content": "请求失败：内部错误，请检查本地应用日志。",
                        "status": "error", "model_calls": "未知", "tool_calls": []})
        st.session_state["last_api_status"] = f"请求失败 · {type(exc).__name__}"
        with st.chat_message("assistant"):
            st.error("内部错误。为避免暴露配置或请求细节，页面不显示异常堆栈。")
            st.caption("失败轮次不会写入 ConversationMemory。")


def _render_dashboard(store: CsvDataStore) -> None:
    st.subheader("电商数据 Dashboard")
    products = store.table("products").sort_values("sku")
    sku_options = products["sku"].tolist()
    sku = st.selectbox("SKU", sku_options, format_func=lambda value: (
        f"{value} · " + products.loc[products["sku"].eq(value), "product_name"].iloc[0]
    ))

    sales_table = store.table("sales")
    min_date = sales_table["date"].min().date()
    max_date = store.as_of_date
    max_day = date.fromisoformat(max_date)
    start_default = max(min_date, max_day - timedelta(days=29))
    selected = st.date_input("统计区间", value=(start_default, max_day),
                             min_value=min_date, max_value=max_day)
    if not isinstance(selected, (tuple, list)) or len(selected) != 2:
        st.info("请选择起止日期。")
        return
    start, end = selected
    if start > end:
        st.error("起始日期不能晚于结束日期。")
        return
    start_text, end_text = start.isoformat(), end.isoformat()

    inventory = get_inventory_data(store, sku, start_text, end_text)
    sales = get_sales_data(store, sku, start_text, end_text)
    reviews = get_review_data(store, sku, start_text, end_text)
    sales_metrics = sales.get("metrics") or {}
    review_metrics = reviews.get("metrics") or {}

    st.caption(f"数据截止日：{store.as_of_date} · 区间状态：库存 {inventory['status']} / "
               f"销售 {sales['status']} / 评价 {reviews['status']}")
    inventory_days = inventory.get("estimated_stock_days")
    stock_label = f"{inventory_days:.2f} 天" if inventory_days is not None else "不可估算"
    columns = st.columns(4)
    columns[0].metric("期末库存", inventory.get("current_inventory")
                      if inventory.get("current_inventory") is not None else "无记录")
    columns[1].metric("估算可售天数", stock_label)
    columns[2].metric("销售额", f"¥{sales_metrics['revenue']:,.2f}"
                      if sales_metrics.get("revenue") is not None else "无数据")
    rating = review_metrics.get("average_rating")
    columns[3].metric("平均评分", f"{rating:.2f} / 5" if rating is not None else "无数据")
    sales_columns = st.columns(4)
    sales_columns[0].metric("销量", sales_metrics.get("units", "无数据"))
    sales_columns[1].metric("订单", sales_metrics.get("orders", "无数据"))
    sales_columns[2].metric("访问量", sales_metrics.get("sessions", "无数据"))
    conversion = sales_metrics.get("conversion_rate")
    sales_columns[3].metric("转化率", f"{conversion:.2%}" if conversion is not None else "无数据")
    if inventory.get("estimate_unavailable_reason"):
        st.caption(f"可售天数不可用原因：{inventory['estimate_unavailable_reason']}")

    st.markdown("#### 销售趋势（CSV 日记录）")
    selected_sales = sales_table[
        sales_table["sku"].eq(sku)
        & sales_table["date"].between(pd.Timestamp(start), pd.Timestamp(end))
    ].set_index("date")
    if selected_sales.empty:
        st.info("此区间没有销售日记录。")
    else:
        st.line_chart(selected_sales[["revenue", "units"]])

    left, right = st.columns(2)
    with left:
        st.markdown("#### 库存趋势（Service 返回）")
        inventory_history = inventory.get("history") or []
        if inventory_history:
            inventory_chart = pd.DataFrame(inventory_history).set_index("date")
            st.line_chart(inventory_chart[["inventory"]])
        else:
            st.info("此区间没有库存日记录。")
    with right:
        st.markdown("#### 评价趋势（CSV 日记录）")
        review_table = store.table("reviews")
        selected_reviews = review_table[
            review_table["sku"].eq(sku)
            & review_table["date"].between(pd.Timestamp(start), pd.Timestamp(end))
        ]
        if selected_reviews.empty:
            st.info("此区间没有评价记录。")
        else:
            daily_rating = selected_reviews.groupby("date")["rating"].mean().to_frame()
            st.line_chart(daily_rating)

    st.markdown("#### 评价摘要")
    review_columns = st.columns(3)
    review_columns[0].metric("评价数", review_metrics.get("review_count", 0))
    review_columns[1].metric("低分评价数（≤2）", review_metrics.get("low_rating_count", 0))
    change = reviews.get("rating_change")
    review_columns[2].metric("对比前一等长区间评分变化",
                             f"{change:+.2f}" if change is not None else "不可比较")
    if reviews.get("comparison_status") != "ok":
        st.caption("评分变化不可比较：当前或前一等长区间超出可比较数据范围。")


def main() -> None:
    st.set_page_config(page_title="EcomAgent", page_icon="🛍️", layout="wide")
    st.title("EcomAgent · AI 商品分析")
    st.caption("真实 Qwen Agent + 本地 CSV Service + RAG；浏览器仅连接本机 Streamlit 服务。")

    if "agent_runtimes" not in st.session_state:
        st.session_state["agent_runtimes"] = {}
    if "last_api_status" not in st.session_state:
        st.session_state["last_api_status"] = "尚未调用"
    if "dashboard_store" not in st.session_state:
        try:
            st.session_state["dashboard_store"] = CsvDataStore()
        except Exception as exc:
            st.error(f"无法加载本地 CSV 数据：{type(exc).__name__}")
            return
    store: CsvDataStore = st.session_state["dashboard_store"]

    with st.sidebar:
        st.header("运行配置")
        try:
            chat_settings = load_settings()
            st.write(f"Chat 模型：`{chat_settings.model}`")
            st.caption("Chat 配置已读取（密钥不显示）；发送消息时才会请求模型 API。")
        except ValueError as exc:
            chat_settings = None
            st.error(str(exc))
        provider = st.radio("RAG Embedding Provider", ["local_hash", "aliyun"],
                            format_func=lambda value: (
                                "LocalHash（离线默认）" if value == "local_hash"
                                else "Aliyun text-embedding-v4（1024维）"
                            ), key="embedding_provider")
        runtimes: dict[str, AgentRuntime] = st.session_state["agent_runtimes"]
        if provider == "aliyun":
            st.warning("Aliyun 初始化会为知识库建立向量索引并调用 Embedding API；后续每次 RAG "
                       "查询也会调用 API，可能产生费用。索引会缓存在当前浏览器会话。")
            runtime = runtimes.get("aliyun")
            if runtime is None:
                confirmed = st.checkbox("我确认初始化 Aliyun Embedding 索引可能产生费用。")
                if st.button("确认并初始化 Aliyun", disabled=not confirmed,
                             key="initialize_aliyun"):
                    try:
                        with st.spinner("正在建立 Aliyun 向量索引…"):
                            runtime = build_runtime("aliyun", store)
                        runtimes["aliyun"] = runtime
                        st.session_state["chat_history_aliyun"] = []
                        st.session_state["last_api_status"] = "索引已建立；尚未发送 Chat 请求"
                        st.rerun()
                    except (ModelRequestError, ValueError) as exc:
                        st.error(str(exc))
                        runtime = None
                    except Exception as exc:
                        st.error(f"Aliyun 初始化失败：{type(exc).__name__}。页面未显示异常详情。")
                        runtime = None
        else:
            runtime = runtimes.get("local_hash")
            if runtime is None and chat_settings is not None:
                try:
                    with st.spinner("正在准备本地 Agent 和离线知识索引…"):
                        runtime = build_runtime("local_hash", store)
                    runtimes["local_hash"] = runtime
                except (ModelRequestError, ValueError) as exc:
                    st.error(str(exc))
                    runtime = None
                except Exception as exc:
                    st.error(f"本地 Agent 初始化失败：{type(exc).__name__}。")
                    runtime = None

        st.caption(f"当前会话 API 状态：{st.session_state['last_api_status']}")
        if provider == "local_hash":
            st.info("LocalHash 不调用 Embedding API。发送 Chat 问题仍会调用真实 Chat 模型并可能产生费用。")
        if runtime is not None:
            st.caption(f"已就绪：真实 ProductAgent · Chat `{runtime.chat_settings.model}` · "
                       f"Embedding `{runtime.embedding_settings.provider}`")

    chat_tab, dashboard_tab = st.tabs(["AI Chat", "Dashboard"])
    with chat_tab:
        active_runtime = st.session_state["agent_runtimes"].get(provider)
        _render_chat(active_runtime, provider)
    with dashboard_tab:
        _render_dashboard(store)


if __name__ == "__main__":
    main()
