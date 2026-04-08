"""
NLP → SQL Generator using a Small Language Model (SLM).

Strategy
--------
1. Build a schema-aware prompt (DDL + few-shot examples).
2. Run inference with the configured SLM (default: google/flan-t5-base).
3. Post-process the output to extract a clean SQL statement.
4. Fall back to a lightweight rule-based parser when the model is not
   loaded (useful during development / unit tests).

Supported SLMs (all run on CPU):
  - google/flan-t5-base      (~250 MB, fast, good accuracy)
  - microsoft/phi-2          (~2.8 GB, slower, higher accuracy)
  - TinyLlama/TinyLlama-1.1B-Chat-v1.0
"""

import re
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy model loader (singleton)
# ---------------------------------------------------------------------------

_model = None
_tokenizer = None
_model_name: Optional[str] = None


def _load_model(model_name: str):
    """Load the SLM once and cache it for the lifetime of the process."""
    global _model, _tokenizer, _model_name

    if _model is not None and _model_name == model_name:
        return _model, _tokenizer

    logger.info(f"⏳ Loading SLM: {model_name} (this may take a minute)…")

    from transformers import AutoTokenizer, AutoModelForSeq2SeqLM, AutoModelForCausalLM
    import torch
    from app.config import settings

    device = settings.DEVICE

    try:
        tokenizer = AutoTokenizer.from_pretrained(model_name)

        # Seq2Seq models (T5 family)
        if "t5" in model_name.lower() or "flan" in model_name.lower():
            model = AutoModelForSeq2SeqLM.from_pretrained(model_name)
        else:
            # Causal / decoder-only (Phi, TinyLlama, …)
            model = AutoModelForCausalLM.from_pretrained(
                model_name,
                torch_dtype=torch.float32,
                low_cpu_mem_usage=True,
            )

        model = model.to(device)
        model.eval()

        _model = model
        _tokenizer = tokenizer
        _model_name = model_name
        logger.info(f"✅ SLM loaded: {model_name}")
        return _model, _tokenizer

    except Exception as exc:
        logger.error(f"❌ Failed to load SLM '{model_name}': {exc}")
        raise


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

FEW_SHOT_EXAMPLES = """
-- Question: Show all employees
-- SQL: SELECT * FROM employees;

-- Question: List employees in Engineering department
-- SQL: SELECT * FROM employees WHERE department = 'Engineering';

-- Question: What is the average salary?
-- SQL: SELECT AVG(salary) AS average_salary FROM employees;

-- Question: Count employees per department
-- SQL: SELECT department, COUNT(*) AS employee_count FROM employees GROUP BY department;

-- Question: Show the top 3 highest paid employees
-- SQL: SELECT name, salary FROM employees ORDER BY salary DESC LIMIT 3;

-- Question: List all active projects
-- SQL: SELECT * FROM projects WHERE status = 'active';

-- Question: Show employees who joined after 2021
-- SQL: SELECT * FROM employees WHERE hire_date > '2021-01-01';

-- Question: What is the total salary budget per department?
-- SQL: SELECT department, SUM(salary) AS total_salary FROM employees GROUP BY department;

-- Question: Show employees and their projects
-- SQL: SELECT e.name, p.title FROM employees e JOIN employee_projects ep ON e.id = ep.employee_id JOIN projects p ON ep.project_id = p.id;
"""


def build_prompt(natural_language: str, ddl: str) -> str:
    """Construct the prompt sent to the SLM."""
    return (
        f"You are an expert SQL generator. Given the database schema below, "
        f"convert the natural language question into a valid SQL query.\n\n"
        f"### Database Schema:\n{ddl}\n\n"
        f"### Examples:\n{FEW_SHOT_EXAMPLES}\n"
        f"### Question: {natural_language}\n"
        f"### SQL:"
    )


# ---------------------------------------------------------------------------
# Model inference
# ---------------------------------------------------------------------------

def _generate_with_model(prompt: str, model_name: str) -> str:
    """Run the prompt through the SLM and return raw output text."""
    import torch
    from app.config import settings

    model, tokenizer = _load_model(model_name)
    device = settings.DEVICE

    inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=1024).to(device)

    with torch.no_grad():
        if "t5" in model_name.lower() or "flan" in model_name.lower():
            outputs = model.generate(
                **inputs,
                max_new_tokens=150,
                num_beams=4,
                early_stopping=True,
            )
        else:
            outputs = model.generate(
                **inputs,
                max_new_tokens=150,
                temperature=0.1,
                do_sample=False,
                pad_token_id=tokenizer.eos_token_id,
            )

    return tokenizer.decode(outputs[0], skip_special_tokens=True)


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------

