"""Tests for POST /api/agent/ask and GET /api/agent/ask/suggestions."""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from api.main import app
    return TestClient(app)


def _auth(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "superduperadmin"})
    return {"Authorization": f"Bearer {r.json().get('access_token', '')}"}


# ── /ask/suggestions ──────────────────────────────────────────────────────────

def test_suggestions_requires_auth(client):
    r = client.get("/api/agent/ask/suggestions")
    assert r.status_code == 401


def test_suggestions_error_status(client):
    r = client.get("/api/agent/ask/suggestions?status=error", headers=_auth(client))
    assert r.status_code == 200
    data = r.json()
    assert "suggestions" in data
    assert len(data["suggestions"]) > 0
    joined = " ".join(data["suggestions"]).lower()
    assert "fail" in joined or "error" in joined or "check" in joined


def test_suggestions_healthy_status(client):
    r = client.get("/api/agent/ask/suggestions?status=healthy", headers=_auth(client))
    assert r.status_code == 200
    assert len(r.json()["suggestions"]) > 0


def test_suggestions_with_section(client):
    r = client.get("/api/agent/ask/suggestions?status=healthy&section=STORAGE", headers=_auth(client))
    assert r.status_code == 200
    suggestions = r.json()["suggestions"]
    joined = " ".join(suggestions).lower()
    assert "storage" in joined or "full" in joined


def test_suggestions_max_four(client):
    r = client.get("/api/agent/ask/suggestions?status=error&section=COMPUTE", headers=_auth(client))
    assert len(r.json()["suggestions"]) <= 4


# ── /ask ──────────────────────────────────────────────────────────────────────

def test_ask_requires_auth(client):
    r = client.post("/api/agent/ask", json={"question": "test", "context": {}})
    assert r.status_code == 401


def test_ask_empty_question_rejected(client):
    r = client.post("/api/agent/ask",
                    json={"question": "   ", "context": {}},
                    headers=_auth(client))
    assert r.status_code == 400


def test_ask_no_lm_studio_returns_503(client):
    with patch("api.routers.agent._lm_base", return_value=""):
        r = client.post("/api/agent/ask",
                        json={"question": "Why is this failing?",
                              "context": {"status": "error", "label": "test"}},
                        headers=_auth(client))
    assert r.status_code == 503


def test_ask_streams_sse_format(client):
    """With a mocked LM Studio, verify SSE data: prefix format."""
    mock_chunk = MagicMock()
    mock_chunk.choices = [MagicMock()]
    mock_chunk.choices[0].delta.content = "It "

    mock_chunk2 = MagicMock()
    mock_chunk2.choices = [MagicMock()]
    mock_chunk2.choices[0].delta.content = "failed."

    mock_stream = iter([mock_chunk, mock_chunk2])

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_stream

    with patch("api.routers.agent._lm_base", return_value="http://mock:1234/v1"):
        with patch("openai.OpenAI", return_value=mock_client):
            r = client.post("/api/agent/ask",
                            json={"question": "Why is this failing?",
                                  "context": {"status": "error", "label": "test-svc",
                                              "platform": "proxmox", "section": "COMPUTE"}},
                            headers=_auth(client))

    assert r.status_code == 200
    assert "text/event-stream" in r.headers.get("content-type", "")
    body = r.text
    assert "data: " in body
    assert "[DONE]" in body
