from types import SimpleNamespace

from job_market_agent.intent import classify_intent, normalize_request, parse_json_object


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload

    def invoke(self, messages):
        return SimpleNamespace(content=self.payload)


class BrokenLLM:
    def invoke(self, messages):
        raise RuntimeError("offline")


def test_direct_keyword_is_search_without_confirmation():
    llm = FakeLLM('{"action":"direct_search","query":"Java 招聘","category":"jobs"}')
    result = classify_intent(llm, "帮我找 Java 岗位", {})
    assert result["action"] == "search"
    assert result["search_request"]["query"] == "Java 招聘"
    assert result["search_request"]["category"] == "jobs"
    assert result["pending_search"] == {}


def test_product_background_needs_confirmation():
    llm = FakeLLM(
        '{"action":"needs_confirmation","query":"降噪耳机",'
        '"category":"products","reason":"需要通勤降噪"}'
    )
    result = classify_intent(llm, "每天坐地铁，想买个能安静听歌的耳机", {})
    assert result["action"] == "needs_confirmation"
    assert result["search_request"]["query"] == "降噪耳机"
    assert result["search_request"]["category"] == "products"


def test_confirmation_uses_pending_request_without_llm():
    pending = {"query": "Python", "category": "jobs", "limit": 10, "freshness": "oneWeek"}
    result = classify_intent(None, "确认", pending)
    assert result["action"] == "search"
    assert result["search_request"] == pending
    assert result["pending_search"] == {}


def test_cancel_clears_pending_request():
    result = classify_intent(None, "取消搜索", {"query": "Java"})
    assert result["action"] == "cancel"
    assert result["pending_search"] == {}


def test_fallback_only_allows_short_keyword():
    result = classify_intent(BrokenLLM(), "计算机", {})
    assert result["action"] == "search"
    assert result["search_request"]["query"] == "计算机"


def test_parse_json_from_code_fence():
    data = parse_json_object('```json\n{"action":"chat","query":""}\n```')
    assert data == {"action": "chat", "query": ""}


def test_normalize_request_inherits_and_clamps():
    pending = {"query": "降噪耳机", "category": "products", "limit": 10, "freshness": "noLimit"}
    result = normalize_request({"limit": 99, "freshness": "oneWeek"}, pending)
    assert result == {
        "query": "降噪耳机", "category": "products", "limit": 50, "freshness": "oneWeek"
    }
