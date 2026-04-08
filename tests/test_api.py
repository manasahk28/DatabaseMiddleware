"""
Tests for the Database Middleware API.

Run with:
    pytest tests/ -v
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Use an in-memory SQLite database for tests
import os
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["DATABASE_TYPE"] = "sqlite"
os.environ["SAFE_MODE"] = "true"

from app.main import app
from app.db.database import get_db, seed_sample_data, engine as real_engine

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

TEST_ENGINE = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=TEST_ENGINE)


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_test_db():
    """Create tables and seed data before each test."""
    from app.db.database import seed_sample_data
    # Point seed at test engine
    from sqlalchemy import event
    seed_sample_data()   # seeds real engine (sqlite file) — ok for integration
    yield


# ---------------------------------------------------------------------------
# Root & health tests
# ---------------------------------------------------------------------------

class TestRootEndpoints:
    def test_root(self):
        r = client.get("/")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"
        assert "endpoints" in data

    def test_health(self):
        r = client.get("/api/v1/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"
        assert "database" in data
        assert "safe_mode" in data


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestSchema:
    def test_list_tables(self):
        r = client.get("/api/v1/tables")
        assert r.status_code == 200
        data = r.json()
        assert "tables" in data
        assert isinstance(data["tables"], list)

    def test_get_schema(self):
        r = client.get("/api/v1/schema")
        assert r.status_code == 200
        data = r.json()
        assert "tables" in data
        assert "ddl" in data
        assert isinstance(data["ddl"], str)
        assert len(data["ddl"]) > 0


# ---------------------------------------------------------------------------
# NLP → SQL tests (rule-based fallback, no model needed)
# ---------------------------------------------------------------------------

class TestNLPQuery:
    def _query(self, question: str, execute: bool = True):
        return client.post("/api/v1/query", json={
            "question": question,
            "execute": execute,
            "use_model": False,   # use rule-based fallback — no GPU needed
        })

    def test_basic_employee_query(self):
        r = self._query("show all employees")
        assert r.status_code == 200
        data = r.json()
        assert "generated_sql" in data
        assert "SELECT" in data["generated_sql"].upper()

    def test_generates_sql_without_execute(self):
        r = self._query("list all employees", execute=False)
        assert r.status_code == 200
        data = r.json()
        assert data["result"] is None
        assert "SELECT" in data["generated_sql"].upper()

    def test_average_salary_question(self):
        r = self._query("what is the average salary?")
        assert r.status_code == 200
        data = r.json()
        assert "AVG" in data["generated_sql"].upper()

    def test_method_field_present(self):
        r = self._query("show all employees")
        data = r.json()
        assert data["method"] in ("slm", "rule_based_fallback")

    def test_confidence_field_present(self):
        r = self._query("show all employees")
        data = r.json()
        assert data["confidence"] in ("high", "low")


# ---------------------------------------------------------------------------
# Raw SQL execution tests
# ---------------------------------------------------------------------------

class TestRawSQL:
    def test_select_query(self):
        r = client.post("/api/v1/execute", json={"sql": "SELECT 1 AS val;"})
        assert r.status_code == 200
        data = r.json()
        assert data["row_count"] == 1
        assert data["rows"][0]["val"] == 1

    def test_safe_mode_blocks_drop(self):
        r = client.post("/api/v1/execute", json={"sql": "DROP TABLE employees;"})
        assert r.status_code == 403
        assert "SAFE_MODE" in r.json()["detail"]

    def test_safe_mode_blocks_insert(self):
        r = client.post("/api/v1/execute", json={"sql": "INSERT INTO employees VALUES (99,'X','Y',0,'2024-01-01',NULL);"})
        assert r.status_code == 403

    def test_invalid_sql(self):
        r = client.post("/api/v1/execute", json={"sql": "SELECT * FROM nonexistent_table_xyz;"})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# SQL generator unit tests
# ---------------------------------------------------------------------------

class TestSQLGenerator:
    def test_rule_based_employee(self):
        from app.models.sql_generator import _rule_based_fallback
        sql = _rule_based_fallback("show all employees")
        assert "employees" in sql.lower()
        assert "SELECT" in sql.upper()

    def test_rule_based_average(self):
        from app.models.sql_generator import _rule_based_fallback
        sql = _rule_based_fallback("average salary")
        assert "AVG" in sql.upper()

    def test_extract_sql_fenced(self):
        from app.models.sql_generator import _extract_sql
        raw = "```sql\nSELECT * FROM employees;\n```"
        sql = _extract_sql(raw)
        assert sql.strip() == "SELECT * FROM employees;"

    def test_extract_sql_with_header(self):
        from app.models.sql_generator import _extract_sql
        raw = "### SQL: SELECT name FROM employees;"
        sql = _extract_sql(raw)
        assert "SELECT" in sql.upper()

    def test_generate_sql_no_model(self):
        from app.models.sql_generator import generate_sql
        result = generate_sql(
            natural_language="list all employees",
            ddl="CREATE TABLE employees (id INTEGER, name TEXT);",
            use_model=False,
        )
        assert "sql" in result
        assert "method" in result
        assert result["method"] == "rule_based_fallback"
        assert "SELECT" in result["sql"].upper()

    def test_build_prompt_contains_ddl(self):
        from app.models.sql_generator import build_prompt
        ddl = "CREATE TABLE test (id INTEGER);"
        prompt = build_prompt("show all rows", ddl)
        assert "CREATE TABLE test" in prompt
        assert "show all rows" in prompt
