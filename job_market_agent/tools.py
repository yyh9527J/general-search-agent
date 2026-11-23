"""LangChain 工具层：通用搜索、保存、导出、统计和结果格式化。"""

from datetime import datetime

from langchain_core.tools import tool

from job_market_agent.service import SearchService


def _result_lines(results: list[dict]) -> list[str]:
    lines = []
    for index, result in enumerate(results[:5], 1):
        summary = result.get("summary") or result.get("snippet") or "来源未提供摘要"
        lines.append(
            f"{index}. {result['title']} | 站点：{result.get('site_name') or '来源未提供'}"
        )
        lines.append(f"   摘要：{summary}")
        lines.append(f"   出处：{result.get('url') or '来源未提供 URL'}")
    return lines


def create_tools(service: SearchService) -> list:
    @tool
    def search_web(
        query: str,
        category: str = "general",
        limit: int = 10,
        freshness: str = "noLimit",
    ) -> str:
        """搜索公开网页，并缓存结果供 save_results 使用。

        Args:
            query: 网页搜索查询词，例如 "Python 招聘"、"降噪耳机"。
            category: 只能是 jobs、products 或 general。
            limit: 返回条数，1-50。
            freshness: noLimit、oneDay、oneWeek、oneMonth 或 oneYear。
        """
        try:
            results, mode = service.search(query, category, limit, freshness)
        except (OSError, ValueError, TypeError) as exc:
            return f"搜索失败：{exc}。未使用演示数据替代真实接口失败。"
        lines = [
            f"搜索完成：{len(results)} 条；数据源：{mode}",
            f"查询：{query}；分类：{category}；时效：{freshness}",
            f"前 {min(5, len(results))} 条（每条都带完整出处 URL）：",
            *_result_lines(results),
            "下一步调用 save_results，再导出 results.csv 和 analysis.csv。",
        ]
        return "\n".join(lines)

    @tool
    def save_results() -> str:
        """把最近一次 search_web 的结果写入 SQLite，按来源和外部 ID 去重。"""
        try:
            inserted, updated, total = service.save()
        except ValueError as exc:
            return str(exc)
        return (
            f"入库完成：新增 {inserted} 条，更新 {updated} 条；"
            f"数据库：{service.settings.db_path}；当前共 {total} 条"
        )

    @tool
    def export_results_csv(output_path: str = "exports/results.csv") -> str:
        """只把最近一次搜索结果导出为 results.csv，不回退导出整个数据库。"""
        try:
            path, count = service.export_results(output_path)
        except ValueError as exc:
            return f"导出失败：{exc}"
        return f"已导出 {count} 条到 {path}"

    @tool
    def analyze_results(output_path: str = "exports/analysis.csv") -> str:
        """统计最近搜索结果的来源、站点、分类和发布时间并生成 analysis.csv。"""
        try:
            path, summary = service.analyze(output_path)
        except ValueError as exc:
            return f"分析失败：{exc}"
        top_sites = "、".join(
            f"{name}({value})" for name, value in summary["sites"].most_common(3)
        )
        lines = [
            f"统计分析表已生成：{path}",
            (
                f"共 {summary['total']} 条，{len(summary['sites'])} 个站点；"
                f"含发布时间 {summary['published']} 条；主要站点：{top_sites or '无'}"
            ),
            f"数据源：{service.last_mode or '、'.join(summary['sources'])}",
            "最终回复必须引用以下结果，并逐条保留摘要和完整出处 URL：",
            *_result_lines(service.last_results),
        ]
        return "\n".join(lines)

    @tool
    def show_saved_results(limit: int = 10) -> str:
        """查看数据库中已保存的网页结果，默认最近 10 条。"""
        rows = service.repository.list_results(max(1, min(int(limit), 50)))
        if not rows:
            return "数据库里还没有数据"
        lines = [f"数据库共 {service.repository.count()} 条，最近 {len(rows)} 条："]
        for row in rows:
            lines.append(
                f"- [{row['source']}] {row['title']} | {row.get('site_name') or '未知站点'} | "
                f"来源：{row['url']}"
            )
        return "\n".join(lines)

    @tool
    def get_current_datetime() -> str:
        """获取当前日期和时间。"""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return [
        search_web, save_results, export_results_csv,
        analyze_results, show_saved_results, get_current_datetime,
    ]
