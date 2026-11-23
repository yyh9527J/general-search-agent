import csv
import io

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.main import create_app


class FakeLLM:
    def __init__(self, responses):
        self.responses = iter(responses)

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        return next(self.responses)


def confirmation_response(query="降噪耳机"):
    return AIMessage(
        content=(
            f'{{"action":"needs_confirmation","query":"{query}",'
            '"category":"products","limit":5,"freshness":"oneMonth",'
            '"reason":"需要通勤降噪"}'
        )
    )


def search_responses(query, category):
    return [
        AIMessage(content="{}"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "search_web",
                    "args": {
                        "query": query, "category": category, "limit": 3,
                        "freshness": "noLimit",
                    },
                    "id": f"search-{query}",
                },
                {"name": "save_results", "args": {}, "id": f"save-{query}"},
                {"name": "export_results_csv", "args": {}, "id": f"export-{query}"},
                {"name": "analyze_results", "args": {}, "id": f"analyze-{query}"},
            ],
        ),
        AIMessage(content=f"已完成 {query} 搜索，并生成 results.csv 和 analysis.csv。"),
    ]


def test_homepage_and_health(settings):
    client = TestClient(create_app(settings, FakeLLM([])))

    homepage = client.get("/")
    assert homepage.status_code == 200
    assert "想搜索什么？" in homepage.text
    assert "--accent: #75b9e5" in homepage.text

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["active_sessions"] == 0


def test_confirmation_chat_and_session_delete(settings):
    application = create_app(settings, FakeLLM([confirmation_response()]))
    client = TestClient(application)

    response = client.post("/chat", json={"message": "每天通勤，想买个安静听歌的耳机"})
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "needs_confirmation"
    assert data["pending_search"]["query"] == "降噪耳机"
    assert data["pending_search"]["category"] == "products"
    assert data["files"] == []
    assert "确认" in data["answer"]

    session_id = data["session_id"]
    assert application.state.sessions.get(session_id).service.last_results == []
    assert client.get(f"/sessions/{session_id}/files/results.csv").status_code == 404
    assert client.delete(f"/sessions/{session_id}").json() == {"deleted": True}
    assert client.delete(f"/sessions/{session_id}").json() == {"deleted": False}

    invalid = client.post("/chat", json={"message": "Python", "session_id": "../../bad"})
    assert invalid.status_code == 400


def test_search_downloads_and_session_output_isolation(settings):
    responses = [
        *search_responses("降噪耳机", "products"),
        *search_responses("Python 招聘", "jobs"),
    ]
    application = create_app(settings, FakeLLM(responses))
    client = TestClient(application)

    first = client.post("/chat", json={"message": "降噪耳机"}).json()
    second = client.post("/chat", json={"message": "Python 招聘"}).json()
    assert first["action"] == "search"
    assert second["action"] == "search"
    assert first["session_id"] != second["session_id"]
    assert {item["name"] for item in first["files"]} == {"results.csv", "analysis.csv"}
    assert {item["name"] for item in second["files"]} == {"results.csv", "analysis.csv"}

    first_download = client.get(f"/sessions/{first['session_id']}/files/results.csv")
    second_download = client.get(f"/sessions/{second['session_id']}/files/results.csv")
    assert first_download.status_code == 200
    assert second_download.status_code == 200
    first_rows = list(csv.DictReader(io.StringIO(first_download.content.decode("utf-8-sig"))))
    second_rows = list(csv.DictReader(io.StringIO(second_download.content.decode("utf-8-sig"))))
    assert len(first_rows) == len(second_rows) == 3
    assert {row["query"] for row in first_rows} == {"降噪耳机"}
    assert {row["query"] for row in second_rows} == {"Python 招聘"}
    assert {row["category"] for row in first_rows} == {"products"}
    assert {row["category"] for row in second_rows} == {"jobs"}

    analysis = client.get(f"/sessions/{first['session_id']}/files/analysis.csv")
    assert analysis.status_code == 200
    assert "结果总数" in analysis.content.decode("utf-8-sig")

    sessions = application.state.sessions
    assert len(sessions.get(first["session_id"]).service.last_results) == 3
    assert len(sessions.get(second["session_id"]).service.last_results) == 3
    assert sessions.get(first["session_id"]).output_dir != sessions.get(second["session_id"]).output_dir

    assert client.get(f"/sessions/{first['session_id']}/files/results.db").status_code == 404
    assert client.get(f"/sessions/{first['session_id']}/files/jobs.csv").status_code == 404
    assert client.delete(f"/sessions/{first['session_id']}").json() == {"deleted": True}
    assert client.get(f"/sessions/{first['session_id']}/files/results.csv").status_code == 404
