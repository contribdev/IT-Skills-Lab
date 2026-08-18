# Неделя 6 — Аутентификация, RBAC, безопасность подов, секреты

**Цель недели:** понимать, кто и как получает доступ к API кластера, уметь выдавать минимальные права и убрать секреты из git.
**Время:** 10.5 часов (3.5 ч теории, 7 ч практики).

Это неделя, после которой ты перестаёшь выдавать всем `cluster-admin`. На собеседованиях RBAC спрашивают почти всегда, потому что он показывает, работал ли человек в многопользовательском кластере или только в своей песочнице.

---

## 📖 Теория

### 1. Три этапа доступа к API

Любой запрос к API server проходит: **аутентификация → авторизация → admission**.

**Аутентификация — «кто ты».** Kubernetes умеет несколько способов:

| Способ | Где применяется |
|---|---|
| Клиентские сертификаты X.509 | Администраторы, компоненты кластера |
| ServiceAccount-токены (JWT) | Приложения внутри кластера |
| OIDC | Корпоративные пользователи (Keycloak, Google, AD) |
| Webhook / прокси | Экзотика, облачные IAM |

⚠️ **Ключевой факт для собеседования:** в Kubernetes **нет объекта User**. Пользователи не хранятся в кластере вообще. Кластер лишь доверяет внешнему источнику: если сертификат подписан его CA, то `CN=` из сертификата становится именем пользователя, а `O=` — группами. Создать пользователя = выпустить сертификат. Удалить = отозвать (а поскольку CRL в Kubernetes толком не поддерживается — в реальности перевыпустить CA или использовать OIDC).

ServiceAccount, наоборот, — **настоящий объект** в кластере, namespaced.

**Авторизация — «что тебе можно».** Основной режим — RBAC. Есть ещё ABAC (устарел), Node (для kubelet), Webhook.

**Admission — «а можно ли это в принципе».** Разбирали на неделе 2; сюда относятся ResourceQuota, PodSecurity и твои будущие политики Kyverno.

### 2. RBAC: четыре объекта

| Объект | Область | Что описывает |
|---|---|---|
| **Role** | namespace | набор прав |
| **ClusterRole** | кластер | набор прав (в т.ч. на cluster-scoped ресурсы) |
| **RoleBinding** | namespace | кому дать права |
| **ClusterRoleBinding** | кластер | кому дать права везде |

Правило состоит из трёх частей:

```yaml
rules:
  - apiGroups: ["apps"]           # "" = core group (pods, services, secrets)
    resources: ["deployments"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
```

**Важные комбинации, которые нужно знать:**

- `RoleBinding` может ссылаться на **ClusterRole** — и тогда права действуют только в namespace этого RoleBinding. Это основной приём: одна ClusterRole `view`, много RoleBinding'ов в разных namespace.
- `ClusterRoleBinding` + ClusterRole = права во всём кластере.
- Обратное невозможно: ClusterRoleBinding не может ссылаться на Role.

**RBAC только аддитивен.** Запрещающих правил не существует, всё запрещено по умолчанию. Убрать право = убрать привязку.

**Встроенные ClusterRole:** `cluster-admin` (всё), `admin` (всё в namespace), `edit` (изменять, но не трогать RBAC), `view` (только чтение, **кроме секретов**).

⚠️ Тонкости, на которых ловят:
- Права на `pods/exec` и `pods/log` — это **отдельные подресурсы**. Дав `get pods`, ты не дал `kubectl exec`. А дав `pods/exec` — фактически дал доступ внутрь контейнера, что почти равно правам приложения.
- Права на чтение Secret в namespace ≈ права всех приложений этого namespace.
- Право `create pod` позволяет запустить под с `hostPath: /` и примонтировать корень ноды. То есть это фактически права root на ноде, если нет ограничивающих политик. **Отличный ответ на вопрос «почему PodSecurity важен».**
- Право `escalate`/`bind` позволяет выдать себе больше прав, чем есть. Обычно закрыто.

