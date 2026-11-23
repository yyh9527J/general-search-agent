"""通用搜索结果的纯统计逻辑：不依赖模型、网络或数据库。"""

from collections import Counter
from datetime import datetime


def _parsed_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def summarize(rows: list[dict]) -> dict:
    sites = Counter(row.get("site_name") or "未知站点" for row in rows)
    sources = Counter(row.get("source") or "未知来源" for row in rows)
    categories = Counter(row.get("category") or "general" for row in rows)
    dated_rows = [row for row in rows if row.get("published_at")]
    parsed_dates = [
        (parsed.timestamp(), row["published_at"])
        for row in dated_rows
        if (parsed := _parsed_date(row["published_at"])) is not None
    ]
    return {
        "total": len(rows),
        "sources": sources,
        "sites": sites,
        "categories": categories,
        "published": len(dated_rows),
        "earliest_published": min(parsed_dates)[1] if parsed_dates else "",
        "latest_published": max(parsed_dates)[1] if parsed_dates else "",
    }


def build_analysis_rows(rows: list[dict], query: str, category: str) -> list[list]:
    """整理为类别、名称、数值、说明四列，方便 Excel 直接打开。"""
    summary = summarize(rows)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    coverage = round(summary["published"] / summary["total"] * 100, 1) if rows else 0
    result = [
        ["总览", "结果总数", summary["total"], f"查询：{query}；生成时间：{generated_at}"],
        ["总览", "来源数量", len(summary["sources"]), f"结果分类：{category}"],
        ["总览", "网站数量", len(summary["sites"]), "按 site_name 统计"],
        [
            "总览", "含发布时间的记录", summary["published"],
            f"发布时间覆盖率 {coverage}%；缺失时间不按 0 或当前时间补写",
        ],
    ]
    if summary["earliest_published"]:
        result.append(
            [
                "总览", "可解析发布时间范围",
                f"{summary['earliest_published']} 至 {summary['latest_published']}",
                "仅统计来源实际提供且可解析的发布时间",
            ]
        )
    for name, value in summary["sources"].most_common():
        result.append(["数据来源", name, value, "结果数；完整 URL 见 results.csv"])
    for name, value in summary["categories"].most_common():
        result.append(["结果分类", name, value, "结果数"])
    for name, value in summary["sites"].most_common(10):
        result.append(["主要站点", name, value, "结果数"])
    return result
