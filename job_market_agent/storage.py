"""SQLite 持久化：通用网页结果去重、更新和搜索运行记录。"""

import sqlite3
from pathlib import Path

from job_market_agent.utils import now_text

SCHEMA = """
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL, external_id TEXT NOT NULL,
    category TEXT NOT NULL, query TEXT NOT NULL,
    title TEXT NOT NULL, url TEXT NOT NULL,
    site_name TEXT, snippet TEXT, summary TEXT, published_at TEXT,
    fetched_at TEXT, first_seen_at TEXT, last_seen_at TEXT, raw_json TEXT,
    UNIQUE(source, external_id)
);
CREATE TABLE IF NOT EXISTS search_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT, query TEXT, category TEXT, result_limit INTEGER, freshness TEXT,
    started_at TEXT, finished_at TEXT, inserted INTEGER, updated INTEGER,
    status TEXT, error TEXT
);
"""


class SearchRepository:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def save_results(
        self,
        results: list[dict],
        query: str,
        category: str,
        limit: int,
        freshness: str,
    ) -> tuple[int, int]:
        if not results:
            raise ValueError("没有可保存的搜索结果")
        inserted = 0
        updated = 0
        started_at = now_text()
        with self.connect() as conn:
            for result in results:
                identity = (result["source"], result["external_id"])
                row = conn.execute(
                    "SELECT id FROM results WHERE source = ? AND external_id = ?", identity
                ).fetchone()
                values = (
                    result["category"], result["query"], result["title"], result["url"],
                    result.get("site_name", ""), result.get("snippet", ""),
                    result.get("summary", ""), result.get("published_at", ""),
                    result["fetched_at"], result.get("raw_json", ""), result["fetched_at"],
                )
                if row:
                    conn.execute(
                        """
                        UPDATE results SET category=?, query=?, title=?, url=?, site_name=?,
                            snippet=?, summary=?, published_at=?, fetched_at=?, raw_json=?,
                            last_seen_at=? WHERE source=? AND external_id=?
                        """,
                        (*values, *identity),
                    )
                    updated += 1
                else:
                    conn.execute(
                        """
                        INSERT INTO results (
                            source, external_id, category, query, title, url, site_name,
                            snippet, summary, published_at, fetched_at, raw_json,
                            first_seen_at, last_seen_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            *identity, result["category"], result["query"], result["title"],
                            result["url"], result.get("site_name", ""),
                            result.get("snippet", ""), result.get("summary", ""),
                            result.get("published_at", ""), result["fetched_at"],
                            result.get("raw_json", ""), result["fetched_at"],
                            result["fetched_at"],
                        ),
                    )
                    inserted += 1
            self._insert_run(
                conn, results[0]["source"], query, category, limit, freshness,
                started_at, inserted, updated, "ok", "",
            )
        return inserted, updated

    def record_run(
        self,
        source: str,
        query: str,
        category: str,
        limit: int,
        freshness: str,
        started_at: str,
        status: str,
        error: str = "",
    ) -> None:
        with self.connect() as conn:
            self._insert_run(
                conn, source, query, category, limit, freshness,
                started_at, 0, 0, status, error[:500],
            )

    @staticmethod
    def _insert_run(
        conn: sqlite3.Connection,
        source: str,
        query: str,
        category: str,
        limit: int,
        freshness: str,
        started_at: str,
        inserted: int,
        updated: int,
        status: str,
        error: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO search_runs (
                source, query, category, result_limit, freshness, started_at, finished_at,
                inserted, updated, status, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source, query, category, limit, freshness, started_at, now_text(),
                inserted, updated, status, error,
            ),
        )

    def count(self) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS total FROM results").fetchone()
        return int(row["total"])

    def list_results(self, limit: int | None = None) -> list[dict]:
        sql = "SELECT * FROM results ORDER BY id DESC"
        params = []
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]
