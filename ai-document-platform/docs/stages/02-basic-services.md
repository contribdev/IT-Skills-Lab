# Этап 2. Базовые сервисы

Развёртывание инфраструктурных компонентов в кластере через Terraform.

## Компоненты

| Сервис | Namespace | Helm Chart |
|--------|-----------|------------|
| MinIO | storage | bitnami/minio |
| PostgreSQL | database | CloudNativePG operator |
| RabbitMQ | queue | bitnami/rabbitmq |

## Развёртывание

```bash
cd terraform/environments/dev
terraform init
terraform apply \
  -var "minio_root_password=XXX" \
  -var "db_password=XXX" \
  -var "rabbitmq_password=XXX"
```

## Проверка

```bash
# PostgreSQL
NODE_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')
PGPASSWORD=admin123 psql -h $NODE_IP -p 30432 -U app -d documents -c 'SELECT 1;'

# MinIO (через port-forward)
kubectl port-forward svc/minio -n storage 9000:9000
curl -s http://127.0.0.1:9000/minio/health/live

# RabbitMQ (через port-forward)
kubectl port-forward svc/rabbitmq -n queue 15672:15672
curl -s -u app:admin123 http://localhost:15672/api/overview
```

## Результат

- PostgreSQL: 2 instance (primary + replica) с автоматическим failover
- MinIO: S3-совместимое хранилище с бакетом `documents`
- RabbitMQ: очереди `ocr.queue` и `llm.queue` готовы к работе
