"""
Database connection, session management, and schema introspection.
"""

from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator, Dict, List, Any
import logging
import re

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine & Session
# ---------------------------------------------------------------------------

_engine = None
_SessionLocal = None


def init_engine(database_url: str):
    global _engine, _SessionLocal
    if not database_url or not database_url.strip():
        raise ValueError("DATABASE_URL must be provided to initialize the database engine.")

    connect_args = {"check_same_thread": False} if "sqlite" in database_url else {}
    if _engine is not None:
        _engine.dispose()

    _engine = create_engine(database_url, connect_args=connect_args, echo=False)
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    logger.info(f"✅ Connected to database: {database_url}")
    return _engine


def set_database_url(database_url: str):
    settings.DATABASE_URL = database_url
    return init_engine(database_url)


def _normalize_sqlite_ddl(ddl: str) -> str:
    """Convert common non-SQLite DDL syntax into SQLite-compatible SQL."""
    ddl = re.sub(r'`', '', ddl)
    ddl = re.sub(r'\bAUTO_INCREMENT\b', 'AUTOINCREMENT', ddl, flags=re.IGNORECASE)
    ddl = re.sub(r'\bINT\b', 'INTEGER', ddl, flags=re.IGNORECASE)
    ddl = re.sub(r'\bUNSIGNED\b', '', ddl, flags=re.IGNORECASE)
    ddl = re.sub(r'\bSIGNED\b', '', ddl, flags=re.IGNORECASE)
    ddl = re.sub(r'\bDOUBLE\b', 'REAL', ddl, flags=re.IGNORECASE)
    ddl = re.sub(r'ENGINE\s*=\s*\w+\b', '', ddl, flags=re.IGNORECASE)
    ddl = re.sub(r'CHARACTER SET\s+\w+\b', '', ddl, flags=re.IGNORECASE)
    ddl = re.sub(r'COLLATE\s+\w+\b', '', ddl, flags=re.IGNORECASE)
    ddl = re.sub(r'AUTO_INCREMENT\s*=\s*\d+\b', '', ddl, flags=re.IGNORECASE)
    return ddl


def create_in_memory_db_from_ddl(ddl: str):
    if not ddl or not ddl.strip():
        raise ValueError("DDL must be provided when connecting via schema DDL.")

    normalized_ddl = _normalize_sqlite_ddl(ddl)
    init_engine("sqlite:///:memory:")
    with get_engine().begin() as conn:
        for stmt in [stmt.strip() for stmt in normalized_ddl.strip().split(";") if stmt.strip()]:
            conn.execute(text(stmt))
    return _engine


