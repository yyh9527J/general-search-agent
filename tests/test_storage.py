from job_market_agent.sources import demo_results
from job_market_agent.storage import SearchRepository


def test_save_results_deduplicates_and_records_runs(tmp_path):
    repository = SearchRepository(tmp_path / "results.db")
    results = demo_results("Python 招聘", "jobs", 3)

    assert repository.save_results(results, "Python 招聘", "jobs", 3, "noLimit") == (3, 0)
    assert repository.save_results(results, "Python 招聘", "jobs", 3, "noLimit") == (0, 3)
    assert repository.count() == 3

    with repository.connect() as conn:
        runs = conn.execute(
            "SELECT source, query, category, result_limit, freshness, status FROM search_runs"
        ).fetchall()
    assert len(runs) == 2
    assert dict(runs[0]) == {
        "source": "demo", "query": "Python 招聘", "category": "jobs",
        "result_limit": 3, "freshness": "noLimit", "status": "ok",
    }


def test_list_results_limit(tmp_path):
    repository = SearchRepository(tmp_path / "results.db")
    repository.save_results(
        demo_results("机械键盘", "products", 4), "机械键盘", "products", 4, "noLimit"
    )
    assert len(repository.list_results(2)) == 2
