"""LangGraph 编排：通用搜索意图确认门禁 + Agent 工具循环。"""

import logging
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from job_market_agent.config import Settings, load_settings
from job_market_agent.intent import classify_intent
from job_market_agent.llm import build_llm
from job_market_agent.prompts import SYSTEM_PROMPT
from job_market_agent.service import SearchService
from job_market_agent.tools import create_tools
from job_market_agent.utils import content_text

logger = logging.getLogger(__name__)


class State(TypedDict):
    messages: Annotated[list, add_messages]
    pending_search: dict
    action: str
    search_request: dict
    reason: str


def create_session() -> dict:
    return {"messages": [], "pending_search": {}}


def build_graph(
    settings: Settings | None = None, service: SearchService | None = None, llm=None
):
    settings = settings or load_settings()
    service = service or SearchService(settings)
    llm = llm or build_llm(settings)
    tools = create_tools(service)
    tools_by_name = {item.name: item for item in tools}
    llm_with_tools = llm.bind_tools(tools)

    def intent_node(state: State) -> dict:
        last = state["messages"][-1]
        decision = classify_intent(
            llm, content_text(last.content), state.get("pending_search", {})
        )
        logger.info("意图=%s 参数=%s", decision["action"], decision.get("search_request", {}))
        return decision

    def respond_node(state: State) -> dict:
        """不调用工具，只负责询问确认或处理取消。"""
        action = state.get("action", "chat")
        request = state.get("search_request", {})
        if action == "needs_confirmation" and request.get("query"):
            reason = state.get("reason") or "它与你的背景或使用需求最相关"
            category_labels = {"jobs": "招聘", "products": "商品", "general": "通用网页"}
            content = (
                "我先不急着搜索。根据你的描述，我建议使用以下条件：\n"
                f"- 查询词：{request['query']}\n"
                f"- 分类：{category_labels[request['category']]}\n"
                f"- 数量：{request['limit']} 条\n"
                f"- 时效：{request['freshness']}\n"
                f"- 判断依据：{reason}\n\n"
                "是否按这个条件搜索？回复“确认”即可；"
                "也可以直接说“换成机械键盘”或“改成最近一周，搜 5 条”。"
            )
            pending = request
        elif action == "needs_confirmation":
            content = "请补充你想搜索的主题、商品或岗位方向，我再帮你推断查询词。"
            pending = {}
        elif action == "cancel":
            content = "已取消这次搜索，没有调用搜索工具。你可以重新描述需求。"
            pending = {}
        else:
            content = "目前没有等待确认的搜索条件。你可以给我关键词，或描述你的需求。"
            pending = {}
        return {"messages": [AIMessage(content=content)], "pending_search": pending}

    def agent_node(state: State) -> dict:
        if state.get("action") == "search":
            request = state["search_request"]
            confirmed = SystemMessage(
                content=(
                    "搜索参数已确认，用户不需要再次被询问："
                    f"query={request['query']!r}, category={request['category']!r}, "
                    f"limit={request['limit']}, freshness={request['freshness']!r}。"
                    "第一步必须按这些参数调用 search_web，随后完成固定保存、导出和分析流程。"
                )
            )
            messages = [SystemMessage(content=SYSTEM_PROMPT), confirmed, *state["messages"]]
            response = llm_with_tools.invoke(messages)
        else:
            # 普通对话不绑定工具，从机制上防止未确认就搜索
            chat_prompt = SystemMessage(
                content=(
                    "你是通用网页搜索助手。当前输入没有被判定为已确认搜索，只回答用户问题。"
                    "若用户想搜集网页，可以请他提供关键词，或描述背景、需求和适用场景。"
                )
            )
            response = llm.invoke([chat_prompt, *state["messages"]])
        return {"messages": [response]}

    def tool_node(state: State) -> dict:
        outputs = []
        for call in getattr(state["messages"][-1], "tool_calls", []) or []:
            name = call.get("name", "")
            logger.info("调用工具=%s 参数=%s", name, call.get("args", {}))
            function = tools_by_name.get(name)
            if function is None:
                result = f"未知工具：{name}"
            else:
                try:
                    result = function.invoke(call.get("args", {}))
                except Exception as exc:  # noqa: BLE001 - 异常交还模型处理
                    result = f"工具 {name} 执行失败：{exc}"
            outputs.append(ToolMessage(content=str(result), tool_call_id=call.get("id")))
        return {"messages": outputs}

    def route_after_intent(state: State) -> str:
        if state.get("action") in {"needs_confirmation", "cancel", "no_pending"}:
            return "respond"
        return "agent"

    def should_continue(state: State) -> str:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    graph = StateGraph(State)
    graph.add_node("intent", intent_node)
    graph.add_node("respond", respond_node)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.add_edge(START, "intent")
    graph.add_conditional_edges(
        "intent", route_after_intent, {"respond": "respond", "agent": "agent"}
    )
    graph.add_edge("respond", END)
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile()


def run_turn(graph, session: dict, text: str, recursion_limit: int = 25) -> str:
    """执行一轮对话并更新 session；异常交给 CLI 统一展示。"""
    session["messages"].append(HumanMessage(content=text))
    result = graph.invoke(session, config={"recursion_limit": recursion_limit})
    session.clear()
    session.update(result)
    return content_text(session["messages"][-1].content)
