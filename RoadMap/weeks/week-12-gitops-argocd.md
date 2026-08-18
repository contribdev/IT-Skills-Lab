# Неделя 12 — GitOps: ArgoCD

**Цель недели:** перейти от push-модели доставки (которая у тебя сейчас в Jenkins) к декларативной pull-модели.
**Время:** 11 часов (3 ч теории, 8 ч практики).

Эта неделя — самая прямая конвертация твоего текущего опыта. Ты уже занимаешься доставкой дистрибутивов и знаешь все её боли: рассинхрон окружений, «а что сейчас развёрнуто в проде», ручные хотфиксы, которые теряются при следующем релизе. GitOps — это индустриальный ответ на эти боли, и рассказывать про него ты сможешь с позиции человека, который знает проблему изнутри.

---

## 📖 Теория

### 1. Push vs Pull

**Push-модель** (то, что у тебя сейчас):

```
git push → CI собирает → CI имеет доступ в кластер → kubectl apply / helm upgrade
```

Проблемы:
- **CI нужны права в кластере.** Credentials кластера живут в CI-системе. Скомпрометировали Jenkins — скомпрометировали прод.
- **Нет источника правды.** Что развёрнуто прямо сейчас? Нужно идти в кластер и смотреть.
- **Дрейф не обнаруживается.** Кто-то поправил руками в 3 часа ночи — об этом никто не узнает, пока не сломается.
- **Откат — это отдельный процесс**, который может быть не отработан.
- **Каждый кластер — отдельная настройка CI.** Десять кластеров = десять наборов credentials.

**Pull-модель (GitOps):**

```
git push → агент ВНУТРИ кластера видит изменение → применяет сам
```

