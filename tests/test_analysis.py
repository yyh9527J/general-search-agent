from job_market_agent.analysis import build_analysis_rows, summarize


def sample_rows():
    return [
        {
            "title": "Python 工程师", "source": "bocha", "category": "jobs",
            "site_name": "甲站点", "published_at": "2026-11-20T08:00:00Z",
        },
        {
            "title": "降噪耳机", "source": "bocha", "category": "products",
            "site_name": "乙站点", "published_at": "",
        },
        {
            "title": "Python 后端", "source": "demo", "category": "jobs",
            "site_name": "甲站点", "published_at": "2026-11-21",
        },
    ]


def test_summary_covers_sources_sites_categories_and_dates():
    summary = summarize(sample_rows())
    assert summary["total"] == 3
    assert summary["published"] == 2
    assert summary["sources"]["bocha"] == 2
    assert summary["sites"]["甲站点"] == 2
    assert summary["categories"]["jobs"] == 2
    assert summary["earliest_published"] == "2026-11-20T08:00:00Z"
    assert summary["latest_published"] == "2026-11-21"


def test_analysis_rows_have_stable_table_shape():
    rows = build_analysis_rows(sample_rows(), "Python", "general")
    assert rows[0][0:3] == ["总览", "结果总数", 3]
    assert all(len(row) == 4 for row in rows)
    assert any(row[0] == "主要站点" and row[1] == "甲站点" for row in rows)
