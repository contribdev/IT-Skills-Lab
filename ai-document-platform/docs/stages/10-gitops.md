# Этап 10. CI/CD и GitOps

## Концепция GitOps

**GitOps** — Git как единственный источник правды. Любое изменение инфраструктуры через Git, не `kubectl edit`.

| Модель | Схема | Описание |
|--------|-------|----------|
| **Push** (было) | Ты → `helm upgrade` → Кластер | Человек инициирует |
| **Pull** (стало) | Git ← ArgoCD → Кластер | Агент сам подтягивает |

## Четыре принципа OpenGitOps

1. **Декларативность** — вся система описана декларативно
2. **Версионирование** — описание в Git, история полная
3. **Автоматическое применение** — агент подтягивает сам
4. **Непрерывная сверка** — сравнивает и исправляет drift

---

## CI/CD Pipeline

```
git push (apps/ или charts/)
        │
        ▼
GitHub Actions (build-and-push-all)
        │  • build 3 образов
        │  • push в GHCR
        │  • bump tags в charts/*/values.yaml
        ▼
git commit + push [skip ci]
        │
        ▼
ArgoCD (poll каждые 3 мин или webhook)
        │
        ▼
Helm diff → apply в кластер
        │
        ▼
Новые поды с новыми образами
```

---

## Архитектура ArgoCD

| Компонент | Ответственность |
|-----------|-----------------|
| **api-server** | gRPC/REST API, веб-UI, RBAC |
| **repo-server** | Клонирует Git, рендерит манифесты |
| **application-controller** | Сравнивает и применяет изменения |
| **redis** | Кеш |

## Ключевые ресурсы

| Ресурс | Назначение |
|--------|-----------|
| **Application** | Что деплоить и куда |
| **ApplicationSet** | Генератор Applications (DRY) |
| **AppProject** | Группировка + RBAC |

---

## Sync Waves

```yaml
metadata:
  annotations:
    argocd.argoproj.io/sync-wave: "-1"  # первым
    argocd.argoproj.io/sync-wave: "0"   # потом
    argocd.argoproj.io/sync-wave: "1"   # последним
```

Порядок: Namespace → Operators/CRDs → Applications

---

## Multi-source Applications

Чарт из внешнего Helm repo, values из своего Git:

```yaml
sources:
  - repoURL: https://charts.jetstack.io
    chart: cert-manager
    helm:
      valueFiles:
        - $values/gitops/platform/values/cert-manager.yaml
  - repoURL: https://github.com/my/repo
    ref: values    # имя для ссылки $values
```

---

## syncOptions

```yaml
syncPolicy:
  automated:
    prune: true           # удалять ресурсы, которых нет в Git
    selfHeal: true        # откатывать drift
  syncOptions:
    - CreateNamespace=true
    - ServerSideApply=true  # для больших CRD
```

---

## Структура GitOps в проекте

```
gitops/
├── projects/
│   ├── platform/
│   │   ├── project.yaml          # AppProject
│   │   ├── applicationset.yaml   # cert-manager, keda, contour...
│   │   └── values/               # Helm values
│   └── apps/
│       └── applicationset.yaml   # api, ocr-worker, llm-worker
```

**Git Directory Generator** — автоматически создаёт Application для каждой папки в `charts/*`.

---

## Результат

![Project Structure](../src/img/project_structure.png)

![KEDA в ArgoCD](../src/img/llm_keda_scaling.png)

---

## Проблемы

**Проблема:** `buildx failed: permission_denied: read_package`

**Причина:** Недостаточно прав для push в GHCR

**Решение:** Проверить `permissions` в workflow и настройки пакета в GitHub