Четыре принципа ([OpenGitOps](https://opengitops.dev/)):

1. **Декларативность** — вся система описана декларативно.
2. **Версионирование и неизменяемость** — описание хранится в git, история полная.
3. **Автоматическое применение** — агент подтягивает изменения сам.
4. **Непрерывная сверка** — агент постоянно сравнивает фактическое состояние с желаемым и исправляет расхождения.

Что это даёт практически:
- Credentials кластера **не покидают кластер**.
- `git log` = журнал изменений прода. Аудит бесплатно.
- Откат = `git revert`.
- Ручное изменение автоматически откатывается (self-heal).
- Новый кластер поднимается тем же репозиторием.

⚠️ Что GitOps **не** решает: секреты (нужен отдельный механизм — неделя 6 и 13), обновление версий образов (нужен отдельный процесс), миграции данных.

### 2. Архитектура ArgoCD

| Компонент | Ответственность |
|---|---|
| **api-server** | gRPC/REST API, веб-UI, аутентификация, RBAC |
| **repo-server** | клонирует git, рендерит манифесты (helm template, kustomize build), кеширует результат |
| **application-controller** | сравнивает желаемое (из repo-server) с фактическим (из кластера), применяет изменения |
| **redis** | кеш |
| **dex** (опционально) | интеграция с SSO |

**Как работает цикл сверки:** контроллер периодически (по умолчанию раз в 3 минуты) опрашивает git и сравнивает. Плюс webhook от git-провайдера для мгновенной реакции. Плюс watch за ресурсами кластера для обнаружения дрейфа.

### 3. Application

Основной объект — CRD `Application`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: myservice-prod
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io    # удалять ресурсы при удалении Application
spec:
  project: default
  source:
    repoURL: https://github.com/you/gitops-lab
    targetRevision: main
    path: apps/myservice
    helm:
      valueFiles:
        - values-prod.yaml
      parameters:
        - name: image.tag
          value: "1.4.2"
  destination:
    server: https://kubernetes.default.svc
    namespace: prod
  syncPolicy:
    automated:
      prune: true          # удалять ресурсы, исчезнувшие из git
      selfHeal: true       # откатывать ручные изменения
      allowEmpty: false
    syncOptions:
      - CreateNamespace=true
      - PruneLast=true
      - ApplyOutOfSyncOnly=true
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
```

⚠️ **`prune: true`** — обоюдоострый. Он даёт настоящую декларативность (удалил из git — удалилось из кластера), но случайное удаление файла удалит ресурс из прода. Стандартная практика: `prune: true` + защита критичных ресурсов аннотацией `argocd.argoproj.io/sync-options: Prune=false`.

⚠️ **`selfHeal: true`** — блокирует ручные изменения. Это правильно, но означает: `kubectl scale` в проде больше не работает, изменения только через git. Команду нужно к этому подготовить.

### 4. Health и Sync статусы

Два независимых измерения — важно не путать:

**Sync status:** `Synced` / `OutOfSync` / `Unknown` — совпадает ли кластер с git.

**Health status:** `Healthy` / `Progressing` / `Degraded` / `Suspended` / `Missing` — работает ли приложение.

Приложение может быть `Synced` + `Degraded` (манифесты применены, но поды падают) — это самая частая ситуация при плохом релизе.

ArgoCD знает, как оценивать здоровье стандартных ресурсов. Для CRD можно написать **кастомный health check** на Lua:

```yaml
# в argocd-cm ConfigMap
resource.customizations.health.keda.sh_ScaledObject: |
  hs = {}
  if obj.status ~= nil and obj.status.conditions ~= nil then
    for i, condition in ipairs(obj.status.conditions) do
      if condition.type == "Ready" and condition.status == "True" then
        hs.status = "Healthy"
        hs.message = "ScaledObject ready"
        return hs
      end
    end
  end
  hs.status = "Progressing"
  return hs
```

### 5. Sync waves и hooks

Порядок применения задаётся аннотацией:

```yaml
metadata:
  annotations:
    argocd.argoproj.io/sync-wave: "-1"    # меньше = раньше, по умолчанию 0
```

Внутри одной волны порядок стандартный (namespace → CRD → ... → workloads). Между волнами ArgoCD **ждёт готовности** ресурсов предыдущей волны.

Типовое распределение:

| Волна | Что |
|---|---|
| `-3` | Namespace, ResourceQuota |
| `-2` | CRD, операторы |
| `-1` | Secrets, ConfigMaps, БД |
| `0` | Job миграций (PreSync hook) |
| `1` | Deployment, Service |
| `2` | Ingress, HPA, мониторинг |

**ArgoCD hooks** (аналог Helm hooks, но свои):

```yaml
annotations:
  argocd.argoproj.io/hook: PreSync        # PreSync | Sync | PostSync | SyncFail | Skip
  argocd.argoproj.io/hook-delete-policy: HookSucceeded
```

⚠️ Важное взаимодействие: **ArgoCD понимает Helm hooks и конвертирует их в свои.** `pre-install`/`pre-upgrade` → `PreSync`, `post-install`/`post-upgrade` → `PostSync`. Но некоторые Helm-хуки (`pre-delete`) не имеют аналога. Это стоит знать при переносе чартов.

### 6. ArgoCD vs Flux

| | ArgoCD | Flux |
|---|---|---|
| UI | ✅ богатый веб-интерфейс | ❌ только CLI (есть сторонний Weave GitOps) |
| Модель | Application CRD | набор CRD (GitRepository, Kustomization, HelmRelease) |
| Мультикластер | из одного ArgoCD | агент в каждом кластере |
| Обновление образов | Image Updater (отдельно) | встроено (Image Automation) |
| Порог входа | ниже (UI помогает) | выше |
| Подход | «приложение-центричный» | «набор компонентов» |

Обоснование выбора для собеседования: ArgoCD чаще выбирают, когда есть несколько команд и нужна визуальная прозрачность; Flux — когда всё автоматизировано и UI не нужен, а также при упоре на модульность.

### 7. Структура GitOps-репозитория

**Критическое правило: код приложения и манифесты — в разных репозиториях.** Иначе изменение тега образа создаёт коммит в репозитории кода, который триггерит сборку, которая меняет тег... бесконечный цикл.

Рекомендуемая структура:

```
gitops-lab/
├── bootstrap/
│   └── root-app.yaml              # app-of-apps, неделя 13
├── infrastructure/                 # платформенные компоненты
│   ├── ingress-nginx/
│   ├── cert-manager/
│   ├── external-secrets/
│   └── monitoring/
├── apps/
│   ├── myservice/
│   │   ├── base/                  # или Helm-чарт
│   │   ├── dev/
│   │   │   ├── values.yaml
│   │   │   └── application.yaml
│   │   └── prod/
│   └── worker/
└── projects/
    └── team-a.yaml                # AppProject
```

Развилка «директории vs ветки»: **используй директории**, а не ветку на окружение. Ветки создают проблему мержа (изменение из dev нужно черри-пикнуть в prod, история расходится). Директории делают diff между окружениями наглядным.

---

## 🔧 Задание 1: установка и первое приложение (2 ч)

```bash
kubectl create namespace argocd
helm repo add argo https://argoproj.github.io/argo-helm
helm install argocd argo/argo-cd -n argocd \
  --set configs.params."server\.insecure"=true

# пароль
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d

kubectl port-forward svc/argocd-server -n argocd 8080:80
```

Установи CLI (`argocd`) и залогинься.

1. Создай репозиторий `gitops-lab` (GitHub или свой Gitea с недели 0) со структурой из теории.
2. Положи туда свой Helm-чарт (или ссылайся на опубликованный OCI-чарт с недели 11) и values для dev.
3. Подключи репозиторий в ArgoCD.
4. Создай первое `Application` — **декларативно, манифестом**, а не через UI. Через UI посмотри результат.
5. Синхронизируй вручную, посмотри дерево ресурсов в UI. Это одна из лучших визуализаций Kubernetes-приложения, которую ты видел.

---

## 🔧 Задание 2: self-heal и prune (1.5 ч)

Главные эксперименты недели.

1. Включи `automated: { prune: true, selfHeal: true }`.

2. **Дрейф:**
   ```bash
   kubectl scale deploy myservice -n dev --replicas=7
   kubectl get deploy myservice -n dev -w
   ```
   Наблюдай, как ArgoCD возвращает 2 реплики. Засеки время реакции.

3. **Изменение через git:**
   ```bash
   # поменяй replicaCount в values.yaml, закоммить, запушь
   ```
   Засеки, за сколько ArgoCD заметит (без webhook — до 3 минут).

4. **Настрой webhook** от GitHub/Gitea → реакция станет мгновенной. Сравни ощущения.

5. **Prune:** удали ресурс из git (например, ConfigMap) → убедись, что он исчез из кластера. Затем добавь аннотацию `Prune=false` на другой ресурс и повтори — он останется.

6. **Откат через git:**
   ```bash
   git revert HEAD && git push
   ```
   Посмотри, как это выглядит в UI. Сравни с `helm rollback` — в чём преимущество для аудита?

---

## 🔧 Задание 3: sync waves (2 ч)

Собери приложение, которое **не поднимется** без правильного порядка:

1. Namespace (wave -3)
2. Secret через SOPS или ExternalSecret (wave -2)
3. PostgreSQL StatefulSet (wave -1)
4. Job миграций как PreSync hook
5. Deployment приложения (wave 1)
6. Ingress и HPA (wave 2)

Эксперименты:

1. Разверни всё **без** волн → часть ресурсов упадёт, потому что зависимости не готовы. ArgoCD будет ретраить, и в итоге всё поднимется, но грязно и долго. Замерь время.
2. Расставь волны → чистое развёртывание с первого раза. Замерь время, сравни.
3. Сделай миграцию, которая падает → PreSync hook не проходит → синхронизация останавливается, приложение не обновляется. Это правильное поведение.
4. Проверь, что Helm hooks твоего чарта с недели 10 корректно превратились в ArgoCD hooks: `kubectl get jobs -n dev`, статус в UI.

---

## 🔧 Задание 4: полный цикл CI → GitOps (2 ч)

Собери индустриальный паттерн доставки:

```
1. push кода в app-repo
2. CI: сборка образа с тегом = git sha
3. CI: сканирование (Trivy), тесты
4. CI: push образа в registry
5. CI: клонирует gitops-repo, обновляет тег в values-dev.yaml, коммитит, пушит
6. ArgoCD видит изменение → разворачивает в dev
7. Промоушен в prod: PR из dev-values в prod-values, ревью, мёрж
8. ArgoCD разворачивает в prod
```

Шаг 5 реализуй скриптом в CI:

```bash
git clone https://x-access-token:${TOKEN}@github.com/you/gitops-lab
cd gitops-lab
yq -i ".image.tag = \"${GIT_SHA}\"" apps/myservice/dev/values.yaml
git config user.email "ci@company.com"
git config user.name "CI Bot"
git commit -am "chore(dev): myservice ${GIT_SHA}"
git push
```

⚠️ Обрати внимание на дисциплину коммитов: сообщения должны быть машиночитаемыми, чтобы `git log` реально работал как аудит-журнал.

**Альтернатива — ArgoCD Image Updater:** разверни его и настрой автоматическое обновление тега по регулярке. Сравни подходы и запиши вывод:

| | Коммит из CI | Image Updater |
|---|---|---|
| Прозрачность | ✅ явный коммит с автором | коммит от бота или вовсе аннотация |
| Промоушен между средами | ✅ через PR | сложнее |
| Связанность | CI должен знать про gitops-repo | ✅ развязано |

Для прода обычно выбирают первый вариант — именно из-за возможности ревью.

---

## 🔧 Задание 5: несколько окружений и проекты (1.5 ч)

1. Разверни то же приложение в `dev`, `staging`, `prod` тремя Application с разными values.
2. Создай `AppProject` с ограничениями:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: team-a
  namespace: argocd
spec:
  sourceRepos:
    - https://github.com/you/gitops-lab
  destinations:
    - namespace: 'team-a-*'
      server: https://kubernetes.default.svc
  clusterResourceWhitelist: []            # запрет на cluster-scoped ресурсы
  namespaceResourceBlacklist:
    - group: ''
      kind: ResourceQuota
  roles:
    - name: developer
      policies:
        - p, proj:team-a:developer, applications, get, team-a/*, allow
        - p, proj:team-a:developer, applications, sync, team-a/dev-*, allow
```

3. Проверь ограничения: попробуй создать Application, нарушающее правила проекта.
4. Настрой для прода **ручную синхронизацию** (`automated` отключён) — типовая практика: dev автоматом, prod по кнопке или по PR.

---

## 🔧 Задание 6: уведомления (1 ч)

Разверни ArgoCD Notifications и настрой оповещения в Telegram:

```yaml
# argocd-notifications-cm
trigger.on-sync-failed: |
  - when: app.status.operationState.phase in ['Error', 'Failed']
    send: [app-sync-failed]
trigger.on-health-degraded: |
  - when: app.status.health.status == 'Degraded'
    send: [app-degraded]
template.app-sync-failed: |
  message: |
    ❌ {{.app.metadata.name}}: синхронизация не удалась
    {{.app.status.operationState.message}}
```

Подписка на приложении:
```yaml
annotations:
  notifications.argoproj.io/subscribe.on-sync-failed.telegram: "<chat-id>"
```

Проверь: сломай приложение специально и получи уведомление.

---

## 💥 Ломаем специально

1. Включи `selfHeal` и попробуй сделать `kubectl edit` на Deployment. Сколько живёт твоё изменение?
2. Удали файл приложения из git при `prune: true` → ресурсы исчезнут из кластера. Восстанови через `git revert`.
3. Сделай коммит с невалидным YAML → Application уйдёт в `Unknown`/`ComparisonError`. Найди сообщение в UI и в логах repo-server.
4. Укажи несуществующий путь в `spec.source.path` → посмотри на диагностику.
5. Создай два Application, управляющих **одним и тем же** ресурсом → увидь бесконечную борьбу за состояние. Понять этот сценарий важно: он встречается при неаккуратном разделении зон ответственности.
6. Удали Application **без** finalizer → ресурсы останутся в кластере сиротами. Добавь finalizer и повтори — ресурсы удалятся. Пойми разницу.
7. Смасштабируй `application-controller` в 0 реплик → GitOps перестал работать, но приложения продолжают жить. Осознай, что ArgoCD не в data path.

---

## ❓ Самопроверка

1. Push vs pull модель — четыре преимущества pull.
2. Четыре принципа GitOps.
3. Три компонента ArgoCD и ответственность каждого.
4. Sync status и health status — в чём разница? Приведи пример `Synced` + `Degraded`.
5. Что делает `prune: true` и в чём его риск? Как защитить критичный ресурс?
6. Что делает `selfHeal` и какое организационное следствие у его включения?
7. Как задать порядок применения ресурсов? Что происходит между волнами?
8. Как ArgoCD обрабатывает Helm hooks?
9. Почему код приложения и манифесты должны лежать в разных репозиториях?
10. Директории или ветки для окружений? Обоснуй.
11. Два способа обновления версии образа в GitOps, плюсы и минусы каждого.
12. Что произойдёт с работающими приложениями, если ArgoCD полностью выключить?
13. ArgoCD vs Flux — три отличия.
14. Как GitOps решает вопрос секретов? (Подсказка: сам по себе — никак.)

---

## 🔗 Ссылки

| Ресурс | Зачем |
|---|---|
| [Argo CD Documentation](https://argo-cd.readthedocs.io/en/stable/) | Основной источник |
| [Argo CD: Best Practices](https://argo-cd.readthedocs.io/en/stable/user-guide/best_practices/) | Структура репозиториев |
| [Sync Waves and Hooks](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-waves/) | |
| [Sync Options](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/) | Prune, CreateNamespace и др. |
| [Argo CD Notifications](https://argo-cd.readthedocs.io/en/stable/operator-manual/notifications/) | |
| [Argo CD Image Updater](https://argocd-image-updater.readthedocs.io/) | Автообновление образов |
| [OpenGitOps](https://opengitops.dev/) | Принципы |
| [Flux docs](https://fluxcd.io/flux/) | Для сравнения |
| [Argo CD Example Apps](https://github.com/argoproj/argocd-example-apps) | Референсные структуры |
| [Codefresh: GitOps best practices](https://codefresh.io/learn/gitops/) | Обзорные материалы |

---

## ✅ Чек-лист недели

- [ ] ArgoCD установлен, приложение разворачивается из git
- [ ] Application создаются **декларативно**, а не кликами в UI
- [ ] Self-heal проверен: ручное изменение откатывается, время реакции замерено
- [ ] Webhook настроен, реакция на push мгновенная
- [ ] Prune работает, критичный ресурс защищён аннотацией
- [ ] Sync waves расставлены; сравнил время развёртывания с волнами и без
- [ ] Helm hooks корректно работают через ArgoCD
- [ ] Полный цикл CI → git commit → ArgoCD → кластер работает
- [ ] Сравнил подход «коммит из CI» и Image Updater, вывод записан
- [ ] Три окружения, AppProject с ограничениями, prod на ручной синхронизации
- [ ] Уведомления в Telegram приходят при сбое
- [ ] Все 7 экспериментов «Ломаем специально» проделаны
- [ ] `notes/week-12.md` заполнен

---

## 🏁 Контрольная точка месяца 3

- [ ] Пишу production-grade Helm-чарты и понимаю каждую строку
- [ ] Знаю слабые места Helm и умею их обходить
- [ ] Владею Kustomize и могу обосновать выбор между ним и Helm
- [ ] Публикую чарты в OCI-registry через автоматический пайплайн
- [ ] Приложение доставляется в кластер декларативно, через git
- [ ] Могу объяснить GitOps человеку, который его не знает, за 5 минут

**Ключевое действие этой недели — переписать резюме и начать откликаться.** Не потому, что ты «готов», а потому, что первые собеседования нужны как диагностика. У тебя уже есть: Kubernetes на уровне администрирования, Helm, GitOps и публичный репозиторий с реальными артефактами. Этого достаточно, чтобы разговор шёл предметно.

Формулировки для резюме (примеры перевода твоего опыта на язык рынка):

| Было | Стало |
|---|---|
| «Занимался автоматизацией в Jenkins» | «Разработал пайплайны сборки и доставки дистрибутивов; сократил цикл доставки с X до Y» |
| «Поддерживал ansible-роли» | «Разработал универсальный инсталлятор на Ansible для развёртывания продукта у заказчиков; перевёл поставку на Helm-чарты» |
| «Изучал Kubernetes» | «Спроектировал и развернул GitOps-платформу: ArgoCD, собственные Helm-чарты, автоматическая доставка из git (ссылка на GitHub)» |
