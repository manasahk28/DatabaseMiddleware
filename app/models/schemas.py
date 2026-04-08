"""
Pydantic schemas for request validation and response serialization.
"""

from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    """Body for POST /query — the main NLP-to-SQL endpoint."""
    question: str = Field(
        ...,
        min_length=3,
        max_length=500,
        example="Show me all employees in the Engineering department",
    )
    execute: bool = Field(
        default=True,
        description="If true, run the generated SQL against the database and return rows.",
    )
    use_model: bool = Field(
        default=True,
        description="If false, skip the SLM and use the rule-based fallback (faster, less accurate).",
    )


class RawSQLRequest(BaseModel):
    """Body for POST /execute — run a raw SQL query directly."""
    sql: str = Field(..., example="SELECT * FROM employees LIMIT 5;")


class ConnectRequest(BaseModel):
    """Body for POST /connect — connect a database or load schema DDL."""
    database_url: Optional[str] = Field(
        None,
        example="sqlite:///./mydata.db",
        description="A SQLAlchemy-style database URL to connect to.",
    )
    ddl: Optional[str] = Field(
        None,
        description="Schema DDL to create an in-memory database for query generation and execution.",
    )


class ConnectResponse(BaseModel):
    tables: List[str]
    ddl: str
    database_url: Optional[str] = None


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class QueryResult(BaseModel):
    columns: List[str]
    rows: List[Dict[str, Any]]
    row_count: int


class NLPQueryResponse(BaseModel):
    question: str
    generated_sql: str
    method: str                        # "slm" | "rule_based_fallback"
    model_used: Optional[str]
    confidence: str                    # "high" | "low"
    result: Optional[QueryResult]
    error: Optional[str] = None


class SchemaResponse(BaseModel):
    tables: Dict[str, Any]
    ddl: str


class HealthResponse(BaseModel):
    status: str
    database: str
    model: str
    safe_mode: bool
