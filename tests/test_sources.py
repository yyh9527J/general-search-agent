import json
from types import SimpleNamespace

import pytest

from job_market_agent.config import Settings
from job_market_agent.sources import BOCHA_API_URL, bocha_search, demo_results
from job_market_agent.utils import clean_text, parse_int, path_get


class FakeResponse:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode("utf-8")
        self.headers = SimpleNamespace(get_content_charset=lambda: "utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return self.body


def install_response(monkeypatch, payload):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        return FakeResponse(payload)

    monkeypatch.setattr("job_market_agent.sources.urllib.request.urlopen", fake_urlopen)
    return calls


def test_demo_results_are_deterministic_and_have_provenance():
    first = demo_results("降噪耳机", "products", 5)
    second = demo_results("降噪耳机", "products", 5)
    assert len(first) == 5
    assert [row["external_id"] for row in first] == [row["external_id"] for row in second]
    assert all(row["source"] == "demo" for row in first)
    assert all(row["category"] == "products" for row in first)
    assert all(row["url"].startswith("https://demo.local/products/") for row in first)
    assert all("不代表真实网页" in row["snippet"] for row in first)


def test_bocha_request_and_response_mapping(monkeypatch):
    calls = install_response(
        monkeypatch,
        {
            "webPages": {
                "value": [
                    {
                        "id": "item-1",
                        "name": "示例商品",
                        "url": "https://example.com/product/1",
                        "siteName": "示例站点",
                        "snippet": "网页片段",
                        "summary": "网页摘要",
                        "datePublished": "2026-11-20T08:00:00Z",
                        "extra": "保留原记录",
                    }
                ]
            }
        },
    )
    settings = Settings(_env_file=None, bocha_api_key="test-bocha-key", search_timeout=7)
    rows = bocha_search("降噪耳机", "products", 3, "oneWeek", settings)

    assert len(calls) == 1
    request, timeout = calls[0]
    headers = {name.lower(): value for name, value in request.header_items()}
    assert request.full_url == BOCHA_API_URL
    assert request.get_method() == "POST"
    assert headers["authorization"] == "Bearer test-bocha-key"
    assert headers["content-type"] == "application/json"
    assert json.loads(request.data) == {
        "query": "降噪耳机", "freshness": "oneWeek", "summary": True, "count": 3
    }
    assert timeout == 7
    assert rows[0]["source"] == "bocha"
    assert rows[0]["title"] == "示例商品"
    assert rows[0]["site_name"] == "示例站点"
    assert rows[0]["summary"] == "网页摘要"
    assert rows[0]["published_at"] == "2026-11-20T08:00:00Z"
    assert json.loads(rows[0]["raw_json"])["extra"] == "保留原记录"


def test_bocha_missing_id_uses_url_hash_and_skips_incomplete_rows(monkeypatch):
    install_response(
        monkeypatch,
        {
            "webPages": {
                "value": [
                    {"name": "无 URL"}, {"name": "有效结果", "url": "https://example.com/a"}
                ]
            }
        },
    )
    settings = Settings(_env_file=None, bocha_api_key="test-key")
    rows = bocha_search("测试", "general", 5, "noLimit", settings)
    assert len(rows) == 1
    assert len(rows[0]["external_id"]) == 20
    assert rows[0]["site_name"] == "example.com"


def test_bocha_accepts_wrapped_data_payload(monkeypatch):
    install_response(
        monkeypatch,
        {
            "code": 200,
            "msg": None,
            "data": {
                "webPages": {
                    "value": [
                        {
                            "id": "wrapped-1",
                            "name": "包裹结构结果",
                            "url": "https://example.com/wrapped",
                            "siteName": "示例站点",
                        }
                    ]
                }
            },
        },
    )
    settings = Settings(_env_file=None, bocha_api_key="test-key")
    rows = bocha_search("测试", "general", 3, "noLimit", settings)
    assert [row["external_id"] for row in rows] == ["wrapped-1"]


def test_bocha_error_code_fails_explicitly(monkeypatch):
    install_response(monkeypatch, {"code": 403, "msg": "invalid api key", "data": None})
    settings = Settings(_env_file=None, bocha_api_key="bad-key")
    with pytest.raises(ValueError, match="invalid api key"):
        bocha_search("测试", "general", 3, "noLimit", settings)


def test_bocha_malformed_response_fails_explicitly(monkeypatch):
    install_response(monkeypatch, {"webPages": {}})
    settings = Settings(_env_file=None, bocha_api_key="test-key")
    with pytest.raises(TypeError, match="webPages.value"):
        bocha_search("测试", "general", 3, "noLimit", settings)


def test_bocha_requires_key():
    with pytest.raises(ValueError, match="BOCHA_API_KEY"):
        bocha_search("测试", "general", 3, "noLimit", Settings(_env_file=None))


def test_nested_path_get():
    payload = {"data": {"items": [{"site": {"name": "示例站点"}}]}}
    assert path_get(payload, "data.items.0.site.name") == "示例站点"
    assert path_get(payload, "data.items.1.site.name") is None


def test_text_and_number_normalization():
    assert clean_text("<p> Python &amp; SQL </p>") == "Python & SQL"
    assert parse_int("共 12 件") == 12
    assert parse_int("未知") is None