Проверка прав — важнейшая команда:

```bash
kubectl auth can-i create deployments -n app
kubectl auth can-i --list -n app
kubectl auth can-i get secrets --as=system:serviceaccount:app:myservice -n app
```

### 3. ServiceAccount и токены

Каждый под получает ServiceAccount (если не указан — `default` из своего namespace) и его токен, смонтированный в `/var/run/secrets/kubernetes.io/serviceaccount/`.

С Kubernetes 1.24 токены **больше не создаются автоматически** как долгоживущие Secret'ы. Вместо этого используется **projected token**: короткоживущий (по умолчанию 1 час), автоматически ротируемый, привязанный к конкретному поду и аудитории. Это важное изменение, о нём стоит знать.

⚠️ Если приложению API-доступ не нужен (а он не нужен 95% приложений) — токен монтировать не надо:

```yaml
spec:
  automountServiceAccountToken: false
```

Это одна из самых дешёвых мер безопасности: без токена скомпрометированный под не сможет обратиться к API.

### 4. SecurityContext

Настройки безопасности на уровне пода и контейнера.

```yaml
spec:
  securityContext:            # уровень пода
    runAsNonRoot: true
    runAsUser: 10001
    runAsGroup: 10001
    fsGroup: 10001            # владелец смонтированных томов
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: app
      securityContext:        # уровень контейнера, перекрывает поды
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop: ["ALL"]
```

Что делает каждое:

- **`runAsNonRoot: true`** — kubelet откажется запускать контейнер, если он работает от UID 0. ⚠️ Проверяется по **числовому** UID; если в образе `USER appuser` без числа — kubelet не сможет проверить и под упадёт с ошибкой. Отсюда правило недели 1 про числовой UID.
- **`readOnlyRootFilesystem: true`** — корень образа read-only. Приложению, которому нужны временные файлы, добавляй `emptyDir` на `/tmp`. Очень сильная мера: заливка вредоноса в контейнер становится невозможной.
- **`allowPrivilegeEscalation: false`** — запрет получения дополнительных привилегий через setuid-бинарники.
- **`capabilities.drop: ["ALL"]`** — снять все Linux capabilities. Если нужен привилегированный порт < 1024, добавь `NET_BIND_SERVICE` (а лучше слушай порт 8080 и маппь через Service).
- **`fsGroup`** — при монтировании тома kubelet рекурсивно меняет группу-владельца. Решает классическую проблему «non-root не может писать в PVC».

### 5. Pod Security Admission

Пришёл на смену PodSecurityPolicy (удалён в 1.25). Работает **на уровне namespace** через лейблы, три уровня:

| Уровень | Что даёт |
|---|---|
| `privileged` | всё разрешено |
| `baseline` | минимальные ограничения, блокирует явно опасное (hostPath, hostNetwork, privileged) |
| `restricted` | жёсткий: non-root, drop ALL caps, seccomp, no privilege escalation |

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: app
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: latest
    pod-security.kubernetes.io/warn: restricted
    pod-security.kubernetes.io/audit: restricted
