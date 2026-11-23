"""项目配置：环境变量、模型、搜索数据源和文件路径。"""

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    deepseek_base_url: str = "https://api.deepseek.com/v1"

    search_workspace_root: str = ""
    search_db_path: str = "data/results.db"
    search_source: str = "auto"
    search_timeout: int = 20
    bocha_api_key: str = ""
    agent_recursion_limit: int = 25

    @property
    def root_path(self) -> Path:
        return Path(self.search_workspace_root) if self.search_workspace_root else PROJECT_ROOT

    @property
    def db_path(self) -> Path:
        path = Path(self.search_db_path)
        return path if path.is_absolute() else self.root_path / path

    def output_path(self, value: str) -> Path:
        """将交付文件限制在工作目录内，防止路径越界。"""
        if not value.strip():
            raise ValueError("输出路径不能为空")
        path = Path(value)
        candidate = path if path.is_absolute() else self.root_path / path
        real_path = Path(os.path.realpath(candidate))
        root = Path(os.path.realpath(self.root_path))
        if real_path != root and root not in real_path.parents:
            raise ValueError(f"只能写入项目目录 {root} 内的文件")
        real_path.parent.mkdir(parents=True, exist_ok=True)
        return real_path


def load_settings() -> Settings:
    """默认读取项目 .env，也可用 AGENT_ENV_FILE 指定其他 env 文件。"""
    env_file = os.getenv("AGENT_ENV_FILE")
    if not env_file:
        default_env = PROJECT_ROOT / ".env"
        env_file = str(default_env) if default_env.exists() else None
    return Settings(_env_file=env_file)
