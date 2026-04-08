"""
API route handlers for the Database Middleware.

Endpoints
---------
POST /query          NLP question → SQL → (optional) execute → results
POST /execute        Run raw SQL directly
GET  /schema         Introspect the database schema
GET  /tables         List available table names
GET  /health         Detailed health check
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import (
    get_db,
    get_schema_info,
    schema_to_ddl,
    execute_query,
    set_database_url,
    create_in_memory_db_from_ddl,
)
from app.models.sql_generator import generate_sql
from app.models.schemas import (
    QueryRequest,
    RawSQLRequest,
    ConnectRequest,
    ConnectResponse,
    NLPQueryResponse,
    QueryResult,
    SchemaResponse,
    HealthResponse,
)
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Main NLP → SQL endpoint
# ---------------------------------------------------------------------------

@router.post("/query", response_model=NLPQueryResponse, tags=["NLP to SQL"])
def nlp_to_sql(request: QueryRequest, db: Session = Depends(get_db)):
    """
    Convert a natural-language question to SQL and (optionally) execute it.

    - **question**: Plain-English question about your data.
    - **execute**: Whether to run the SQL and return rows (default: true).
    - **use_model**: Use the SLM (true) or rule-based fallback (false).
    """
    logger.info(f"📥 Question received: {request.question!r}")

    # 1. Get schema DDL for prompt context
    schema = get_schema_info()
    ddl = schema_to_ddl(schema)

    # 2. Generate SQL
    gen = generate_sql(
        natural_language=request.question,
        ddl=ddl,
        use_model=request.use_model,
    )

    logger.info(f"🗄️  Generated SQL [{gen['method']}]: {gen['sql']!r}")

    # 3. Optionally execute
    result_payload = None
    exec_error = gen.get("error")

    if request.execute and not exec_error:
        try:
            raw_result = execute_query(gen["sql"], db)
            result_payload = QueryResult(**raw_result)
        except Exception as exc:
            logger.error(f"❌ Query execution failed: {exc}")
            exec_error = str(exc)

    return NLPQueryResponse(
        question=request.question,
        generated_sql=gen["sql"],
        method=gen["method"],
        model_used=gen["model_used"],
        confidence=gen["confidence"],
        result=result_payload,
        error=exec_error,
    )


# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------

@router.post("/connect", response_model=ConnectResponse, tags=["Schema"])
def connect_database(request: ConnectRequest):
    """Connect an external database URL or create an in-memory DB from DDL."""
    if bool(request.database_url) == bool(request.ddl):
        raise HTTPException(
            status_code=400,
            detail="Provide exactly one of database_url or ddl.",
        )

    try:
        if request.database_url:
            set_database_url(request.database_url)
        else:
            create_in_memory_db_from_ddl(request.ddl)

        schema = get_schema_info()
        ddl = schema_to_ddl(schema)
        return ConnectResponse(
            tables=list(schema.keys()),
            ddl=ddl,
            database_url=request.database_url,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# Raw SQL execution
# ---------------------------------------------------------------------------

@router.post("/execute", tags=["SQL"])
def execute_raw_sql(request: RawSQLRequest, db: Session = Depends(get_db)):
    """
    Execute a raw SQL query directly (subject to SAFE_MODE restrictions).
    """
    try:
        result = execute_query(request.sql, db)
        return {
            "sql": request.sql,
            "columns": result["columns"],
            "rows": result["rows"],
            "row_count": result["row_count"],
        }
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"SQL error: {exc}")


# ---------------------------------------------------------------------------
# Schema introspection
# ---------------------------------------------------------------------------

@router.get("/schema", response_model=SchemaResponse, tags=["Schema"])
def get_schema():
    """Return the full database schema as structured JSON + DDL."""
    schema = get_schema_info()
    ddl = schema_to_ddl(schema)
    return SchemaResponse(tables=schema, ddl=ddl)


@router.get("/tables", tags=["Schema"])
def list_tables():
    """Return a list of all table names in the database."""
    schema = get_schema_info()
    return {"tables": list(schema.keys()), "count": len(schema)}


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@router.get("/health", response_model=HealthResponse, tags=["System"])
def health_check():
    """Detailed health status of the API."""
    return HealthResponse(
        status="healthy",
        database=settings.DATABASE_TYPE,
        model=settings.SLM_MODEL_NAME,
        safe_mode=settings.SAFE_MODE,
    )