```

Три режима: `enforce` (блокировать), `warn` (предупреждать в ответе API), `audit` (писать в аудит-лог). Правильная стратегия внедрения: сначала `warn` + `audit`, собрать список нарушений, починить, потом `enforce`.

⚠️ Ограничение PSA: он **не умеет исключения**. «Restricted, но вот этому DaemonSet'у можно hostPath» — не выражается. Отсюда переход на Kyverno/Gatekeeper (неделя 17), где политики гибкие.

### 6. Секреты: почему всё, что ты делал до сих пор, не годится для прода

Проблемы нативных Secret:
1. В etcd лежат в открытом виде (если не включён encryption at rest).
2. В git класть нельзя вообще.
3. Ротация — только вручную.
4. Аудит доступа отсутствует.

Три подхода к решению:

**A. Encryption at rest** — шифрование в etcd на стороне API server (`EncryptionConfiguration`). Обязательно, но недостаточно: защищает только украденный бэкап etcd.

**B. SOPS (+ age/PGP/KMS)** — шифруем **значения** в YAML, файл целиком остаётся читаемым и diff'ается в git. Идеально для GitOps. Минус: ключ расшифровки должен быть в кластере.

**C. External Secrets Operator + внешнее хранилище (Vault и т.п.)** — в git лежит только *ссылка* на секрет (`ExternalSecret`), оператор подтягивает значение и создаёт нативный Secret. Плюсы: ротация, аудит, единый источник правды. Это индустриальный стандарт, и именно его ты будешь использовать на неделе 13.

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata: { name: app-secrets, namespace: app }
spec:
  refreshInterval: 1h
  secretStoreRef: { name: vault-backend, kind: ClusterSecretStore }
  target: { name: app-secrets }
  data:
    - secretKey: db_password
      remoteRef: { key: app/prod, property: db_password }
```

---

## 🔧 Задание 1: создаём пользователя с нуля (2 ч)

Классическое упражнение, встречается на CKA.

```bash
# 1. Ключ и CSR
openssl genrsa -out dev-user.key 2048
openssl req -new -key dev-user.key -out dev-user.csr \
  -subj "/CN=dev-user/O=developers"

# 2. Отправляем CSR в кластер
cat <<EOF | kubectl apply -f -
apiVersion: certificates.k8s.io/v1
kind: CertificateSigningRequest
metadata: { name: dev-user }
spec:
  request: $(cat dev-user.csr | base64 | tr -d '\n')
  signerName: kubernetes.io/kube-apiserver-client
  usages: ["client auth"]
  expirationSeconds: 8640000
EOF

# 3. Подписываем
kubectl certificate approve dev-user
kubectl get csr dev-user -o jsonpath='{.status.certificate}' | base64 -d > dev-user.crt
```

Собери kubeconfig:

```bash
kubectl config set-credentials dev-user \
  --client-key=dev-user.key --client-certificate=dev-user.crt --embed-certs=true
kubectl config set-context dev --cluster=default --user=dev-user --namespace=app
kubectl config use-context dev
kubectl get pods            # Forbidden — прав ещё нет
```

