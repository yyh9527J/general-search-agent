import csv

import pytest

from job_market_agent.tools import create_tools


def test_service_search_save_export_and_analyze(service):
    results, mode = service.search("Python 招聘", "jobs", 4, "oneWeek")
    assert len(results) == 4
    assert "demo" in mode
    assert service.save() == (4, 0, 4)

    results_path, result_count = service.export_results()
    analysis_path, summary = service.analyze()
    assert result_count == 4
    assert summary["total"] == 4
    assert results_path.name == "results.csv"
    assert analysis_path.name == "analysis.csv"

    with results_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 4
    assert rows[0]["url"].startswith("https://demo.local/jobs/")
    assert rows[0]["summary"]
    assert rows[0]["query"] == "Python 招聘"


def test_exports_use_current_search_not_entire_database(service):
    service.search("Python 招聘", "jobs", 5)
    service.save()
    service.search("机械键盘", "products", 2)
    service.save()

    _, count = service.export_results()
    _, summary = service.analyze()
    assert count == 2
    assert summary["total"] == 2
    assert service.repository.count() == 7


def test_output_path_cannot_escape_workspace(service):
    service.search("Python", "general", 1)
    with pytest.raises(ValueError, match="只能写入"):
        service.export_results("../outside.csv")


def test_auto_without_key_uses_labelled_demo(service):
    service.settings.search_source = "auto"
    service.settings.bocha_api_key = ""
    results, mode = service.search("降噪耳机", "products", 3)
    assert len(results) == 3
    assert results[0]["source"] == "demo"
    assert "未配置 BOCHA_API_KEY" in mode


@pytest.mark.parametrize("source_mode", ["auto", "bocha"])
def test_real_source_failure_never_falls_back_to_demo(service, monkeypatch, source_mode):
    service.settings.search_source = source_mode
    service.settings.bocha_api_key = "test-key"

    def fail_search(*args):
        raise OSError("offline")

    monkeypatch.setattr("job_market_agent.service.bocha_search", fail_search)
    with pytest.raises(OSError, match="offline"):
        service.search("降噪耳机", "products", 3)
    assert service.last_results == []
    with pytest.raises(ValueError, match="没有可导出"):
        service.export_results()
    with service.repository.connect() as conn:
        run = conn.execute("SELECT status, error FROM search_runs").fetchone()
    assert run["status"] == "error"
    assert run["error"] == "offline"


def test_tool_registry_is_complete(service):
    names = {item.name for item in create_tools(service)}
    assert names == {
        "search_web", "save_results", "export_results_csv",
        "analyze_results", "show_saved_results", "get_current_datetime",
    }
