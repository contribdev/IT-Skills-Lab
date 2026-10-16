# Troubleshooting: Insufficient CPU

После перезагрузки ПК столкнулся с проблемами:
- Prometheus работал некорректно, метрики приходили рваные
- KEDA не мог создать новые поды: `Insufficient CPU`

## Requests vs Limits

| | CPU | Memory |
|---|-----|--------|
| **Requests** | Гарантированная доля, резервируется scheduler | OOM score |
| **Limits** | Throttling при превышении | OOMKill при превышении |
| **При превышении** | Процесс замораживается (100ms) | Под убивается (SIGKILL) |
| **Обратимо?** | Да | Нет, перезапуск |

> **CPU — сжимаемый ресурс. Memory — не сжимаемый.**

---

## Диагностика

```bash
# Реальное использование
kubectl top nodes

# Requests на нодах
kubectl describe nodes | grep -A5 "Allocated resources"

# Топ потребителей
kubectl get pods -A -o json | jq -r '
  .items[] |
  select(.status.phase=="Running") |
  "\(.metadata.namespace)/\(.metadata.name): \(.spec.containers[0].resources.requests.cpu // "0")"
' | sort -t: -k2 -h | tail -20
```

**Результат:**
- CPU Requests 97-100%
- kyverno: 400m, projectcontour: 400m, keda: 300m...
- Итого: ~3000m = 100% capacity 3 нод

---

## Capacity ноды

| Уровень | Что это |
|---------|---------|
| Capacity | Всего ресурсов |
| Allocatable | Capacity минус системные резервы |
| Allocated | Requests размещённых подов |

`сумма requests всех подов ≤ allocatable ноды`

---

## Единицы измерения

| Ресурс | Единица | Пример |
|--------|---------|--------|
| CPU | millicores | 100m = 0.1 CPU |
| CPU | cores | 1 = 100% одного ядра |
| Memory | bytes | 256Mi, 1Gi |

---

## Throttling

Принудительное ограничение CPU при превышении `limits.cpu`.

Linux CFS настраивает cgroup:
- `cpu.shares` — пропорция (из requests)
- `cpu.cfs_quota_us` — потолок (из limits)

Симптом: рост latency при нормальной нагрузке.

---

## Проблема с Kyverno

При удалении Kyverno Helm не удалил `ValidatingWebhookConfiguration` и `MutatingWebhookConfiguration`, что заблокировало кластер.

**Решение:** сначала удалять хуки, потом сносить оператор.
