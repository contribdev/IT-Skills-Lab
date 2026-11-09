# IT-Skills-Lab
Репозиторий, в рамках которого я хочу пройти повышение своих компетенций в DEVOPS. 

# Краткое описание проекта 

Платформа принимает PDF/сканы → OCR (Tesseract) → структурирование через локальную LLM (Ollama, llama3.1:8b) → отдаёт JSON. Асинхронный конвейер на RabbitMQ, артефакты в S3 (MinIO), статусы в PostgreSQL.

Что сделано:

Инфраструктура как код на Terraform: модули storage, database, queue для MinIO, PostgreSQL (CloudNativePG) и RabbitMQ.

Helm-чарты для микросервисов api (FastAPI), ocr-worker, llm-worker; сеть, scheduling, ServiceAccount.

GitOps: ArgoCD + ApplicationSet — автоматическая синхронизация состояния кластера из Git.

Ingress и TLS: Contour (Envoy) + cert-manager + HTTPProxy.

Секреты и политики: Vault + External Secrets Operator, Kyverno, Reloader.

Observability: Prometheus + Grafana, дашборды и SLI/SLO.

Автоскейлинг: KEDA по глубине очередей RabbitMQ.

CI/CD: сборка образов и доставка через GitOps.

Стек: Kubernetes, Terraform, Helm, ArgoCD, KEDA, Vault, ESO, Kyverno, Contour, cert-manager, Prometheus, Grafana, PostgreSQL (CloudNativePG), RabbitMQ, MinIO (S3), Ollama, FastAPI, Tesseract, Docker.