def get_engine():
    if _engine is None:
        raise HTTPException(
            status_code=503,
            detail="No database connected. Connect via POST /api/v1/connect first.",
        )
    return _engine


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a DB session and closes it after the request."""
    if _SessionLocal is None:
        raise HTTPException(
            status_code=503,
            detail="No database connected. Connect via POST /api/v1/connect first.",
        )

    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Schema introspection
# ---------------------------------------------------------------------------

def get_schema_info() -> Dict[str, Any]:
    """
    Return a structured description of every table and column in the database.
    Used to build context-rich prompts for the SLM.
    """
    inspector = inspect(get_engine())
    schema: Dict[str, Any] = {}

    for table_name in inspector.get_table_names():
        columns = []
        for col in inspector.get_columns(table_name):
            columns.append({
                "name": col["name"],
                "type": str(col["type"]),
                "nullable": col.get("nullable", True),
            })

        foreign_keys = []
        for fk in inspector.get_foreign_keys(table_name):
            foreign_keys.append({
                "constrained_columns": fk["constrained_columns"],
                "referred_table": fk["referred_table"],
                "referred_columns": fk["referred_columns"],
            })

        pk = inspector.get_pk_constraint(table_name)
        schema[table_name] = {
            "columns": columns,
            "primary_key": pk.get("constrained_columns", []),
            "foreign_keys": foreign_keys,
        }

    return schema


def schema_to_ddl(schema: Dict[str, Any]) -> str:
    """
    Convert the schema dict into compact CREATE TABLE DDL strings.
    These are embedded in the SLM prompt so the model understands the DB layout.
    """
    lines: List[str] = []
    for table, info in schema.items():
        col_defs = []
        for col in info["columns"]:
            nullable = "" if col["nullable"] else " NOT NULL"
            pk_marker = " PRIMARY KEY" if col["name"] in info["primary_key"] else ""
            col_defs.append(f"  {col['name']} {col['type']}{pk_marker}{nullable}")
        for fk in info["foreign_keys"]:
            src = ", ".join(fk["constrained_columns"])
            ref_cols = ", ".join(fk["referred_columns"])
            col_defs.append(
                f"  FOREIGN KEY ({src}) REFERENCES {fk['referred_table']}({ref_cols})"
            )
        lines.append(f"CREATE TABLE {table} (\n" + ",\n".join(col_defs) + "\n);")
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Query execution
# ---------------------------------------------------------------------------

def execute_query(sql: str, db: Session) -> Dict[str, Any]:
    """
    Execute a SQL query and return rows + column names.
    Enforces SAFE_MODE (SELECT-only) when configured.
    """
    from app.config import settings

    sql_stripped = sql.strip().rstrip(";")

    if settings.SAFE_MODE:
        first_word = sql_stripped.split()[0].upper()
        if first_word not in ("SELECT", "WITH"):
            raise ValueError(
                f"SAFE_MODE is enabled — only SELECT queries are allowed. "
                f"Got: {first_word}"
            )

    result = db.execute(text(sql_stripped))
    columns = list(result.keys())
    rows = [dict(zip(columns, row)) for row in result.fetchall()]
    return {"columns": columns, "rows": rows, "row_count": len(rows)}


# ---------------------------------------------------------------------------
# Sample data seeder (for demo / first run)
# ---------------------------------------------------------------------------

def seed_sample_data() -> None:
    """
    Create and populate demo tables if they don't exist yet.
    Safe to call multiple times — uses CREATE TABLE IF NOT EXISTS.
    """
    if _engine is None:
        if settings.DATABASE_URL:
            init_engine(settings.DATABASE_URL)
        else:
            raise RuntimeError("No database connected to seed sample data.")

    ddl_and_inserts = """
    CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        department TEXT NOT NULL,
        salary REAL NOT NULL,
        hire_date TEXT NOT NULL,
        manager_id INTEGER
    );

    CREATE TABLE IF NOT EXISTS departments (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        budget REAL NOT NULL,
        location TEXT
    );

    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        department_id INTEGER,
        start_date TEXT,
        end_date TEXT,
        status TEXT DEFAULT 'active',
        FOREIGN KEY (department_id) REFERENCES departments(id)
    );

    CREATE TABLE IF NOT EXISTS employee_projects (
        employee_id INTEGER,
        project_id INTEGER,
        role TEXT,
        PRIMARY KEY (employee_id, project_id),
        FOREIGN KEY (employee_id) REFERENCES employees(id),
        FOREIGN KEY (project_id) REFERENCES projects(id)
    );
    """

    inserts = """
    INSERT OR IGNORE INTO departments VALUES (1, 'Engineering', 1200000, 'Bangalore');
    INSERT OR IGNORE INTO departments VALUES (2, 'Marketing', 500000, 'Mumbai');
    INSERT OR IGNORE INTO departments VALUES (3, 'HR', 300000, 'Delhi');
    INSERT OR IGNORE INTO departments VALUES (4, 'Finance', 700000, 'Bangalore');

    INSERT OR IGNORE INTO employees VALUES (1, 'Arjun Sharma', 'Engineering', 95000, '2020-03-15', NULL);
    INSERT OR IGNORE INTO employees VALUES (2, 'Priya Nair', 'Engineering', 87000, '2021-06-01', 1);
    INSERT OR IGNORE INTO employees VALUES (3, 'Rohan Mehta', 'Marketing', 72000, '2019-11-10', NULL);
    INSERT OR IGNORE INTO employees VALUES (4, 'Sneha Pillai', 'HR', 65000, '2022-01-20', NULL);
    INSERT OR IGNORE INTO employees VALUES (5, 'Vikram Iyer', 'Finance', 110000, '2018-08-05', NULL);
    INSERT OR IGNORE INTO employees VALUES (6, 'Ananya Das', 'Engineering', 78000, '2023-02-14', 1);
    INSERT OR IGNORE INTO employees VALUES (7, 'Kiran Rao', 'Marketing', 68000, '2021-09-30', 3);
    INSERT OR IGNORE INTO employees VALUES (8, 'Meera Joshi', 'Finance', 95000, '2020-07-22', 5);

    INSERT OR IGNORE INTO projects VALUES (1, 'DataPipeline Overhaul', 1, '2024-01-01', '2024-06-30', 'active');
    INSERT OR IGNORE INTO projects VALUES (2, 'Brand Refresh', 2, '2024-02-01', '2024-04-30', 'completed');
    INSERT OR IGNORE INTO projects VALUES (3, 'ERP Migration', 4, '2023-10-01', '2024-12-31', 'active');
    INSERT OR IGNORE INTO projects VALUES (4, 'AI Middleware', 1, '2024-03-01', NULL, 'active');

    INSERT OR IGNORE INTO employee_projects VALUES (1, 1, 'Lead');
    INSERT OR IGNORE INTO employee_projects VALUES (2, 1, 'Developer');
    INSERT OR IGNORE INTO employee_projects VALUES (6, 4, 'Developer');
    INSERT OR IGNORE INTO employee_projects VALUES (1, 4, 'Architect');
    INSERT OR IGNORE INTO employee_projects VALUES (3, 2, 'Lead');
    INSERT OR IGNORE INTO employee_projects VALUES (7, 2, 'Analyst');
    INSERT OR IGNORE INTO employee_projects VALUES (5, 3, 'Lead');
    INSERT OR IGNORE INTO employee_projects VALUES (8, 3, 'Analyst');
    """

    with get_engine().connect() as conn:
        for stmt in ddl_and_inserts.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(text(stmt))
        for stmt in inserts.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(text(stmt))
        conn.commit()

    logger.info("✅ Sample data seeded successfully.")


# Initialize engine if DATABASE_URL is already configured.
try:
    if settings.DATABASE_URL:
        init_engine(settings.DATABASE_URL)
except Exception as exc:
    logger.warning(f"Database initialization skipped: {exc}")
