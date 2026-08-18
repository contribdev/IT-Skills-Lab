# Неделя 10 — Helm: зависимости, hooks, схемы, тесты

**Цель недели:** собрать многокомпонентный чарт промышленного уровня и узнать, что Helm делает плохо.
**Время:** 11 часов (3 ч теории, 8 ч практики).

Знание слабых мест Helm ценится выше, чем знание синтаксиса шаблонов. На собеседовании вопрос «что тебе не нравится в Helm» — это проверка на реальный опыт.

---

## 📖 Теория

### 1. Зависимости и subcharts

```yaml
# Chart.yaml
dependencies:
  - name: postgresql
    version: "15.x.x"
    repository: https://charts.bitnami.com/bitnami
    condition: postgresql.enabled          # включать по флагу
  - name: redis
    version: "19.x.x"
    repository: https://charts.bitnami.com/bitnami
    condition: redis.enabled
    alias: cache                           # переименовать
  - name: common
    version: "2.x.x"
    repository: https://charts.bitnami.com/bitnami
    tags: [shared]                         # групповое включение
```

```bash
helm dependency update      # скачать в charts/, создать Chart.lock
helm dependency build       # установить строго по Chart.lock
```

⚠️ `Chart.lock` **коммить в git** — иначе сборка невоспроизводима, как и в любом пакетном менеджере.

**Передача values в subchart** — по имени (или alias):

```yaml
# values.yaml родителя
postgresql:
  enabled: true
  auth:
    database: myapp
  primary:
    persistence:
      size: 20Gi
```

**Global values** — единственный способ передать значение во все subcharts сразу:

```yaml
global:
  imageRegistry: registry.lab
  storageClass: fast
```

⚠️ Порядок применения: **values родителя перекрывают values subchart'а**. Обратное невозможно — subchart не может влиять на родителя (кроме через `global`).

⚠️ Главная ловушка subcharts: **вложенность.** Чарт с тремя уровнями зависимостей превращается в лабиринт, где непонятно, откуда взялось значение. Практический совет из индустрии: не более одного уровня вложенности; для БД в проде чаще берут оператор, а не subchart.

Отладка:
```bash
helm template . --debug | grep -A5 "name: myapp-postgresql"
helm show values bitnami/postgresql | less     # какие values принимает зависимость
```

### 2. Hooks

Hooks позволяют выполнять ресурсы на определённых этапах жизненного цикла.

```yaml
metadata:
  annotations:
    "helm.sh/hook": pre-upgrade,pre-install
    "helm.sh/hook-weight": "-5"                # меньше = раньше
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
```

**Точки:**

| Hook | Когда |
|---|---|
| `pre-install` / `post-install` | до/после первой установки |
| `pre-upgrade` / `post-upgrade` | до/после апгрейда |
| `pre-delete` / `post-delete` | до/после удаления |
| `pre-rollback` / `post-rollback` | вокруг отката |
| `test` | по команде `helm test` |

**delete-policy:**
- `before-hook-creation` (по умолчанию) — удалить предыдущий объект перед созданием нового
- `hook-succeeded` — удалить после успеха
- `hook-failed` — удалить после неудачи

Типовое применение — миграции БД:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ include "myservice.fullname" . }}-migrate
  annotations:
    "helm.sh/hook": pre-upgrade,pre-install
    "helm.sh/hook-weight": "-5"
    "helm.sh/hook-delete-policy": before-hook-creation
spec:
  backoffLimit: 2
  activeDeadlineSeconds: 600
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: migrate
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}"
          command: ["alembic", "upgrade", "head"]
