"""应用服务层：串联网页搜索、SQLite、当前结果 CSV 导出和通用统计。"""

import csv
from pathlib import Path

from job_market_agent.analysis import build_analysis_rows, summarize
from job_market_agent.config import Settings
from job_market_agent.sources import bocha_search, demo_results
from job_market_agent.storage import SearchRepository
from job_market_agent.utils import now_text

RESULT_COLUMNS = [
    "source", "external_id", "category", "query", "title", "url", "site_name",
    "snippet", "summary", "published_at", "fetched_at", "raw_json",
]
CATEGORIES = {"jobs", "products", "general"}
FRESHNESS_VALUES = {"noLimit", "oneDay", "oneWeek", "oneMonth", "oneYear"}


class SearchService:
    """每个 CLI/Web 会话持有独立实例，导出严格使用本次搜索结果。"""

    def __init__(
        self,
        settings: Settings,
        repository: SearchRepository | None = None,
        export_dir: str = "exports",
    ):
        self.settings = settings
        self.repository = repository or SearchRepository(settings.db_path)
        self.export_dir = export_dir
        self.last_results: list[dict] = []
        self.last_query = ""
        self.last_category = "general"
        self.last_limit = 10
        self.last_freshness = "noLimit"
        self.last_mode = ""

    def _export_path(self, output_path: str, filename: str) -> Path:
        if output_path == f"exports/{filename}":
            output_path = str(Path(self.export_dir) / filename)
        return self.settings.output_path(output_path).with_suffix(".csv")

    def search(
        self,
        query: str,
        category: str = "general",
        limit: int = 10,
        freshness: str = "noLimit",
    ) -> tuple[list[dict], str]:
        query = query.strip()
        category = category.strip().lower()
        freshness = freshness.strip() or "noLimit"
        if not query:
            raise ValueError("搜索关键词不能为空")
        if category not in CATEGORIES:
            raise ValueError("category 只能是 jobs、products 或 general")
        if freshness not in FRESHNESS_VALUES:
            raise ValueError("freshness 取值无效")
        limit = max(1, min(int(limit), 50))
        source_mode = self.settings.search_source.strip().lower()
        if source_mode not in {"auto", "bocha", "demo"}:
            raise ValueError("SEARCH_SOURCE 只能是 auto、bocha 或 demo")

        self.last_results = []
        self.last_query = query
        self.last_category = category
        self.last_limit = limit
        self.last_freshness = freshness
        started_at = now_text()
        use_demo = source_mode == "demo" or (
            source_mode == "auto" and not self.settings.bocha_api_key.strip()
        )
        try:
            if use_demo:
                results = demo_results(query, category, limit)
                reason = "SEARCH_SOURCE=demo" if source_mode == "demo" else "未配置 BOCHA_API_KEY"
                mode = f"demo 演示数据（{reason}）"
            else:
                results = bocha_search(query, category, limit, freshness, self.settings)
                mode = "真实网页搜索（博查 API）"
        except (OSError, ValueError, TypeError) as exc:
            self.repository.record_run(
                "bocha", query, category, limit, freshness, started_at, "error", str(exc)
            )
            raise

        self.last_results = results
        self.last_mode = mode
        return results, mode

    def save(self) -> tuple[int, int, int]:
        if not self.last_results:
            raise ValueError("还没有搜索结果，请先 search_web")
        inserted, updated = self.repository.save_results(
            self.last_results, self.last_query, self.last_category,
            self.last_limit, self.last_freshness,
        )
        return inserted, updated, self.repository.count()

    def export_results(self, output_path: str = "exports/results.csv") -> tuple[Path, int]:
        if not self.last_results:
            raise ValueError("没有可导出的本次搜索结果，请先 search_web 再 save_results")
        real_path = self._export_path(output_path, "results.csv")
        with real_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=RESULT_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(self.last_results)
        return real_path, len(self.last_results)

    def analyze(self, output_path: str = "exports/analysis.csv"):
        if not self.last_results:
            raise ValueError("没有可分析的本次搜索结果，请先 search_web 并 save_results")
        real_path = self._export_path(output_path, "analysis.csv")
        analysis_rows = build_analysis_rows(self.last_results, self.last_query, self.last_category)
        with real_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["类别", "名称", "数值", "说明"])
            writer.writerows(analysis_rows)
        return real_path, summarize(self.last_results)
