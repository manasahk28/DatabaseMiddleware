# Database Middleware — NLP to SQL + SLM

A full-stack middleware system that lets you **ask questions in plain English** and get back **SQL queries with live results** — powered by a Small Language Model (SLM) running locally. Includes a chatbot UI, a FastAPI backend, and support for any database via schema DDL.

---

## What It Does

You type:
> *"Show me the top 3 highest paid employees"*

The system returns:
```sql
SELECT name, salary FROM employees ORDER BY salary DESC LIMIT 3;
```
Plus the actual query results — all in a chat interface.

---

## Architecture

```
Browser (index.html)
        │  HTTP POST /api/v1/query
        ▼
┌─────────────────────┐
│   FastAPI Backend   │
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
│   (HuggingFace)     │  microsoft/phi-2
│                     │  TinyLlama/TinyLlama-1.1B-Chat-v1.0
└────────┬────────────┘
         │ raw output
         ▼
┌─────────────────────┐
│  SQL Post-Processor │  Strips fences, extracts statement, adds semicolon
└────────┬────────────┘
         │ clean SQL
         ▼
┌─────────────────────┐
│  Query Executor     │  SQLAlchemy + SAFE_MODE guard
└────────┬────────────┘
         │
         ▼
    JSON Response → Chat UI renders results
```

---

## Project Structure

```
.
├── app/
│   ├── __init__.py
│   ├── main.py                ← FastAPI app, CORS, lifespan
│   ├── config.py              ← All settings loaded from .env
│   ├── db/
│   │   ├── __init__.py
│   │   └── database.py        ← Engine, sessions, schema introspection, seeder
│   ├── models/
│   │   ├── __init__.py
│   │   ├── sql_generator.py   ← SLM inference, prompt engineering, fallback
│   │   └── schemas.py         ← Pydantic request/response models
│   └── routes/
│       ├── __init__.py
│       └── api.py             ← All API route handlers
├── ui/
│   └── index.html             ← Chatbot UI (open directly in browser)
├── tests/
│   └── test_api.py            ← 16 test cases
├── .env                       ← Configuration
├── requirements.txt
└── README.md
```

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

> Requires Python 3.10+ (tested on Python 3.13 Windows)

### 2. Configure `.env`

```env
DATABASE_URL=sqlite:///./company.db
SLM_MODEL_NAME=google/flan-t5-base
SAFE_MODE=true
DEVICE=cpu
```

### 3. Start the backend

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

On first run, the server automatically creates and seeds a demo SQLite database with sample company data.

### 4. Open the Chat UI

Open `ui/index.html` directly in your browser (no extra server needed).

The UI auto-connects to `localhost:8000` and you can start asking questions immediately.

### 5. API docs (optional)

- Swagger UI → http://localhost:8000/docs
- ReDoc      → http://localhost:8000/redoc

---

## Chat UI Features

The UI (`ui/index.html`) is a standalone HTML file — no build step, no npm, just open it in a browser.

- **Chatbot interface** — questions on the right, SQL + results on the left
- **Multi-database support** — connect any DB by pasting its schema DDL, or use the built-in demo DB
- **Auto schema detection** — if no DB is connected when you ask a question, it prompts you to set one up
- **Results table** — scrollable table with column headers and row count
- **SQL display** — generated SQL shown in a code block above results
- **Method badges** — shows whether AI model or rule-based fallback was used, and confidence level
- **Quick hint buttons** — one-click common queries
- **Toggles** — switch between AI model / rule-based, and generate-only / generate+execute

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | API home |
| POST | `/api/v1/query` | NLP question → SQL → (optional) execute |
| POST | `/api/v1/execute` | Run raw SQL directly |
| GET | `/api/v1/schema` | Full DB schema as JSON + DDL |
| GET | `/api/v1/tables` | List table names |
| GET | `/api/v1/health` | Health check |

### POST /api/v1/query — request body

```json
{
  "question": "Show me the top 3 highest paid employees",
  "execute": true,
  "use_model": true
}
```

### POST /api/v1/query — response

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

---

## Supported SLMs

| Model | Size | Speed (CPU) | Recommended |
|-------|------|-------------|-------------|
| `google/flan-t5-base` | ~250 MB | Fast | Yes — default |
| `TinyLlama/TinyLlama-1.1B-Chat-v1.0` | ~600 MB | Medium | Good balance |
| `microsoft/phi-2` | ~2.8 GB | Slow | Highest accuracy |

Change model in `.env`:
```env
SLM_MODEL_NAME=microsoft/phi-2
```

The model downloads automatically from HuggingFace on first use.

---

## Multi-Database Support

The system supports any relational database. To use your own DB:

**Option 1 — via the UI:**
Click "Change DB" → "Paste schema DDL" → paste your `CREATE TABLE` statements.

**Option 2 — via `.env`:**
```env
DATABASE_URL=postgresql://user:password@localhost:5432/mydb
DATABASE_TYPE=postgresql
```
Then install the driver:
```bash
pip install psycopg2-binary   # PostgreSQL
pip install pymysql           # MySQL
```

**Option 3 — via API:**
Use `POST /api/v1/query` with your question — it always introspects the live DB schema automatically.

---

## SAFE_MODE

When `SAFE_MODE=true` (default), only `SELECT` and `WITH` queries are allowed. Any `DROP`, `INSERT`, `UPDATE`, or `DELETE` via `/api/v1/execute` returns HTTP 403. The NLP endpoint is naturally biased toward SELECT queries due to the few-shot examples in the prompt.

Disable only if you need write access:
```env
SAFE_MODE=false
```

---

## Demo Database

The seeder creates four tables with Indian company sample data on first run:

| Table | Columns |
|-------|---------|
| `employees` | id, name, department, salary, hire_date, manager_id |
| `departments` | id, name, budget, location |
| `projects` | id, title, department_id, start_date, end_date, status |
| `employee_projects` | employee_id, project_id, role |

Try these questions to get started:
- "Show all employees in Engineering"
- "What is the average salary by department?"
- "List all active projects"
- "Top 5 highest paid employees"
- "Count employees per department"
- "Show employees and their projects"

---

## Running Tests

```bash
pytest tests/ -v
```

Tests use an in-memory SQLite database and the rule-based fallback — no GPU or model download required.

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `fastapi` | >=0.115.0 | API framework |
| `uvicorn` | >=0.30.0 | ASGI server |
| `sqlalchemy` | >=2.0.36 | ORM + query execution |
| `transformers` | >=4.40.0 | HuggingFace SLM loading |
| `torch` | >=2.1.0 | Model inference |
| `pydantic` | >=2.7.0 | Request/response validation |
| `python-dotenv` | >=1.0.0 | .env config loading |
| `sentencepiece` | >=0.2.0 | Tokenizer support |
| `accelerate` | >=0.26.0 | Optimized model loading |

> All versions are minimum bounds compatible with Python 3.13 on Windows.
