"""命令行交互入口。"""

import argparse
import logging

from langgraph.errors import GraphRecursionError

from job_market_agent.config import load_settings
from job_market_agent.graph import build_graph, create_session, run_turn
from job_market_agent.service import SearchService


def execute(graph, session: dict, text: str, recursion_limit: int) -> None:
    try:
        answer = run_turn(graph, session, text, recursion_limit)
    except GraphRecursionError:
        print("执行步数超过上限，已停止。请把任务拆小一些再试。")
        return
    except Exception as exc:  # noqa: BLE001 - CLI 顶层需要展示所有运行错误
        print(f"执行失败：{exc}")
        return
    print(f"\n助手：{answer}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="通用网页搜索、存储与分析 Agent")
    parser.add_argument("--once", default="", help="只执行一条指令后退出")
    parser.add_argument("--verbose", action="store_true", help="显示意图和工具调用日志")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="[%(levelname)s] %(name)s: %(message)s",
    )

    settings = load_settings()
    service = SearchService(settings)
    graph = build_graph(settings=settings, service=service)

    print("通用网页搜索助手已启动（输入 quit 退出，/reset 清空会话）")
    print("可搜索招聘、商品或其他网页；描述背景需求时，推断查询词后会先请你确认。")
    print(f"内部数据库：{settings.db_path}")
    print("交付文件统一为 CSV：exports/results.csv、exports/analysis.csv")
    print(f"搜索模式：{settings.search_source}")
    if settings.search_source == "auto" and not settings.bocha_api_key:
        print("当前未配置 BOCHA_API_KEY，将使用明确标注的 demo 演示数据。")
    print()

    session = create_session()
    if args.once:
        execute(graph, session, args.once, settings.agent_recursion_limit)
        return

    while True:
        try:
            text = input("你：").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue
        if text.lower() in {"quit", "exit", "q"}:
            break
        if text == "/reset":
            session = create_session()
            print("会话与待确认条件已清空。\n")
            continue
        execute(graph, session, text, settings.agent_recursion_limit)


if __name__ == "__main__":
    main()