```

⚠️ **Критические особенности hooks, которые нужно знать:**

1. **Ресурсы-hooks не управляются Helm как часть релиза.** Они не попадают в `helm get manifest`, не удаляются при `helm uninstall` (если нет `delete-policy`), не откатываются при rollback.
2. **Провал hook останавливает весь релиз.** Job миграций упал → апгрейд не состоялся. Это одновременно фича и источник проблем.
3. **Rollback не откатывает миграции.** Helm вернёт старые манифесты, но схема БД останется новой. Отсюда правило: миграции должны быть обратно совместимыми (expand/contract), а не «в одну сторону».
4. **Hook, зависший навсегда** (Job без `activeDeadlineSeconds`, который никогда не завершится) оставляет релиз в состоянии `pending-upgrade`. Всегда ставь таймаут.

### 3. Застрявшие релизы

Состояния `pending-install`, `pending-upgrade`, `pending-rollback` означают, что процесс Helm был прерван (упал CI, таймаут, Ctrl+C). Helm 3 не умеет автоматически выходить из них: следующий `upgrade` откажется работать с сообщением «another operation is in progress».

Способы выйти:

```bash
# Способ 1: откатить на последнюю успешную ревизию
helm rollback myservice <номер-последней-deployed>

# Способ 2 (Helm 3.13+): пометить релиз как failed
helm status myservice
# затем удалить Secret последней зависшей ревизии:
kubectl delete secret sh.helm.release.v1.myservice.v7

# Способ 3: крайняя мера
helm uninstall myservice --keep-history  # и переустановить
```

Это очень частый реальный инцидент. Проверь оба способа на практике — пригодится.

### 4. `values.schema.json`

Валидация values до применения. Помогает поймать опечатки и неверные типы.

```json
{
  "$schema": "https://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["image", "service"],
  "properties": {
    "replicaCount": { "type": "integer", "minimum": 1, "maximum": 100 },
    "image": {
      "type": "object",
      "required": ["repository"],
      "properties": {
        "repository": { "type": "string" },
        "tag": { "type": "string" },
        "pullPolicy": { "enum": ["Always", "IfNotPresent", "Never"] }
      }
    },
    "service": {
      "type": "object",
      "properties": {
        "type": { "enum": ["ClusterIP", "NodePort", "LoadBalancer"] },
        "port": { "type": "integer", "minimum": 1, "maximum": 65535 }
      }
    },
    "config": {
      "type": "object",
      "properties": {
        "logLevel": { "enum": ["debug", "info", "warn", "error"] }
      }
    }
  }
}
```

Схема проверяется при `install`, `upgrade`, `lint`, `template`. Ошибка выдаётся до обращения к кластеру — быстро и понятно.

⚠️ Ограничение: схема применяется к **итоговым** values после слияния. Проверить «этот параметр обязателен только если включён ingress» можно через `if/then` или `dependencies` в JSON Schema, но читаемость страдает.

### 5. `helm test`

Ресурсы с аннотацией `"helm.sh/hook": test` запускаются командой `helm test`:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: "{{ include "myservice.fullname" . }}-test-connection"
  annotations:
    "helm.sh/hook": test
    "helm.sh/hook-delete-policy": hook-succeeded
spec:
  restartPolicy: Never
  containers:
    - name: test
      image: curlimages/curl:latest
      command: ["sh", "-c"]
      args:
        - |
          set -e
          curl -sf http://{{ include "myservice.fullname" . }}:{{ .Values.service.port }}/healthz
          curl -sf http://{{ include "myservice.fullname" . }}:{{ .Values.service.port }}/readyz
          echo "OK"
```

```bash
helm test myservice -n app --logs
```

Это база для CI на неделе 11: поднять kind, установить чарт, прогнать `helm test`, снести кластер.

### 6. Library charts

Чарт с `type: library` не устанавливается сам, а поставляет шаблоны другим чартам. Полезно, когда у тебя 10 микросервисов с одинаковой структурой.

```yaml
# common-lib/Chart.yaml
apiVersion: v2
name: common-lib
type: library
version: 1.0.0
```

```yaml
# common-lib/templates/_deployment.yaml
{{- define "common.deployment" -}}
apiVersion: apps/v1
kind: Deployment
...
{{- end }}
```

