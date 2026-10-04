"""Prompt templates for the LLM extraction task.

The prompt asks Ollama to return a strict JSON object with a fixed schema.
This version was validated against llama3.1:8b on 2026-10-04 with an
invoice sample and produced correct structure, roles and types.
"""

PROMPT_VERSION = "1.0.0"


SYSTEM_PROMPT = (
    "Ты — эксперт по извлечению структурированных данных из документов. "
    "Ты всегда возвращаешь только валидный JSON без markdown, комментариев "
    "и пояснений."
)


_JSON_SCHEMA = """{
  "document_type": "invoice|contract|act|receipt|other",
  "summary": "строка, 1-2 предложения",
  "confidence": число от 0.0 до 1.0,
  "parties": [
    {"role": "seller|buyer|contractor|customer|other",
     "name": "строка или null",
     "inn": "строка или null",
     "kpp": "строка или null"}
  ],
  "amounts": [
    {"role": "total|vat|subtotal|other",
     "value": число,
     "currency": "строка, обычно RUB"}
  ],
  "dates": [
    {"type": "issue|due|signing|other",
     "value": "YYYY-MM-DD"}
  ],
  "line_items": [
    {"description": "строка",
     "quantity": число или null,
     "unit_price": число или null,
     "total": число или null}
  ],
  "key_terms": ["строка"]
}"""


_USER_PROMPT_TEMPLATE = """Верни СТРОГО JSON следующей структуры:

{schema}

ВАЖНО:
- role в amounts — это ТИП суммы (total, vat, subtotal), НЕ сторона сделки.
- value в amounts — ЧИСЛО, не строка.
- confidence — твоя оценка уверенности от 0.0 до 1.0.
- Не добавляй markdown, комментарии и пояснения.
- Если поле не найдено в тексте — null или пустой массив.

Текст документа:
{text}"""


def build_user_prompt(text: str) -> str:
    """Build the user-facing prompt for a given document text."""
    return _USER_PROMPT_TEMPLATE.format(
        schema=_JSON_SCHEMA,
        text=text,
    )