"""大模型客户端工厂。"""

from langchain_openai import ChatOpenAI

from job_market_agent.config import Settings


def build_llm(settings: Settings) -> ChatOpenAI:
    if not settings.deepseek_api_key:
        raise ValueError(
            "没有找到 DEEPSEEK_API_KEY，请复制 .env.example 为 .env 并填写，"
            "或设置 AGENT_ENV_FILE 指向已有 env 文件。"
        )
    return ChatOpenAI(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        temperature=0,
    )
