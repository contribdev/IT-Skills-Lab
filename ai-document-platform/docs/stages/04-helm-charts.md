# Этап 4. Helm-чарты

## Сетевое взаимодействие

### Путь запроса API

```
API pod (10.42.1.5)
  │
  │ 1. getaddrinfo("postgres-rw.database.svc.cluster.local")
  │    → /etc/resolv.conf → nameserver 10.43.0.10 (CoreDNS)
  │
  ▼
CoreDNS (10.43.0.10)
  │ 2. Резолвит Service → возвращает ClusterIP
  │
  ▼
kube-proxy (iptables/IPVS)
  │ 3. ClusterIP → pod IP (DNAT)
  │
  ▼
PostgreSQL pod
```

### Передача credentials

| Слой | Где | Что происходит |
|------|-----|----------------|
| 1 | `values.yaml` | Шаблон: `secrets.DATABASE_URL: ""` |
| 2 | `helm install --set` | Передача значений |
| 3 | `secret.yaml` | Рендер Secret в кластере (base64) |
| 4 | Deployment `envFrom` | Монтирование в под |
| 5 | `pydantic-settings` | Чтение env в приложении |

---

## Scheduling: размещение подов

### nodeSelector

Жёсткий фильтр по меткам ноды. Pod запустится только на нодах с указанными метками.

### tolerations

Для работы с taints. Ноды могут иметь taints — «не ставь сюда поды без разрешения».

```yaml
tolerations:
  - key: "gpu"
    operator: "Equal"
    value: "true"
    effect: "NoSchedule"
```

### affinity

- **nodeAffinity** — на какие ноды ставить (жёсткий/мягкий)
- **podAffinity** — ставить рядом с другими подами
- **podAntiAffinity** — не ставить рядом (replicas на разных нодах)

---

## ServiceAccount

Идентификация пода внутри кластера:
- **Объект** — ServiceAccount в namespace
- **Токен** — JWT в `/var/run/secrets/kubernetes.io/serviceaccount/token`
- **RBAC** — правила доступа

**Зачем своя SA:**
- Принцип наименьших привилегий
- Изоляция между приложениями
- IRSA/Workload Identity — привязка к cloud IAM
- Image pull secrets

---

## Доступ к Ollama через ExternalName

```yaml
kind: Service
spec:
  type: ExternalName
  externalName: ollama.local
```

CoreDNS override для резолвинга `ollama.local` в Windows IP:

```yaml
data:
  ollama.server: |
    ollama.local:53 {
      hosts {
        172.21.128.1 ollama.local
        fallthrough
      }
    }
```

---

## Проблемы

**Ошибка:** После копирования чарта забыл обновить имя образа — был передан образ API вместо OCR worker.

**Решение:** `helm upgrade` с правильными параметрами.
