# Этап 8. KEDA

**KEDA** (Kubernetes Event-Driven Autoscaling) — оператор, который масштабирует поды по внешним событиям, а не по CPU/памяти.

## Зачем KEDA вместо HPA

- В `ocr.queue` скопилось 50 задач → KEDA поднимает OCR-воркеры с 2 до N
- HPA масштабирует по CPU. OCR-воркер, ожидающий RabbitMQ, почти не ест CPU → HPA не сработает

## Настройка

```bash
helm install keda kedacore/keda --namespace keda
```

KEDA ходит напрямую в Management API RabbitMQ (не через Prometheus).

### Копирование Secret

```bash
kubectl -n queue get secret rabbitmq-credentials -o yaml | \
  sed 's/namespace: queue/namespace: ai-doc-platform/' | \
  kubectl apply -f -
```

Необходимы: `TriggerAuthentication` и `ScaledObject`.

---

## Нагрузочное тестирование

```bash
seq 1 100 | xargs -P 10 -I {} curl -k -s -X POST https://documents.local/documents \
  -F "file=@/tmp/test.pdf;type=application/pdf" \
  -o /dev/null
```

![KEDA Test](../src/img/test-keda.png)

---

## Проблемы

При тестировании не все запланированные поды поднялись:
- `Insufficient CPU/memory`
- taints
- лимит подов на ноде

**Диагностика:**
```bash
kubectl describe pod <pending-pod>
kubectl top nodes
kubectl describe node
```

**Решения:**
- Понизить `maxReplicaCount` в ScaledObject
- Уменьшить `requests` в подах
- Добавить ноды
- Использовать cluster-autoscaler

**Результат:** В dev-кластере из 3 нод: `maxReplicaCount` OCR = 4, LLM = 3 — подобрано эмпирически.
