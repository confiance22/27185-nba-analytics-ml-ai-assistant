import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import re
import snowflake.connector
import requests

from database.db import get_connection
from config.settings import GROQ_API_KEY
from etl.logging_setup import get_logger

if "NO_PROXY" not in os.environ:
    os.environ["NO_PROXY"] = "localhost,127.0.0.1"

logger = get_logger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "llama-3.1-8b-instant"

SCHEMA_DESCRIPTION = """
Database schema:

Table: cleaned_teams
  team_id        INTEGER  PRIMARY KEY
  city           VARCHAR
  name           VARCHAR               (e.g. "Lakers")
  full_name      VARCHAR               (e.g. "Los Angeles Lakers")
  abbreviation   VARCHAR               (e.g. "LAL")
  conference     VARCHAR               "East" or "West"
  division       VARCHAR               Atlantic, Central, Southeast, Northwest, Pacific, Southwest

Table: cleaned_games
  game_id            INTEGER  PRIMARY KEY
  date               DATE
  season             INTEGER               (2021, 2022, or 2023)
  postseason         BOOLEAN               FALSE = regular, TRUE = playoffs
  home_team_id       INTEGER  FK -> cleaned_teams.team_id
  visitor_team_id    INTEGER  FK -> cleaned_teams.team_id
  home_team_score    INTEGER
  visitor_team_score INTEGER
  home_win           INTEGER               1 = HOME team won, 0 = VISITOR team won.
                                           There is NO separate "visitor_win" column.
                                           To check if the visitor won, use home_win = 0.

IMPORTANT COLUMN RULES:
  - Do NOT re-define home_win in a subquery. If counting wins for a specific team:
      CASE WHEN team = home AND home_win = 1 THEN 1
           WHEN team = visitor AND home_win = 0 THEN 1
           ELSE 0 END

Notes:
  - 30 active NBA teams. Games span 2021-2023 only.
  - Individual game results only - not playoff series or championship winners.
"""


def _groq_complete(prompt, model=MODEL):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
    }
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    resp = requests.post(GROQ_URL, json=payload, headers=headers, timeout=120)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def question_to_sql(question):
    logger.info("Calling Groq (Llama) to generate SQL...")

    prompt = f"""{SCHEMA_DESCRIPTION}

Instructions:
- Translate the following question into a single SQL SELECT statement.
- Return ONLY the SQL query - no explanation, no markdown code fences, no extra text.
- If the question asks about something NOT in this schema (e.g. players, coaches,
  tickets, other sports, weather, predictions, future events), respond with exactly:
  UNANSWERABLE
- Do NOT wrap the SQL in markdown triple backticks.
- Use table names cleaned_teams and cleaned_games exactly as shown.
- Use column names exactly as shown.

Question: {question}
"""

    try:
        raw = _groq_complete(prompt, model=MODEL)
    except Exception as e:
        logger.error(f"Groq SQL-generation call failed: {e}")
        return "UNANSWERABLE"

    raw = re.sub(r"^```(?:sql)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    raw = raw.strip()
    logger.info(f"Groq returned SQL:\n{raw}")
    return raw


def result_to_sentence(question, sql, result):
    if result is None:
        return (
            "I couldn't run that query - it may have referenced something that "
            "doesn't exist in this data. Try asking about teams, games, scores, "
            "or seasons from 2021-2023."
        )

    if not result:
        return "I ran the query but found no matching data for that question."

    logger.info("Calling Groq (Llama) to convert result to sentence...")

    prompt = f"""
You are a helpful NBA data assistant. Given a user's question, the SQL query
that was run, and the query result, answer the user's original question in
one clear, natural sentence. Use the actual numbers from the result.

User's question: {question}

SQL query: {sql}

Query result (JSON-like): {result}

Answer in one sentence using the real numbers from the result:
"""

    try:
        answer = _groq_complete(prompt, model=MODEL)
        logger.info("Groq sentence response received")
        return answer
    except Exception as e:
        logger.error(f"Groq sentence call failed: {e}")
        return (
            f"I found data for that question but had trouble phrasing the answer. "
            f"The SQL returned {len(result)} row(s)."
        )


def run_sql_safely(sql):
    stripped = sql.strip().upper()
    if not stripped.startswith("SELECT"):
        logger.warning(f"Rejected non-SELECT query:\n{sql}")
        return None

    if "LIMIT" not in stripped:
        sql = sql.rstrip().rstrip(";") + " LIMIT 50;"

    logger.info(f"Running SQL:\n{sql}")

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            col_names = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
            result = [dict(zip(col_names, row)) for row in rows]
        logger.info(f"Query returned {len(result)} row(s)")
        return result
    except snowflake.connector.errors.Error as e:
        logger.error(f"SQL execution failed: {e}")
        return None
    finally:
        conn.close()


def ask(question):
    try:
        sql = question_to_sql(question)
        if sql == "UNANSWERABLE":
            return (
                "I can only answer questions about NBA teams and games from the "
                "2021-2023 seasons - that question is outside what I can look up."
            )
        result = run_sql_safely(sql)
        return result_to_sentence(question, sql, result)
    except Exception as e:
        logger.error(f"Unexpected error in ask(): {e}")
        return "Something went wrong while processing your question. Please try again."


def main():
    print("NBA Data AI Assistant")
    print("Type 'quit' or 'exit' to stop.\n")
    while True:
        try:
            question = input("Ask a question about the NBA data: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question:
            continue
        if question.lower() in ("quit", "exit"):
            break
        answer = ask(question)
        print(f"\n{answer}\n")


if __name__ == "__main__":
    main()