Теперь выдай права:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata: { name: pod-reader, namespace: app }
rules:
  - apiGroups: [""]
    resources: ["pods", "pods/log"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata: { name: dev-pod-reader, namespace: app }
subjects:
  - kind: User
    name: dev-user
    apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: Role
  name: pod-reader
  apiGroup: rbac.authorization.k8s.io
```

Проверь границы прав опытом:
```bash
kubectl auth can-i --list -n app
kubectl get pods -n app          # ок
kubectl get pods -n default      # Forbidden
kubectl delete pod X -n app      # Forbidden
kubectl exec -it X -- sh         # Forbidden — почему? Добавь pods/exec и повтори
kubectl logs X                   # проверь с pods/log и без
```

Отдельно: выдай права через **группу** `developers` (из `O=` в сертификате) вместо конкретного пользователя. Это то, как делают в реальности.

---

## 🔧 Задание 2: ServiceAccount для приложения (1.5 ч)

Напиши маленький Python-сервис, который читает ConfigMap через Kubernetes API (библиотека `kubernetes`, `config.load_incluster_config()`).

1. Запусти его с `default` ServiceAccount → получи 403. Прочитай текст ошибки внимательно, там указаны и субъект, и требуемое право.
2. Создай отдельный ServiceAccount, Role на `get configmaps` в своём namespace, RoleBinding. Заработало.
3. Посмотри токен изнутри пода:
   ```bash
   kubectl exec -it <pod> -- cat /var/run/secrets/kubernetes.io/serviceaccount/token
   ```
   Раздекодируй JWT (jwt.io или `jq`) — посмотри `exp`, `aud`, привязку к поду.
4. Поставь `automountServiceAccountToken: false` на своём основном приложении (которому API не нужен) и убедись, что каталог с токеном исчез.
5. Проверь права от имени ServiceAccount:
   ```bash
   kubectl auth can-i get configmaps --as=system:serviceaccount:app:myservice -n app
   ```

---

## 🔧 Задание 3: SecurityContext и PSA (2 ч)

1. Включи на namespace `app` режим `warn: restricted` (не enforce!). Примени свои существующие манифесты — получи список предупреждений. Выпиши их.

2. Чини по одному:
   - `runAsNonRoot: true` + числовой UID
   - `allowPrivilegeEscalation: false`
   - `capabilities: drop: [ALL]`
   - `seccompProfile: RuntimeDefault`
   - `readOnlyRootFilesystem: true` + emptyDir на `/tmp` и на всё, куда приложение пишет

3. Переключи на `enforce: restricted`. Убедись, что всё работает.

4. Попробуй создать заведомо опасный под и получи отказ:
   ```yaml
   spec:
     hostNetwork: true
     containers:
       - name: bad
         image: busybox
         securityContext: { privileged: true }
         volumeMounts: [{ name: root, mountPath: /host }]
     volumes:
       - name: root
         hostPath: { path: / }
   ```

5. **Демонстрация опасности:** в namespace **без** PSA запусти этот под и убедись, что из него виден и изменяем корень файловой системы ноды. Это то самое «право create pod ≈ root на ноде». Обязательно проделай — понимание останется навсегда.

---

## 🔧 Задание 4: аудит безопасности кластера (1 ч)

```bash
# kube-bench — проверка по CIS Benchmark
kubectl apply -f https://raw.githubusercontent.com/aquasecurity/kube-bench/main/job.yaml
kubectl logs job/kube-bench

# kubescape или kube-score — проверка манифестов
kube-score score 02-k8s-manifests/*.yaml
```

Задача: выписать топ-10 замечаний, исправить пять и объяснить в журнале, почему остальные пять не критичны для лабы. Умение отличать реальный риск от шума линтера — тоже навык.

---

## 🔧 Задание 5: убираем секреты из git (2 ч)

**Вариант A — SOPS + age (быстрый, для GitOps):**

```bash
age-keygen -o key.txt              # ключ, в git НЕ кладём
sops --encrypt --age <public-key> secret.yaml > secret.enc.yaml
git add secret.enc.yaml
sops --decrypt secret.enc.yaml | kubectl apply -f -
```

Открой `secret.enc.yaml` и обрати внимание: ключи читаемы, значения зашифрованы. Именно поэтому SOPS удобен для code review.

**Вариант B — Vault + External Secrets Operator (продовый):**

```bash
helm install vault hashicorp/vault -n vault --create-namespace \
  --set "server.dev.enabled=true"

helm install external-secrets external-secrets/external-secrets \
  -n external-secrets --create-namespace
```

1. Положи секреты в Vault (KV v2).
2. Настрой аутентификацию Kubernetes в Vault: Vault доверяет ServiceAccount-токенам кластера.
3. Создай `ClusterSecretStore` и `ExternalSecret`.
4. Убедись, что нативный Secret создался автоматически.
5. **Проверь ротацию:** измени значение в Vault, дождись `refreshInterval` — Secret обновится сам.

Сделай оба варианта. На неделе 13 ты будешь выбирать между ними осознанно, и хорошо, если выбор будет основан на опыте, а не на статье в интернете.

---

## 💥 Ломаем специально

1. Дай пользователю `get secrets` в namespace и прочитай его же токены. Осознай, что это фактически права всех приложений namespace.
2. Дай `pods/exec` без `get pods` — сможет ли пользователь зайти в под, если он знает его имя? (Да.) Сделай вывод о гранулярности прав.
3. Создай RoleBinding, ссылающийся на ClusterRole `admin`, в одном namespace. Проверь, что права ограничены этим namespace. Затем создай ClusterRoleBinding на ту же роль и сравни.
4. Поставь `readOnlyRootFilesystem: true` без emptyDir на `/tmp` — поймай падение приложения. Прочитай ошибку и почини.
5. Укажи `runAsUser: 10001` для образа, где файлы принадлежат root → приложение не запишет ничего. Почини через `fsGroup` или `--chown` в Dockerfile.
6. Удали RoleBinding у работающего приложения — что произойдёт с уже установленными соединениями и с новыми запросами к API?

---

## ❓ Самопроверка

1. Три этапа обработки запроса к API server.
2. Почему в Kubernetes нет объекта User? Как тогда «создать пользователя»?
3. Может ли RoleBinding ссылаться на ClusterRole? А ClusterRoleBinding на Role? Что это даёт?
4. Почему право `create pod` фактически равно правам root на ноде? Как это закрыть?
5. Чем `pods/exec` отличается от `pods` в правилах RBAC?
6. Что изменилось с ServiceAccount-токенами в Kubernetes 1.24?
7. Зачем `automountServiceAccountToken: false`?
8. `runAsNonRoot: true` — почему требует числового UID в образе?
9. Три уровня Pod Security Standards и три режима применения. Как безопасно внедрять?
10. Главное ограничение PSA по сравнению с Kyverno?
11. Base64 в Secret — это шифрование? Что нужно, чтобы секреты в etcd были зашифрованы?
12. SOPS vs External Secrets — когда что выбрать?

---

## 🔗 Ссылки

| Ресурс | Зачем |
|---|---|
| [RBAC](https://kubernetes.io/docs/reference/access-authn-authz/rbac/) | Главный документ недели |
| [Authenticating](https://kubernetes.io/docs/reference/access-authn-authz/authentication/) | Способы аутентификации |
| [Certificate Signing Requests](https://kubernetes.io/docs/reference/access-authn-authz/certificate-signing-requests/) | Задание 1 |
| [ServiceAccounts](https://kubernetes.io/docs/concepts/security/service-accounts/) | Токены и projected volumes |
| [Security Context](https://kubernetes.io/docs/tasks/configure-pod-container/security-context/) | |
| [Pod Security Standards](https://kubernetes.io/docs/concepts/security/pod-security-standards/) | Таблица требований по уровням |
| [Encrypting Secret Data at Rest](https://kubernetes.io/docs/tasks/administer-cluster/encrypt-data/) | |
| [kube-bench](https://github.com/aquasecurity/kube-bench) | CIS-аудит |
| [SOPS](https://github.com/getsops/sops) | Секреты в git |
| [External Secrets Operator](https://external-secrets.io/) | Продовый подход |
| [RBAC.dev](https://rbac.dev/) | Подборка инструментов и статей по RBAC |

---

## ✅ Чек-лист недели

- [ ] Создал пользователя через клиентский сертификат и собрал ему kubeconfig
- [ ] Выдал права через Role и через группу из `O=`, проверил границы через `auth can-i`
- [ ] Разобрался с `pods/exec` и `pods/log` как отдельными подресурсами
- [ ] Приложение с собственным ServiceAccount и минимальными правами работает
- [ ] `automountServiceAccountToken: false` там, где API не нужен
- [ ] Namespace в режиме `enforce: restricted`, все манифесты соответствуют
- [ ] Проделал демонстрацию: под с hostPath даёт доступ к корню ноды
- [ ] kube-bench прогнан, топ-5 замечаний исправлено
- [ ] Секреты убраны из git: сделаны оба варианта — SOPS и Vault + ESO
- [ ] Проверил автоматическую ротацию секрета через ESO
- [ ] Все 6 экспериментов «Ломаем специально» проделаны
- [ ] `notes/week-06.md` заполнен
