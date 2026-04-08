# Database Middleware — NLP to SQL + SLM

A FastAPI-based middleware that converts **natural-language questions into SQL queries** using a **Small Language Model (SLM)**, then executes them against a relational database.

---

## Architecture

```
User Question (English)
        │
        ▼
┌─────────────────────┐
│   FastAPI Endpoint  │  POST /api/v1/query
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Schema Introspector│  Reads DB tables → builds DDL string
└────────┬────────────┘
         │ DDL context
         ▼
┌─────────────────────┐
│   Prompt Builder    │  DDL + few-shot examples + question → prompt
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│    SLM Inference    │  google/flan-t5-base (default)
│  (HuggingFace)      │  microsoft/phi-2
│                     │  TinyLlama/TinyLlama-1.1B-Chat-v1.0
└────────┬────────────┘
         │ raw SQL
         ▼
┌─────────────────────┐
│  SQL Post-Processor │  Strip fences, extract statement, add semicolon
└────────┬────────────┘
         │ clean SQL
         ▼
┌─────────────────────┐
│  Query Executor     │  SQLAlchemy + SAFE_MODE guard
└────────┬────────────┘
         │
         ▼
     JSON Response
```

---

## Project Structure

```
.
├── app/
│   ├── __init__.py
│   ├── main.py            ← FastAPI app + lifecycle events
│   ├── config.py          ← Settings from .env
│   ├── db/
│   │   ├── __init__.py
│   │   └── database.py    ← Engine, session, schema introspection, seeder
│   ├── models/
│   │   ├── __init__.py
│   │   ├── sql_generator.py  ← SLM inference + prompt engineering
│   │   └── schemas.py     ← Pydantic request/response models
│   └── routes/
│       ├── __init__.py
│       └── api.py         ← All route handlers
├── tests/
│   └── test_api.py
├── .env
├── requirements.txt
└── README.md
```

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure `.env`

```env
DATABASE_URL=sqlite:///./company.db
SLM_MODEL_NAME=google/flan-t5-base   # fastest on CPU
SAFE_MODE=true
```

### 3. Run the server

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The server will automatically create and seed a demo SQLite database on first run.

### 4. Open the docs

- Swagger UI → http://localhost:8000/docs  
- ReDoc      → http://localhost:8000/redoc

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | API home |
| POST | `/api/v1/query` | **NLP → SQL → execute** |
| POST | `/api/v1/execute` | Run raw SQL |
| GET | `/api/v1/schema` | Full DB schema (JSON + DDL) |
| GET | `/api/v1/tables` | List table names |
| GET | `/api/v1/health` | Health check |

---

## Example Usage

### NLP Query

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Show me the top 3 highest paid employees",
    "execute": true,
    "use_model": true
  }'
```

Response:
```json
{
  "question": "Show me the top 3 highest paid employees",
  "generated_sql": "SELECT name, salary FROM employees ORDER BY salary DESC LIMIT 3;",
  "method": "slm",
  "model_used": "google/flan-t5-base",
  "confidence": "high",
  "result": {
    "columns": ["name", "salary"],
    "rows": [
      {"name": "Vikram Iyer", "salary": 110000},
      {"name": "Arjun Sharma", "salary": 95000},
      {"name": "Meera Joshi", "salary": 95000}
    ],
    "row_count": 3
  }
}
```

### Skip the SLM (faster, rule-based)

```json
{ "question": "average salary", "use_model": false }
```

### Raw SQL

```bash
curl -X POST http://localhost:8000/api/v1/execute \
  -H "Content-Type: application/json" \
  -d '{"sql": "SELECT department, COUNT(*) FROM employees GROUP BY department;"}'
```

---

## Supported SLMs

| Model | Size | Speed (CPU) | Notes |
|-------|------|-------------|-------|
| `google/flan-t5-base` | ~250 MB | Fast | **Recommended default** |
| `microsoft/phi-2` | ~2.8 GB | Slow | Higher accuracy |
| `TinyLlama/TinyLlama-1.1B-Chat-v1.0` | ~600 MB | Medium | Good balance |

Change via `.env`:
```env
SLM_MODEL_NAME=microsoft/phi-2
```

---

## Running Tests

```bash
pytest tests/ -v
```

---

## SAFE_MODE

When `SAFE_MODE=true` (default), only `SELECT` and `WITH` queries are allowed through the executor. Any attempt to run `DROP`, `INSERT`, `UPDATE`, or `DELETE` via `/api/v1/execute` will return HTTP 403.

The NLP endpoint generates queries based on the schema context and few-shot examples, which naturally biases toward SELECT statements.

---

## Demo Database Schema

The seeder creates four tables on first run:

- **employees** (id, name, department, salary, hire_date, manager_id)
- **departments** (id, name, budget, location)
- **projects** (id, title, department_id, start_date, end_date, status)
- **employee_projects** (employee_id, project_id, role)