В потребителе:
```yaml
{{- include "common.deployment" . }}
```

⚠️ Реальность: library charts дают экономию, но усложняют отладку. Практическое правило — начинать с них, когда однотипных чартов больше пяти.

### 7. Что Helm делает плохо

Готовый ответ на собеседование:

1. **CRD.** Файлы в `crds/` ставятся один раз и **никогда не обновляются** Helm'ом. Обновление CRD — ручная операция или отдельный процесс. Это осознанное решение авторов (обновление CRD может уничтожить данные), но на практике болезненное.
2. **Нет отслеживания дрейфа.** Кто-то поменял ресурс через `kubectl` — Helm об этом не узнает. `helm upgrade` может даже не заметить разницу, потому что сравнивает с сохранённым манифестом, а не с кластером. (Отсюда — ArgoCD на неделе 12.)
3. **Порядок применения ресурсов** фиксирован и не настраивается (кроме hooks). Иногда это не то, что нужно.
4. **Отладка шаблонов** — Go templates поверх YAML остаются болезненными. Ошибка в отступе даёт сообщение, которое указывает не туда.
5. **Логика в шаблонах.** Сложные чарты превращаются в программу на языке, не предназначенном для программирования.
6. **Секреты.** Нативной поддержки нет, нужны плагины или внешние решения.
7. **Ограничение размера релиза** (1 МБ на Secret).

Именно из-за пунктов 2 и 5 существует Kustomize (неделя 11), а из-за пункта 2 — ArgoCD (неделя 12).

---

## 🔧 Задание 1: многокомпонентный чарт (3.5 ч)

Собери умышленно сложный чарт, который отражает реальное приложение:

```
myplatform/
├── Chart.yaml               # зависимости: postgresql, redis
├── values.yaml
├── values.schema.json
├── templates/
│   ├── _helpers.tpl
│   ├── api-deployment.yaml       # web-компонент
│   ├── api-service.yaml
│   ├── worker-deployment.yaml    # фоновый обработчик
│   ├── worker-keda.yaml          # ScaledObject (условно)
│   ├── configmap.yaml
│   ├── secret.yaml               # только если не задан existingSecret
│   ├── ingress.yaml
│   ├── serviceaccount.yaml
│   ├── rbac.yaml
│   ├── networkpolicy.yaml
│   ├── pdb.yaml
│   ├── job-migrate.yaml          # pre-upgrade hook
│   ├── NOTES.txt
│   └── tests/
│       └── test-connection.yaml
```

Требования к реализации:

1. **Два деплоймента** (api и worker) с общими хелперами, но разными лейблами компонента (`app.kubernetes.io/component: api` / `worker`).
2. **Postgres и Redis как зависимости** с `condition`, чтобы в проде можно было указать внешние.
3. **Логика подключения:** если `postgresql.enabled=true` — использовать внутренний хост, иначе брать из `.Values.externalDatabase.host`. Это классический паттерн, реализуй его в `_helpers.tpl`:

```yaml
{{- define "myplatform.databaseHost" -}}
{{- if .Values.postgresql.enabled -}}
{{ .Release.Name }}-postgresql
{{- else -}}
{{ required "externalDatabase.host обязателен при postgresql.enabled=false" .Values.externalDatabase.host }}
{{- end -}}
{{- end }}
```

⚠️ Обрати внимание на функцию `required` — она даёт понятную ошибку вместо пустого значения в манифесте. Используй её для всех критичных параметров.

4. **Генерация пароля при установке с сохранением при апгрейде** — приём из bitnami:

```yaml
{{- $existing := lookup "v1" "Secret" .Release.Namespace (include "myplatform.fullname" .) }}
{{- $password := "" }}
{{- if $existing }}
{{- $password = index $existing.data "app-password" | b64dec }}
{{- else }}
{{- $password = randAlphaNum 32 }}
{{- end }}
```

