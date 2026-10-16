# Этап 3. Приложения

Разработка трёх микросервисов на Python 3.12 с async/await.

## Сервисы

| Сервис | Порт | Очередь | Назначение |
|--------|------|---------|------------|
| **api** | 8080 | — | REST API, приём PDF |
| **ocr-worker** | 9090 | ocr.queue | Извлечение текста |
| **llm-worker** | 9091 | llm.queue | Структурирование JSON |

## Технологии

| Компонент | Библиотека |
|-----------|------------|
| API Framework | FastAPI |
| ORM | SQLAlchemy 2.0 async + asyncpg |
| Очередь | aio-pika (RabbitMQ) |
| S3 | aioboto3 |
| HTTP клиент | httpx |
| OCR | pytesseract |
| Конфигурация | pydantic-settings |
| Метрики | prometheus-client |

## Структура сервиса

```
apps/api/
├── pyproject.toml          # Зависимости (uv)
├── Dockerfile              # Multi-stage build
├── .env                    # Локальная конфигурация
└── src/api/
    ├── main.py             # Entrypoint
    ├── config.py           # Settings (pydantic)
    ├── db.py               # SQLAlchemy async
    ├── rabbit.py           # RabbitMQ client
    ├── s3.py               # MinIO client
    ├── models.py           # DB models
    ├── schemas.py          # Pydantic schemas
    └── routes/
        ├── documents.py    # Upload, status, result
        ├── health.py       # /healthz, /readyz
        └── metrics.py      # /metrics
```

## Запуск локально

```bash
# API
cd apps/api
uv sync
uv run uvicorn api.main:app --host 127.0.0.1 --port 8080 --reload

# OCR Worker
cd apps/ocr-worker
uv sync
uv run python -m ocr_worker.main

# LLM Worker
cd apps/llm-worker
uv sync
uv run python -m llm_worker.main
```

## Docker

```bash
docker build -t ai-doc-api:latest apps/api/
docker build -t ai-doc-ocr:latest apps/ocr-worker/
docker build -t ai-doc-llm:latest apps/llm-worker/
```

## Поток данных

1. **POST /documents** — API сохраняет PDF в S3, создаёт запись в БД, публикует в `ocr.queue`
2. **OCR Worker** — читает PDF, извлекает текст (Tesseract), сохраняет в S3, публикует в `llm.queue`
3. **LLM Worker** — читает текст, отправляет в Ollama, сохраняет JSON в S3, обновляет статус
4. **GET /documents/{id}/result** — API возвращает JSON из S3

## Health Checks

| Endpoint | Что проверяет |
|----------|---------------|
| `/healthz` | Сервис жив |
| `/readyz` | БД, S3, RabbitMQ доступны |
| `/metrics` | Prometheus метрики |
