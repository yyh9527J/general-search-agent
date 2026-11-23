import pytest

from job_market_agent.config import Settings
from job_market_agent.service import SearchService


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        deepseek_api_key="test-key",
        search_workspace_root=str(tmp_path),
        search_source="demo",
    )


@pytest.fixture
def service(settings):
    return SearchService(settings)