⚠️ `lookup` возвращает пустоту при `helm template` (нет доступа к кластеру) — учитывай это, иначе рендер вне кластера сгенерирует новый пароль.

---

## 🔧 Задание 2: hooks и миграции (2 ч)

1. Реализуй Job миграций как `pre-upgrade,pre-install` hook с `hook-weight: "-5"`.
2. Проверь, что он запускается **до** обновления Deployment: наблюдай `kubectl get pods -w` во время `helm upgrade`.
3. Убедись, что Job не виден в `helm get manifest`.
4. Сделай миграцию, которая падает → апгрейд не состоится, приложение останется на старой версии. Это правильное поведение.
5. Добавь `post-install` hook, который отправляет уведомление (можно просто `curl` на webhook.site).
6. Проверь `hook-delete-policy`: с `hook-succeeded` Job исчезает после успеха, без него — накапливается.

💥 **Обязательный эксперимент:** сделай Job без `activeDeadlineSeconds`, который никогда не завершается (`sleep infinity`), запусти `helm upgrade` с коротким `--timeout 1m`. Получишь релиз в состоянии `pending-upgrade`. Затем **выйди из этого состояния всеми тремя способами** из теории. Это самая полезная поломка недели — она встречается в реальной работе постоянно.

---

## 🔧 Задание 3: схема и валидация (1 ч)

1. Напиши `values.schema.json` для своего чарта, покрыв основные параметры.
2. Проверь, что ловится:
   ```bash
   helm template . --set replicaCount=abc          # тип
   helm template . --set service.type=Weird        # enum
   helm template . --set replicaCount=0            # minimum
   helm template . --set image.repository=null     # required
   ```
3. Добавь условную валидацию: если `ingress.enabled=true`, то `ingress.hosts` обязателен.
4. Сравни сообщения об ошибках: от схемы (понятное, до применения) и от `required` в шаблоне (тоже понятное, но позже). Пойми, когда что уместнее.

---

## 🔧 Задание 4: helm test (1 ч)

1. Напиши тесты: доступность `/healthz`, доступность `/readyz`, доступность БД из пода приложения.
2. Прогони: `helm test myplatform -n app --logs`.
3. Сделай так, чтобы тест падал (сломай сервис), убедись в понятном выводе.
4. Оформи тест-под с `restartPolicy: Never` и `hook-delete-policy: hook-succeeded`, чтобы не оставлял мусор.

---

## 🔧 Задание 5: library chart (1.5 ч)

1. Вынеси общие шаблоны (лейблы, деплоймент, сервис) в отдельный чарт `common-lib` с `type: library`.
2. Подключи его как зависимость к двум разным чартам.
3. Убедись, что изменение в library влияет на оба.
4. Запиши в журнал честный вывод: **окупилась ли эта абстракция на двух чартах?** (Скорее нет — и это правильный ответ. Понимание, когда абстракция преждевременна, ценнее умения её строить.)

---

## 🔧 Задание 6: CRD и дрейф (1 ч)

Два эксперимента, демонстрирующих слабости Helm:

**CRD:**
1. Создай чарт с CRD в папке `crds/`.
2. Установи, потом измени CRD в чарте и сделай `helm upgrade`. Убедись, что CRD **не обновился**.
3. Найди в документации Helm объяснение, почему так сделано.
4. Посмотри, как эту проблему решают чарты вроде cert-manager (флаг `crds.enabled` и CRD как обычные шаблоны).

**Дрейф:**
1. Установи релиз.
2. Измени что-нибудь вручную: `kubectl scale deploy myservice --replicas=7`, `kubectl set image ...`.
3. Сделай `helm upgrade` с теми же values. Что произойдёт? А `helm diff upgrade` — покажет ли расхождение?
4. Сделай вывод и запиши: **Helm не знает о состоянии кластера, он сравнивает с сохранённым манифестом.** Именно эту проблему решает ArgoCD на неделе 12.