def _extract_sql(raw: str) -> str:
    """
    Pull a clean SQL statement out of messy model output.
    Handles markdown fences, extra commentary, and incomplete statements.
    """
    # Strip markdown SQL fences
    raw = re.sub(r"```sql", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"```", "", raw)

    # If the model echoed the prompt header, grab everything after "SQL:"
    if "### SQL:" in raw:
        raw = raw.split("### SQL:")[-1]
    elif "SQL:" in raw:
        raw = raw.split("SQL:")[-1]

    # Take only the first statement
    raw = raw.strip()
    if ";" in raw:
        raw = raw.split(";")[0] + ";"
    elif "\n\n" in raw:
        raw = raw.split("\n\n")[0]

    # Ensure it ends with a semicolon
    raw = raw.strip()
    if raw and not raw.endswith(";"):
        raw += ";"

    return raw


# ---------------------------------------------------------------------------
# Rule-based fallback (no model required)
# ---------------------------------------------------------------------------

_KEYWORD_MAP = {
    r"\ball\b.*\bemployee": "SELECT * FROM employees;",
    r"\blist\b.*\bemployee": "SELECT * FROM employees;",
    r"\bshow\b.*\bemployee": "SELECT * FROM employees;",
    r"\baverage salary\b": "SELECT AVG(salary) AS average_salary FROM employees;",
    r"\bhighest.paid\b": "SELECT name, salary FROM employees ORDER BY salary DESC LIMIT 5;",
    r"\btop \d+ .* paid\b": "SELECT name, salary FROM employees ORDER BY salary DESC LIMIT 5;",
    r"\bcount\b.*\bdepartment\b": "SELECT department, COUNT(*) AS count FROM employees GROUP BY department;",
    r"\ball\b.*\bdepartment": "SELECT * FROM departments;",
    r"\bactive project": "SELECT * FROM projects WHERE status = 'active';",
    r"\ball\b.*\bproject": "SELECT * FROM projects;",
    r"\btotal salary\b": "SELECT department, SUM(salary) AS total FROM employees GROUP BY department;",
}


def _rule_based_fallback(question: str) -> str:
    """Very simple keyword-to-SQL mapper used when no SLM is available."""
    q = question.lower()
    for pattern, sql in _KEYWORD_MAP.items():
        if re.search(pattern, q):
            return sql
    return "SELECT * FROM employees LIMIT 10;"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_sql(
    natural_language: str,
    ddl: str,
    model_name: Optional[str] = None,
    use_model: bool = True,
) -> Dict[str, Any]:
    """
    Convert a natural-language question to SQL.

    Parameters
    ----------
    natural_language : str   The user's question.
    ddl              : str   DDL string describing the database schema.
    model_name       : str   HuggingFace model ID (falls back to settings).
    use_model        : bool  If False, skip the SLM and use the rule-based fallback.

    Returns
    -------
    dict with keys: sql, method, model_used, confidence
    """
    from app.config import settings

    model_name = model_name or settings.SLM_MODEL_NAME

    if not use_model:
        sql = _rule_based_fallback(natural_language)
        return {
            "sql": sql,
            "method": "rule_based_fallback",
            "model_used": None,
            "confidence": "low",
        }

    try:
        prompt = build_prompt(natural_language, ddl)
        raw_output = _generate_with_model(prompt, model_name)
        sql = _extract_sql(raw_output)

        # Basic sanity check
        if not sql.strip().upper().startswith(("SELECT", "WITH", "INSERT", "UPDATE", "DELETE")):
            logger.warning("Model output didn't look like SQL — falling back to rule-based.")
            sql = _rule_based_fallback(natural_language)
            method = "rule_based_fallback"
            confidence = "low"
        else:
            method = "slm"
            confidence = "high"

        return {
            "sql": sql,
            "method": method,
            "model_used": model_name,
            "confidence": confidence,
        }

    except Exception as exc:
        logger.warning(f"SLM inference failed ({exc}), using rule-based fallback.")
        sql = _rule_based_fallback(natural_language)
        return {
            "sql": sql,
            "method": "rule_based_fallback",
            "model_used": None,
            "confidence": "low",
            "error": str(exc),
        }
