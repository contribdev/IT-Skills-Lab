# Этап 1. Terraform: инфраструктура

## Модуль STORAGE

Модуль создаёт пространство имен, secret и устанавливает MinIO.

**Реализовано:**
- namespace `storage`
- Secret `minio-credentials` (ключи `access-key` / `secret-key`)
- Helm release MinIO (Bitnami chart)
- outputs в модуле и в `environments/dev`

### Проблема: образы MinIO недоступны

Официальные образы `minio/minio` (Docker Hub) удалены из публичного доступа. Community-сборки (`netvark/minio`) несовместимы с официальным Helm-чартом.

**Решение:** Bitnami MinIO chart с образами из `bitnamilegacy`:

```hcl
set { name = "image.repository"; value = "bitnamilegacy/minio" }
set { name = "image.tag";        value = "2025.7.23-debian-12-r5" }
```

### Проверка через rclone

```bash
rclone config create local s3 \
  provider=Minio \
  endpoint=http://localhost:9000 \
  access_key_id=admin \
  secret_access_key=ПАРОЛЬ
```

| Команда | Описание |
|---------|----------|
| `rclone lsd local:` | Список бакетов |
| `rclone ls local:documents` | Список файлов в бакете |
| `rclone copy file.txt local:documents/` | Загрузить файл |
| `rclone mkdir local:newbucket` | Создать бакет |

---

## Модуль DATABASE

Для PostgreSQL используется **CloudNativePG (CNPG)** — самый популярный PostgreSQL-operator.

| Функция | Что делает |
|---------|------------|
| Репликация | Streaming replication между instances |
| Failover | При падении primary повышает replica |
| Service | Создаёт `-rw`, `-ro`, `-r` сервисы |
| Backup | Автоматические бэкапы в S3 |
| Мониторинг | Экспортирует метрики для Prometheus |

**Реализовано:**
- namespace `cnpg-system` (для operator)
- namespace `database` (для PostgreSQL)
- Helm release CNPG operator
- Secret `postgres-app-credentials`
- CR `Cluster` через `kubectl_manifest`

### Проблемы

1. **CRD не установлен:**
   ```
   API did not recognize GroupVersionKind from manifest
   ```
   Решение: разделить apply — сначала CRD, потом CR.

2. **kubernetes_manifest не работает с операторами:** CNPG дописывает дефолтные параметры PostgreSQL, Terraform видит drift.

3. **Неверный провайдер:** Terraform искал `hashicorp/kubectl`, но нужен `gavinbunney/kubectl`.

### Структура CNPG Cluster

```
CNPG Cluster (один YAML-объект)
│
├── Pod postgres-1 (primary)
│   └── PostgreSQL Cluster
│       ├── /var/lib/postgresql/data (PVC 10Gi)
│       ├── база: documents
│       └── роли: postgres, app
│
└── Pod postgres-2 (replica)
    └── PostgreSQL Cluster (streaming replication)
```

---

## Модуль QUEUE

**Реализовано:**
- namespace `queue`
- Secret `rabbitmq-credentials` с `amqp-url` и `management-url`
- Helm release RabbitMQ (Bitnami chart) с Management plugin
- ConfigMap со скриптом создания очередей
- Kubernetes Job — создаёт очереди через Management API

### Схема

```
Terraform
  │
  ├── kubernetes_namespace "queue"
  ├── kubernetes_secret "credentials"
  ├── helm_release "rabbitmq"
  └── kubernetes_job "create_queues"
        │
        └── PUT /api/queues/%2F/ocr.queue
            PUT /api/queues/%2F/llm.queue
```

> **Management plugin** — расширение RabbitMQ, добавляющее HTTP API и веб-интерфейс.
