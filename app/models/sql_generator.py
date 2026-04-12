import re
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

_model = None
_tokenizer = None
_model_name: Optional[str] = None


# ---------------- MODEL LOADER ----------------
def _load_model(model_name: str):
    global _model, _tokenizer, _model_name

    if _model is not None and _model_name == model_name:
        return _model, _tokenizer

    from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
    import torch
    from app.config import settings

    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSeq2SeqLM.from_pretrained(model_name)

    model = model.to(settings.DEVICE)
    model.eval()

    _model = model
    _tokenizer = tokenizer
    _model_name = model_name

    logger.info(f"✅ Model loaded: {model_name}")
    return model, tokenizer


# ---------------- PROMPT ----------------
def build_prompt(nl: str, ddl: str) -> str:
    return f"""
Convert natural language to SQL.

Schema:
{ddl}

Rules:
- Use only given tables
- Avoid unnecessary joins
- Return only SQL

Q: Show all customers
SQL: SELECT * FROM customers;

Q: Get all orders
SQL: SELECT * FROM orders;

Q: Get all order items
SQL: SELECT * FROM order_items;

Q: Top 5 products
SQL: SELECT * FROM products ORDER BY price DESC LIMIT 5;

Now convert:
Q: {nl}
SQL:
"""


# ---------------- MODEL GENERATION ----------------
def _generate(prompt: str, model_name: str):
    import torch
    from app.config import settings

    model, tokenizer = _load_model(model_name)

    inputs = tokenizer(prompt, return_tensors="pt", truncation=True).to(settings.DEVICE)

    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=120)

    return tokenizer.decode(out[0], skip_special_tokens=True)


# ---------------- CLEAN SQL ----------------
def _clean_sql(text: str):
    if "SQL:" in text:
        text = text.split("SQL:")[-1]

    text = text.strip()

    if ";" in text:
        text = text.split(";")[0] + ";"

    return text


# ---------------- TABLE MATCH ----------------
def _match_table(question: str, ddl: str):
    tables = re.findall(r"CREATE\s+TABLE\s+(\w+)", ddl, re.IGNORECASE)
    q = question.lower()

    for t in tables:
        if t.lower() in q:
            return t
        if t.lower().replace("_", " ") in q:
            return t

    return tables[0] if tables else "table_name"


# ---------------- RULE FALLBACK ----------------
def _fallback(question: str, ddl: str):
    table = _match_table(question, ddl)
    q = question.lower()

    if "count" in q:
        return f"SELECT COUNT(*) FROM {table};"

    if "top" in q:
        return f"SELECT * FROM {table} LIMIT 5;"

    return f"SELECT * FROM {table} LIMIT 10;"


# ---------------- MAIN ----------------
def generate_sql(
    natural_language: str,
    ddl: str,
    model_name: Optional[str] = None,
    use_model: bool = True,
) -> Dict[str, Any]:

    from app.config import settings
    model_name = model_name or settings.SLM_MODEL_NAME

    q = natural_language.lower()
    table = _match_table(natural_language, ddl)

    # ---------------- COUNT FIX ----------------
    if "count" in q:
        return {
            "sql": f"SELECT COUNT(*) FROM {table};",
            "method": "count_override",
            "model_used": None,
            "confidence": "high",
        }

    # ---------------- TOP / EXPENSIVE ----------------
    if "top" in q or "expensive" in q or "highest" in q:
        if "5" in q:
            return {
                "sql": f"SELECT * FROM {table} ORDER BY price DESC LIMIT 5;",
                "method": "top_override",
                "model_used": None,
                "confidence": "high",
            }
        else:
            return {
                "sql": f"SELECT * FROM {table} ORDER BY price DESC;",
                "method": "sort_override",
                "model_used": None,
                "confidence": "high",
            }

    # ---------------- FAST PATH ----------------
    if any(word in q for word in ["all", "show", "list", "get"]):
        return {
            "sql": f"SELECT * FROM {table};",
            "method": "fast_path",
            "model_used": None,
            "confidence": "high",
        }

    # ---------------- MODEL ----------------
    if use_model:
        try:
            prompt = build_prompt(natural_language, ddl)
            raw = _generate(prompt, model_name)
            sql = _clean_sql(raw)

            if not sql.lower().startswith("select"):
                raise ValueError("Invalid SQL")

            return {
                "sql": sql,
                "method": "model",
                "model_used": model_name,
                "confidence": "medium",
            }

        except Exception as e:
            logger.warning(f"Model failed: {e}")

    # ---------------- FALLBACK ----------------
    return {
        "sql": _fallback(natural_language, ddl),
        "method": "fallback",
        "model_used": None,
        "confidence": "low",
    }