---

## 💥 Ломаем специально

1. Зависимость с несовместимой версией в `Chart.yaml` → ошибка `helm dependency update`. Прочитай сообщение.
2. Удали `Chart.lock` и переустанови зависимости — увидь, как подтянутся более новые версии. Осознай риск невоспроизводимости.
3. Передай значение в subchart с неправильным ключом (опечатка в имени чарта) → значение просто проигнорируется молча. Пойми, почему это опасно и как ловится (`helm template --debug`).
4. Hook с `hook-weight` в неправильном порядке → миграция запустится после деплоя нового кода. Воспроизведи и увидь последствия.
5. Сделай `helm uninstall` для чарта с hooks без `delete-policy` → Job'ы останутся в namespace висеть.
6. Установи чарт с очень большим количеством ресурсов (сгенерируй 2000 ConfigMap через `range`) → упрёшься в лимит размера Secret. Прочитай ошибку.

---

## ❓ Самопроверка

1. Зачем нужен `Chart.lock` и надо ли его коммитить?
2. Может ли subchart изменить values родителя? Как передать значение во все subcharts?
3. Что происходит с ресурсом-hook при `helm uninstall`? А при `rollback`?
4. Job миграций упал во время `pre-upgrade` — что будет с релизом?
5. Rollback отменит миграцию БД? Как проектировать миграции с учётом этого?
6. Релиз в состоянии `pending-upgrade` — три способа выйти.
7. Почему Helm не обновляет CRD? Как это обходят популярные чарты?
8. Кто-то изменил Deployment через kubectl. Заметит ли это `helm upgrade`? А `helm diff`?
9. Что возвращает функция `lookup` при `helm template` вне кластера? Какую проблему это создаёт?
10. Зачем функция `required` и чем она лучше пустого значения?
11. Когда library chart оправдан?
12. Назови пять слабых мест Helm.

---

## 🔗 Ссылки

| Ресурс | Зачем |
|---|---|
| [Helm: Chart Hooks](https://helm.sh/docs/topics/charts_hooks/) | Главная тема недели |
| [Subcharts and Global Values](https://helm.sh/docs/chart_template_guide/subcharts_and_globals/) | Зависимости |
| [Schema Files](https://helm.sh/docs/topics/charts/#schema-files) | values.schema.json |
| [Library Charts](https://helm.sh/docs/topics/library_charts/) | |
| [Chart Tests](https://helm.sh/docs/topics/chart_tests/) | |
| [Custom Resource Definitions в Helm](https://helm.sh/docs/chart_best_practices/custom_resource_definitions/) | Почему CRD не обновляются |
| [JSON Schema](https://json-schema.org/learn/getting-started-step-by-step) | Справочник по схемам |
| [Bitnami: паттерн генерации паролей](https://github.com/bitnami/charts/blob/main/bitnami/common/templates/_secrets.tpl) | Референс приёма с `lookup` |

---

## ✅ Чек-лист недели

- [ ] Многокомпонентный чарт: api + worker + БД и Redis как зависимости с `condition`
- [ ] Реализован паттерн «внутренняя или внешняя БД» через хелпер с `required`
- [ ] Реализована генерация пароля с сохранением при апгрейде через `lookup`
- [ ] Job миграций как `pre-upgrade` hook с `hook-weight` и `activeDeadlineSeconds`
- [ ] **Воспроизвёл застрявший релиз и вышел из него тремя способами**
- [ ] `values.schema.json` ловит ошибки типов, enum и обязательных полей
- [ ] `helm test` проверяет работоспособность после установки
- [ ] Собрал library chart и записал честный вывод о его целесообразности
- [ ] Проверил на опыте: CRD не обновляются, дрейф не детектируется
- [ ] Все 6 экспериментов «Ломаем специально» проделаны
- [ ] Могу назвать пять слабых мест Helm и объяснить каждое
- [ ] `notes/week-10.md` заполнен
