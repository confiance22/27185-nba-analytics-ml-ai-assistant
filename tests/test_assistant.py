import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Day 11: tests for the AI assistant (mocked to avoid real API/DB calls).
from unittest.mock import patch, MagicMock
import pytest


@pytest.fixture(autouse=True)
def _no_env_vars(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)


# ========================= run_sql_safely =========================

@patch("ai_assistant.assistant.get_connection")
def test_run_sql_safely_rejects_non_select(mock_get_conn):
    from ai_assistant.assistant import run_sql_safely
    result = run_sql_safely("DROP TABLE cleaned_games")
    assert result is None
    mock_get_conn.assert_not_called()


@patch("ai_assistant.assistant.get_connection")
def test_run_sql_safely_adds_limit(mock_get_conn):
    fake_cursor = MagicMock()
    fake_cursor.description = [("ONE",)]
    fake_cursor.fetchall.return_value = [(1,)]
    fake_conn = MagicMock()
    fake_conn.cursor.return_value.__enter__.return_value = fake_cursor
    mock_get_conn.return_value = fake_conn

    from ai_assistant.assistant import run_sql_safely
    result = run_sql_safely("SELECT 1")
    assert result == [{"ONE": 1}]
    executed_sql = fake_cursor.execute.call_args[0][0]
    assert "LIMIT 50" in executed_sql.upper()


# ========================= question_to_sql =========================

@patch("ai_assistant.assistant.requests.post")
def test_question_to_sql_mocked(mock_post):
    mock_post.return_value = _mock_groq_response("SELECT COUNT(*) FROM cleaned_teams")
    from ai_assistant.assistant import question_to_sql
    result = question_to_sql("how many teams?")
    assert result == "SELECT COUNT(*) FROM cleaned_teams"


@patch("ai_assistant.assistant.requests.post")
def test_question_to_sql_strips_markdown_fences(mock_post):
    mock_post.return_value = _mock_groq_response("```sql\nSELECT 1\n```")
    from ai_assistant.assistant import question_to_sql
    result = question_to_sql("test")
    assert result == "SELECT 1"


@patch("ai_assistant.assistant.requests.post")
def test_question_to_sql_unanswerable_mocked(mock_post):
    mock_post.return_value = _mock_groq_response("UNANSWERABLE")
    from ai_assistant.assistant import question_to_sql
    result = question_to_sql("who won the super bowl?")
    assert result == "UNANSWERABLE"


# ========================= ask (unanswerable pathway) =========================

@patch("ai_assistant.assistant.run_sql_safely")
@patch("ai_assistant.assistant.question_to_sql")
def test_ask_unanswerable_returns_graceful_message(mock_q2s, mock_run):
    mock_q2s.return_value = "UNANSWERABLE"
    from ai_assistant.assistant import ask
    answer = ask("who won the super bowl?")
    assert "can only answer" in answer
    mock_run.assert_not_called()


# ========================= result_to_sentence =========================

def test_result_to_sentence_handles_none():
    from ai_assistant.assistant import result_to_sentence
    msg = result_to_sentence("q", "SELECT 1", None)
    assert "couldn't run that query" in msg


def test_result_to_sentence_handles_empty_list():
    from ai_assistant.assistant import result_to_sentence
    msg = result_to_sentence("q", "SELECT 1", [])
    assert "no matching data" in msg


@patch("ai_assistant.assistant.requests.post")
def test_result_to_sentence_calls_groq(mock_post):
    mock_post.return_value = _mock_groq_response("There are 30 teams.")
    from ai_assistant.assistant import result_to_sentence
    msg = result_to_sentence("how many teams?", "SELECT COUNT(*)", [{"COUNT(*)": 30}])
    assert "30" in msg


# ========================= ask (error handling) =========================

@patch("ai_assistant.assistant.question_to_sql")
def test_ask_never_crashes_on_unexpected_error(mock_q2s):
    mock_q2s.side_effect = RuntimeError("boom")
    from ai_assistant.assistant import ask
    answer = ask("any question")
    assert "Something went wrong" in answer


# ========================= Integration smoke (skipped by default) =========================

@pytest.mark.skip(reason="Requires real Groq + Snowflake. Run: pytest ... -k smoke --no-header -s")
def test_real_integration_smoke():
    from ai_assistant.assistant import ask
    answer = ask("how many teams are in the nba")
    assert "30" in answer


# ========================= Helper =========================

def _mock_groq_response(text):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"choices": [{"message": {"content": text}}]}
    return mock_resp
