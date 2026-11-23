"""通用网页数据源：博查 Web Search API 与明确标识的离线演示数据。"""

import hashlib
import json
import urllib.parse
import urllib.request

from job_market_agent.config import Settings
from job_market_agent.utils import clean_text, now_text

BOCHA_API_URL = "https://api.bochaai.com/v1/web-search"
RESULT_SUFFIXES = ["相关信息汇总", "热门网页推荐", "实用资料参考", "最新内容摘录", "相关结果精选"]


def demo_results(query: str, category: str = "general", limit: int = 10) -> list[dict]:
    """生成离线合成结果；所有记录均使用 source=demo 和 demo.local 域名。"""
    query = query.strip() or "通用搜索"
    limit = max(1, min(int(limit), 50))
    slug = hashlib.sha1(f"{category}:{query}".encode()).hexdigest()[:10]
    fetched_at = now_text()
    results = []
    for index in range(limit):
        title = f"{query}：{RESULT_SUFFIXES[index % len(RESULT_SUFFIXES)]} {index + 1}"
        url = f"https://demo.local/{category}/{slug}-{index + 1:03d}"
        snippet = f"关于“{query}”的离线演示摘要 {index + 1}，不代表真实网页内容。"
        raw = {"demo": True, "title": title, "url": url, "snippet": snippet}
        results.append(
            {
                "source": "demo",
                "external_id": f"demo-{slug}-{index + 1:03d}",
                "category": category,
                "query": query,
                "title": title,
                "url": url,
                "site_name": "演示站点",
                "snippet": snippet,
                "summary": "本记录仅用于验证搜索、保存、导出与分析流程，未访问互联网。",
                "published_at": "",
                "fetched_at": fetched_at,
                "raw_json": json.dumps(raw, ensure_ascii=False),
            }
        )
    return results


def bocha_search(
    query: str,
    category: str,
    limit: int,
    freshness: str,
    settings: Settings,
) -> list[dict]:
    """调用博查网页搜索，保留来源字段与单条原始响应，不生成缺失信息。"""
    if not settings.bocha_api_key.strip():
        raise ValueError("未配置 BOCHA_API_KEY，无法使用真实网页搜索")

    body = json.dumps(
        {"query": query, "freshness": freshness, "summary": True, "count": limit},
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        BOCHA_API_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {settings.bocha_api_key.strip()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "general-search-agent/0.1",
        },
    )
    with urllib.request.urlopen(request, timeout=settings.search_timeout) as response:  # noqa: S310
        charset = response.headers.get_content_charset() or "utf-8"
        payload = json.loads(response.read().decode(charset, errors="replace"))

    if not isinstance(payload, dict):
        raise TypeError("博查接口响应不是 JSON 对象")
    code = payload.get("code")
    if code is not None and str(code) != "200":
        message = clean_text(payload.get("msg")) or "未提供错误信息"
        raise ValueError(f"博查接口返回错误 code={code}：{message}")
    # 官方响应为 {code, msg, data:{webPages:{value:[...]}}}，同时兼容直接返回 webPages 的形式
    container = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    web_pages = container.get("webPages")
    items = web_pages.get("value") if isinstance(web_pages, dict) else None
    if not isinstance(items, list):
        raise TypeError("博查接口响应缺少 data.webPages.value 列表")

    fetched_at = now_text()
    results = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        title = clean_text(item.get("name"))
        url = clean_text(item.get("url"))
        if not title or not url:
            continue
        external_id = clean_text(item.get("id")) or hashlib.sha1(
            url.encode("utf-8")
        ).hexdigest()[:20]
        if external_id in seen:
            continue
        seen.add(external_id)
        results.append(
            {
                "source": "bocha",
                "external_id": external_id,
                "category": category,
                "query": query,
                "title": title,
                "url": url,
                "site_name": clean_text(item.get("siteName"))
                or urllib.parse.urlparse(url).netloc,
                "snippet": clean_text(item.get("snippet")),
                "summary": clean_text(item.get("summary")),
                "published_at": clean_text(item.get("datePublished")),
                "fetched_at": fetched_at,
                "raw_json": json.dumps(item, ensure_ascii=False),
            }
        )
    if not results:
        raise ValueError("博查接口没有返回包含标题和完整 URL 的网页结果")
    return results
