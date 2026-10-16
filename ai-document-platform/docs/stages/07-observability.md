# Этап 7. Observability

## Архитектура сборки метрик

```
            Prometheus (monitoring)
                    │ scrape каждые 15s
     ┌──────────────┼──────────────┐
     ▼              ▼              ▼
   api:8000    ocr-worker:9090  llm-worker:9091
  /metrics       /metrics        /metrics
```

## Типы метрик Prometheus

| Тип | Описание | Пример |
|-----|----------|--------|
| **Counter** | Только растёт | `ocr_processed_total` |
| **Gauge** | Растёт и падает | `ocr_active_jobs` |
| **Histogram** | Распределение по buckets | `ocr_duration_seconds` |
| **Summary** | Процентили на стороне приложения | — |

---

## Golden Signals (Google SRE)

| Signal | Что | Метрика |
|--------|-----|---------|
| Latency | Как долго | `histogram_quantile(0.95, rate(..._bucket[5m]))` |
| Traffic | Сколько | `rate(http_requests_total[5m])` |
| Errors | Ошибки | `rate(http_requests_total{status=~"5.."}[5m])` |
| Saturation | Загрузка | `process_resident_memory_bytes` |

Для сервисов — **RED** (Rate, Errors, Duration).
Для ресурсов — **USE** (Utilization, Saturation, Errors).

---

## Дашборды

| Дашборд | Назначение |
|---------|-----------|
| Overview | Бизнес-метрики: документы в пайплайне |
| API Golden Signals | RPS, latency p50/p95/p99, error ratio |
| OCR Performance | Производительность OCR с разбивкой ошибок |
| LLM Performance | Производительность LLM, токены, latency Ollama |

![Overview Dashboard](../src/img/overview.png)

![API Golden Signals](../src/img/api_golden_signals.png)

---

## PromQL: основы

### Типы данных

| Тип | Пример |
|-----|--------|
| Instant vector | `http_requests_total` |
| Range vector | `http_requests_total[5m]` |
| Scalar | `42` |

### Основные функции

| Функция | Что |
|---------|-----|
| `rate(v[5m])` | Скорость counter |
| `increase(v[1h])` | Прирост за час |
| `sum by (l) (v)` | Сумма с группировкой |
| `histogram_quantile(q, v)` | Процентиль |

### Паттерны

- **Доля:** `sum(numerator) / sum(denominator)`
- **Процентиль:** `histogram_quantile(0.95, sum by (le) (rate(..._bucket[5m])))`
- **«Нет данных = 0»:** `выражение or vector(0)`

---

## SLI / SLO / SLA

```
SLI  →  SLO  →  SLA
что      цель     обещание
мерим   для себя клиенту
```

| Термин | Что это |
|--------|---------|
| **SLI** | Метрика качества: `(хорошие события) / (всего)` |
| **SLO** | Целевое значение SLI (внутренняя цель) |
| **SLA** | Юридическое обязательство с последствиями |
| **Error Budget** | `1 − SLO` — сколько ошибок допустимо |
| **Burn Rate** | Скорость расхода Error Budget |

> SLA всегда слабее SLO на 0.3-0.5%.

---

## PrometheusRule

CRD для декларативного описания алертов. Prometheus Operator автоматически подхватывает.

![Prometheus Rules](../src/img/prometheus-rules.png)
