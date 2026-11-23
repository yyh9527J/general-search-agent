"""意图识别：区分直接关键词、明确搜索要求、背景需求与确认回复。"""

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from job_market_agent.prompts import INTENT_PROMPT
from job_market_agent.utils import content_text

CONFIRM_WORDS = {
    "确认", "确认搜索", "可以", "可以搜", "可以搜吧", "好", "好的", "好的搜吧",
    "行", "对", "是", "嗯", "按这个搜", "按这个搜索", "就这样", "开始搜索",
}
CANCEL_WORDS = {"取消", "取消搜索", "不用了", "先不搜", "不搜索", "算了"}
CATEGORIES = {"jobs", "products", "general"}
FRESHNESS_VALUES = {"noLimit", "oneDay", "oneWeek", "oneMonth", "oneYear"}


def parse_json_object(content) -> dict:
    """从模型回复中提取 JSON 对象，容忍 ```json 代码块。"""
    text = content_text(content).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        value = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def normalize_request(data: dict, pending: dict | None = None) -> dict:
    """补齐搜索参数；修改待确认条件时继承未提及的旧字段。"""
    pending = pending or {}
    query = str(data.get("query") or pending.get("query") or "").strip()
    category = str(data.get("category") or pending.get("category") or "general").lower()
    if category not in CATEGORIES:
        category = "general"
    freshness = str(data.get("freshness") or pending.get("freshness") or "noLimit")
    if freshness not in FRESHNESS_VALUES:
        freshness = "noLimit"
    try:
        limit = int(data.get("limit") or pending.get("limit") or 10)
    except (TypeError, ValueError):
        limit = 10
    return {
        "query": query, "category": category,
        "limit": max(1, min(limit, 50)), "freshness": freshness,
    }


def classify_intent(llm, text: str, pending: dict) -> dict:
    """返回 action、search_request、reason，以及需要清理的 pending_search。"""
    normalized = re.sub(r"[\s，。！!？?]+", "", text).lower()
    if pending and normalized in CONFIRM_WORDS:
        return {
            "action": "search", "search_request": normalize_request({}, pending),
            "pending_search": {}, "reason": "用户已确认推断条件",
        }
    if pending and normalized in CANCEL_WORDS:
        return {"action": "cancel", "pending_search": {}}

    prompt = (
        f"当前待确认条件：{json.dumps(pending, ensure_ascii=False)}\n"
        f"本轮用户输入：{text}"
    )
    try:
        response = llm.invoke(
            [SystemMessage(content=INTENT_PROMPT), HumanMessage(content=prompt)]
        )
        data = parse_json_object(response.content)
    except Exception:  # noqa: BLE001 - 识别失败时保守处理，不擅自搜索
        data = {}

    action = str(data.get("action") or "chat")
    request = normalize_request(data, pending)
    reason = str(data.get("reason") or "").strip()

    if action == "direct_search":
        action = "search"
    elif action == "confirm":
        action = "search" if pending else "no_pending"
        if pending:
            request = normalize_request({}, pending)
    elif action not in {"needs_confirmation", "cancel", "chat"}:
        action = "chat"

    # 模型输出异常时，只对短关键词保守直通
    if action == "chat" and not data:
        compact = text.strip()
        if len(compact) <= 20 and not re.search(r"[？?]|我|想找|推荐|适合|情况|毕业", compact):
            return {
                "action": "search",
                "search_request": normalize_request({"query": compact}, pending),
                "pending_search": {}, "reason": "输入是明确关键词",
            }

    if action == "search" and not request["query"]:
        action = "needs_confirmation"
    result = {"action": action, "search_request": request, "reason": reason}
    if action in {"search", "cancel", "no_pending"}:
        result["pending_search"] = {}
    return result
