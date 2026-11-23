"""FastAPI 网页服务：通用搜索、多轮会话、独立导出与安全下载。"""

from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from langgraph.errors import GraphRecursionError
from pydantic import BaseModel, Field

from job_market_agent.config import Settings, load_settings
from job_market_agent.graph import build_graph, create_session, run_turn
from job_market_agent.llm import build_llm
from job_market_agent.service import SearchService

STATIC_DIR = Path(__file__).resolve().parent / "static"
DOWNLOAD_NAMES = ("results.csv", "analysis.csv")
SESSION_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000, description="用户输入")
    session_id: str | None = Field(default=None, description="会话 ID；不传则自动创建")


class FileInfo(BaseModel):
    name: str
    url: str


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    action: str
    pending_search: dict[str, Any]
    files: list[FileInfo]
    latency_ms: int


@dataclass
class SessionRuntime:
    session_id: str
    service: SearchService
    graph: Any
    state: dict
    output_dir: Path
    lock: threading.Lock = field(default_factory=threading.Lock)


class SessionManager:
    """每个网页会话使用独立 service、图状态和锁，模型客户端可共享。"""

    def __init__(self, settings: Settings, llm=None):
        self.settings = settings
        self._llm = llm
        self._sessions: dict[str, SessionRuntime] = {}
        self._lock = threading.Lock()

    @staticmethod
    def valid_session_id(session_id: str) -> bool:
        return bool(SESSION_ID_PATTERN.fullmatch(session_id))

    def _create(self, session_id: str) -> SessionRuntime:
        if self._llm is None:
            self._llm = build_llm(self.settings)
        export_dir = Path("exports") / "sessions" / session_id
        service = SearchService(self.settings, export_dir=str(export_dir))
        return SessionRuntime(
            session_id=session_id,
            service=service,
            graph=build_graph(self.settings, service, self._llm),
            state=create_session(),
            output_dir=self.settings.output_path(str(export_dir)),
        )

    def get_or_create(self, session_id: str | None = None) -> SessionRuntime:
        session_id = session_id or str(uuid.uuid4())
        if not self.valid_session_id(session_id):
            raise ValueError("会话 ID 格式无效")
        with self._lock:
            runtime = self._sessions.get(session_id)
            if runtime is None:
                runtime = self._create(session_id)
                self._sessions[session_id] = runtime
            return runtime

    def get(self, session_id: str) -> SessionRuntime | None:
        if not self.valid_session_id(session_id):
            return None
        with self._lock:
            return self._sessions.get(session_id)

    def delete(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)


def create_app(settings: Settings | None = None, llm=None) -> FastAPI:
    application = FastAPI(
        title="General Search Agent API",
        description="带意图确认的通用网页搜索、存储、导出与分析 Agent",
        version="0.2.0",
    )
    sessions = SessionManager(settings or load_settings(), llm)
    application.state.sessions = sessions

    def available_files(session_id: str, runtime: SessionRuntime) -> list[FileInfo]:
        return [
            FileInfo(
                name=name,
                url=f"/sessions/{session_id}/files/{name}",
            )
            for name in DOWNLOAD_NAMES
            if (runtime.output_dir / name).is_file()
        ]

    @application.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @application.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": "0.2.0",
            "model": sessions.settings.deepseek_model,
            "search_source": sessions.settings.search_source,
            "active_sessions": sessions.count(),
        }

    @application.post("/chat", response_model=ChatResponse)
    def chat(request: ChatRequest) -> ChatResponse:
        text = request.message.strip()
        if not text:
            raise HTTPException(status_code=400, detail="消息不能为空")
        started = time.perf_counter()
        try:
            runtime = sessions.get_or_create(request.session_id)
            with runtime.lock:
                answer = run_turn(
                    runtime.graph,
                    runtime.state,
                    text,
                    sessions.settings.agent_recursion_limit,
                )
            session_id = runtime.session_id
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except GraphRecursionError as exc:
            raise HTTPException(
                status_code=503,
                detail="执行步数超过上限，请把任务拆小一些再试。",
            ) from exc
        except Exception as exc:  # noqa: BLE001 - Web 顶层统一返回运行错误
            raise HTTPException(status_code=500, detail=f"执行失败：{exc}") from exc

        return ChatResponse(
            session_id=session_id,
            answer=answer,
            action=runtime.state.get("action", "chat"),
            pending_search=dict(runtime.state.get("pending_search", {})),
            files=available_files(session_id, runtime),
            latency_ms=round((time.perf_counter() - started) * 1000),
        )

    @application.delete("/sessions/{session_id}")
    def delete_session(session_id: str) -> dict[str, bool]:
        return {"deleted": sessions.delete(session_id)}

    @application.get("/sessions/{session_id}/files/{filename}")
    def download_file(session_id: str, filename: str) -> FileResponse:
        runtime = sessions.get(session_id)
        if runtime is None:
            raise HTTPException(status_code=404, detail="会话不存在或已清空")
        if filename not in DOWNLOAD_NAMES:
            raise HTTPException(status_code=404, detail="只允许下载 results.csv 和 analysis.csv")
        path = runtime.output_dir / filename
        if not path.is_file():
            raise HTTPException(status_code=404, detail="文件尚未生成，请先完成网页搜索")
        return FileResponse(path, media_type="text/csv; charset=utf-8", filename=filename)

    return application


app = create_app()


def serve() -> None:
    uvicorn.run("app.main:app", host="127.0.0.1", port=8001)


if __name__ == "__main__":
    serve()
