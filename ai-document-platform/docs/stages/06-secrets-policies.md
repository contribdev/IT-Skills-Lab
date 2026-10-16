# Этап 6. Секреты и политики

**Цель:** секреты не в Helm values и git, все ресурсы подчиняются политикам.

## External Secrets Operator

**ESO** — оператор, который читает секреты из внешнего хранилища (Vault, AWS SM, GCP SM) и создаёт K8s Secrets.

| CRD | Назначение |
|-----|------------|
| `SecretStore` | Где брать секреты (в рамках namespace) |
| `ClusterSecretStore` | То же, на весь кластер |
| `ExternalSecret` | Какой секрет синхронизировать в K8s Secret |

### Схема обновления секретов

```
Vault (изменение пароля)
    ↓
ESO (refreshInterval: 1h) обновляет K8s Secret
    ↓
Secret меняется
    ↓
Reloader видит изменение
    ↓
kubectl rollout restart deployment/...
    ↓
Новые поды с новым env
```

---

## Vault

### Dev режим

```bash
helm install vault hashicorp/vault \
    --namespace vault \
    --set "server.dev.enabled=true" \
    --set "server.dev.devRootToken=root-token"
```

### Standalone режим

1. **Инициализация:**
   ```bash
   vault operator init -key-shares=5 -key-threshold=3
   ```

2. **Распечатывание (unseal):** Vault при старте всегда запечатан. Нужно 3 из 5 ключей для расшифровки.

---

## Stakater Reloader

Оператор, который следит за Secrets и ConfigMaps. При изменении — перезапускает Deployments.

```bash
helm install reloader stakater/reloader \
    --namespace reloader \
    --set reloader.watchGlobally=true
```

---

## Kyverno — политики кластера

Admission controller, который проверяет/мутирует ресурсы до сохранения в etcd.

```
kubectl apply → API-сервер → admission webhook → разрешить/запретить → etcd
```

### Режимы работы

| Режим | Поведение | Когда использовать |
|-------|-----------|-------------------|
| Audit | Не блокирует, пишет в PolicyReport | Первое время — понять масштаб |
| Enforce | Блокирует создание | Когда уверен, что не сломается |

### Компоненты

| Компонент | Назначение |
|-----------|------------|
| admission-controller | Webhook для новых ресурсов |
| background-controller | Сканирует существующие ресурсы |
| reports-controller | Собирает PolicyReport |
| cleanup-controller | Удаляет ресурсы по TTL |

### Реализованная политика

Запрет `securityContext.privileged: true` — даёт контейнеру root-доступ к хосту.

**Результат нарушения:**
```yaml
results:
- message: 'validation error: Privileged mode is disallowed...'
  policy: disallow-privileged-containers
  result: fail
```

---

## Проблемы

**Нюанс Kyverno:** если упадёт при `failurePolicy: Fail`, API-сервер не сможет валидировать ресурсы → создание/изменение сломается.
