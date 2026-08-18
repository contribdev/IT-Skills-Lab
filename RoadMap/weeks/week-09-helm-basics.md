# Неделя 9 — Helm: основы и первый собственный chart

**Цель недели:** написать production-grade chart для своего сервиса руками, понимая каждую строку.
**Время:** 10.5 часов (2.5 ч теории, 8 ч практики).

Отсюда начинается третий месяц — переход от «умею настроить кластер» к «умею промышленно упаковывать и доставлять приложения». Именно этот месяц ближе всего к твоему текущему опыту: ты уже занимаешься доставкой дистрибутивов, просто другими средствами.

---

## 📖 Теория

### 1. Зачем Helm

К концу второго месяца у тебя десятки манифестов. Проблемы, которые они создают:

1. **Дублирование.** dev/staging/prod различаются пятью значениями, а копий манифестов три.
2. **Нет атомарности.** `kubectl apply -f .` может применить половину и упасть. Что откатывать?
3. **Нет версионирования.** Что именно было развёрнуто три недели назад?
4. **Нет удаления комплектом.** Удалить приложение = помнить все его ресурсы.
5. **Нет распространения.** Отдать приложение другой команде = отдать папку с инструкцией.

Helm решает всё это, вводя понятие **release** — установленный экземпляр чарта с именем, версией (revision) и историей.

### 2. Где Helm хранит состояние

Важный вопрос на собеседованиях. Helm 3 хранит информацию о релизе **в самом кластере**, в Secret'ах namespace релиза:

```bash
kubectl get secrets -l owner=helm
# sh.helm.release.v1.myservice.v1
# sh.helm.release.v1.myservice.v2

kubectl get secret sh.helm.release.v1.myservice.v2 -o jsonpath='{.data.release}' \
  | base64 -d | base64 -d | gzip -d | jq .
```

Внутри — сжатый JSON: манифесты, values, метаданные. Отсюда следствия:

- Никакого Tiller (это было в Helm 2, удалено — важное отличие, спрашивают).
- Helm работает с правами твоего kubeconfig, никаких дополнительных привилегий в кластере.
- Удалил Secret вручную — Helm «забыл» о релизе, а ресурсы остались висеть.
- ⚠️ Ограничение размера Secret (1 МБ в etcd) ограничивает размер чарта. Огромные чарты с сотнями CRD упираются в это.

`--history-max` (по умолчанию 10) ограничивает число хранимых ревизий.

### 3. Анатомия чарта

```
mychart/
├── Chart.yaml           # метаданные: name, version, appVersion, dependencies
├── values.yaml          # значения по умолчанию
├── values.schema.json   # JSON-схема для валидации values (неделя 10)
├── templates/
│   ├── _helpers.tpl     # переиспользуемые фрагменты (начинается с _, не рендерится в манифест)
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── ingress.yaml
│   ├── NOTES.txt        # текст после установки
│   └── tests/
│       └── test-connection.yaml
├── charts/              # зависимости (subcharts)
├── crds/                # CRD, ставятся ДО остальных ресурсов и НЕ обновляются Helm'ом
└── .helmignore
```

**Два разных «version» в `Chart.yaml`** — постоянный источник путаницы:

```yaml
apiVersion: v2
name: myservice
version: 1.4.2          # версия САМОГО ЧАРТА (SemVer, обязательно)
appVersion: "2.7.0"     # версия приложения внутри (строка, произвольная)
type: application       # или library
```

Правило: поменял шаблоны → инкремент `version`. Поменял версию приложения → `appVersion`. Они меняются независимо.

### 4. Шаблоны: Go templates + Sprig

```yaml
{{ .Values.replicaCount }}                     # значение из values
{{ .Release.Name }}                            # имя релиза
{{ .Chart.Name }}-{{ .Chart.Version }}
{{ .Values.image.tag | default .Chart.AppVersion }}
{{ .Values.name | quote }}                     # в кавычки
{{ toYaml .Values.resources | nindent 12 }}    # вложенный YAML с отступом
```

**Встроенные объекты:**

| Объект | Что содержит |
|---|---|
| `.Values` | значения из values.yaml + `-f` + `--set` |
| `.Release` | `.Name`, `.Namespace`, `.Revision`, `.IsUpgrade`, `.IsInstall`, `.Service` |
| `.Chart` | содержимое Chart.yaml |
| `.Capabilities` | версия кластера, доступные API (`.APIVersions.Has "networking.k8s.io/v1"`) |
| `.Files` | доступ к файлам чарта (`.Files.Get "config/app.conf"`, `.Files.Glob`) |
| `.Template` | имя текущего шаблона |

**Управляющие конструкции:**

```yaml
{{- if .Values.ingress.enabled }}
...
{{- end }}

{{- with .Values.nodeSelector }}
nodeSelector:
  {{- toYaml . | nindent 2 }}         # внутри with точка = .Values.nodeSelector
{{- end }}

{{- range $key, $value := .Values.env }}
- name: {{ $key }}
  value: {{ $value | quote }}
{{- end }}
```

⚠️ Внутри `with` и `range` **точка переопределяется**. Чтобы добраться до корня, используй `$`: `{{ $.Release.Name }}`. Это ошибка номер один у начинающих.

### 5. Whitespace chomping — где теряются часы

```
{{- ...     удалить пробелы и перенос СЛЕВА
    ... -}} удалить пробелы и перенос СПРАВА
```

YAML чувствителен к отступам, поэтому:

- Для управляющих конструкций почти всегда `{{- if ... }}` и `{{- end }}` — иначе останутся пустые строки.
- Для вставки блоков — **`nindent`, а не `indent`**: `nindent` сначала добавляет перенос строки, потом отступ. Практически всегда нужен именно он.
- Отступ в `nindent N` считается от начала строки, а не от текущей позиции.

Отладка:

```bash
helm template myservice ./mychart --debug
helm template myservice ./mychart | kubectl apply --dry-run=server -f -
```

⚠️ Разница важна: `--dry-run=client` только проверяет синтаксис локально, `--dry-run=server` отправляет в API server и проходит валидацию и admission. Второе гораздо полезнее.

### 6. Именование: `_helpers.tpl`

Стандартный набор, который генерирует `helm create`:

```
{{- define "mychart.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "mychart.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "mychart.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{ include "mychart.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "mychart.selectorLabels" -}}
app.kubernetes.io/name: {{ include "mychart.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
```

⚠️ **Почему `labels` и `selectorLabels` разделены** — ключевой момент. `selector` у Deployment **иммутабелен** (помнишь неделю 2). Если положить в селектор версию чарта, то при каждом обновлении версии Helm будет пытаться изменить неизменяемое поле и апгрейд упадёт. Поэтому в селектор идёт только стабильное подмножество лейблов.

⚠️ `trunc 63` — ограничение длины лейбла в Kubernetes. Без него длинные имена релизов ломают установку.

### 7. Ключевые команды

```bash
helm install myservice ./mychart -n app --create-namespace
helm install myservice ./mychart -f values-prod.yaml --set image.tag=1.2.3
helm upgrade --install myservice ./mychart -f values-prod.yaml   # идемпотентно, так делают в CI
helm list -A
helm history myservice -n app
helm rollback myservice 3 -n app
helm get values myservice          # какие values применены
helm get manifest myservice        # что реально в кластере
helm uninstall myservice --keep-history
helm lint ./mychart
helm template ./mychart            # рендер без установки
```

**Флаги, которые нужны в CI:**
- `--atomic` — при неудаче автоматически откатить (включает `--wait`)
- `--wait --timeout 5m` — ждать готовности ресурсов
- `--create-namespace`

---

## 🔧 Задание 1: препарируем чужой чарт (1.5 ч)

Лучший учебник по Helm — хорошо написанный чужой чарт.

```bash
helm repo add bitnami https://charts.bitnami.com/bitnami
helm pull bitnami/postgresql --untar
cd postgresql
```

Разбор по пунктам (записывай находки в журнал):

1. Прочитай `values.yaml` целиком. Обрати внимание на структуру, комментарии-документацию (`## @param`), группировку.
2. Открой `templates/_helpers.tpl` — посмотри, сколько там именованных шаблонов и зачем.
3. Найди в `templates/` работу с секретами: как чарт решает проблему «сгенерировать пароль при установке, но не менять его при апгрейде». Подсказка — ищи `lookup`.
4. Найди условную логику: что включается флагами.
5. Отрендери и посмотри результат:
   ```bash
   helm template pg . > /tmp/pg.yaml && wc -l /tmp/pg.yaml
   helm template pg . --set architecture=replication | grep -c "kind:"
   ```

Второй чарт для разбора — `ingress-nginx` (ты его уже ставил на неделе 5). Сравни стили: bitnami очень «навороченный», upstream-чарты обычно проще.

---

## 🔧 Задание 2: пишем чарт с нуля руками (3 ч)

**Не используй `helm create` на этом этапе.** Цель — понять каждую строку. Сравнишь со сгенерированным в задании 3.

Создай структуру и наполни:

**`Chart.yaml`:**
```yaml
apiVersion: v2
name: myservice
description: Release automation service (Jira/Artifactory integration)
type: application
version: 0.1.0
appVersion: "1.0.0"
maintainers:
  - name: Your Name
```

**`values.yaml`** — продумай структуру, это важнее шаблонов:
```yaml
replicaCount: 2

image:
  repository: registry.lab/myservice
  tag: ""                 # пусто = взять appVersion
  pullPolicy: IfNotPresent

imagePullSecrets: []
nameOverride: ""
fullnameOverride: ""

serviceAccount:
  create: true
  name: ""
  annotations: {}
  automount: false        # с недели 6 знаешь, зачем

podAnnotations: {}

podSecurityContext:
  runAsNonRoot: true
  runAsUser: 10001
  fsGroup: 10001
  seccompProfile:
    type: RuntimeDefault

securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities:
    drop: ["ALL"]

service:
  type: ClusterIP
  port: 80

ingress:
  enabled: false
  className: nginx
  annotations: {}
  hosts:
    - host: myservice.local
      paths:
        - path: /
          pathType: Prefix
  tls: []

resources:
  requests: { cpu: 100m, memory: 128Mi }
  limits: { memory: 512Mi }        # CPU-лимит намеренно не задаём, неделя 3

probes:
  liveness:
    path: /healthz
    periodSeconds: 10
  readiness:
    path: /readyz
    periodSeconds: 5
  startup:
    enabled: true
    failureThreshold: 30

config:                            # уедет в ConfigMap
  logLevel: info
  jiraUrl: https://jira.company.com
  artifactoryUrl: https://artifactory.company.com

existingSecret: ""                 # имя внешнего Secret, если есть

nodeSelector: {}
tolerations: []
affinity: {}
topologySpreadConstraints: []

podDisruptionBudget:
  enabled: false
  minAvailable: 1

autoscaling:
  enabled: false
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70
```

**Обязательные элементы в шаблонах** (собери всё, что освоил за два месяца):

- `deployment.yaml` с probes, ресурсами, securityContext, preStop, `terminationGracePeriodSeconds`
- `service.yaml`
- `configmap.yaml` из `.Values.config`
- `serviceaccount.yaml` (условно, по `.Values.serviceAccount.create`)
- `ingress.yaml` (условно)
- `hpa.yaml` (условно, взаимоисключающе с `replicaCount`)
- `pdb.yaml` (условно)
- `_helpers.tpl`
- `NOTES.txt`

**Обязательный приём — чексумма конфига** (то, что на неделе 3 делал руками):

```yaml
template:
  metadata:
    annotations:
      checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
      {{- with .Values.podAnnotations }}
      {{- toYaml . | nindent 8 }}
      {{- end }}
```

Теперь изменение ConfigMap автоматически вызывает rolling update. Одна строка вместо ручного патча.

**Взаимоисключение replicas и HPA:**

```yaml
{{- if not .Values.autoscaling.enabled }}
replicas: {{ .Values.replicaCount }}
{{- end }}
```

⚠️ Если оставить `replicas` при включённом HPA, то каждый `helm upgrade` будет сбрасывать количество реплик к значению из values, а HPA — возвращать обратно. Классический баг в проде.

**`NOTES.txt`** — напиши полезный:
```
Приложение {{ include "myservice.fullname" . }} установлено.

{{- if .Values.ingress.enabled }}
Доступно по адресу:
{{- range .Values.ingress.hosts }}
  http{{ if $.Values.ingress.tls }}s{{ end }}://{{ .host }}
{{- end }}
{{- else }}
Проброс порта:
  kubectl port-forward svc/{{ include "myservice.fullname" . }} 8080:{{ .Values.service.port }}
{{- end }}

Версия приложения: {{ .Chart.AppVersion }}
```

---

## 🔧 Задание 3: сравнение с `helm create` (0.5 ч)

```bash
helm create generated
diff -r generated/templates mychart/templates
```

Разбери отличия. Что-то у тебя лучше (ты знаешь, зачем каждая строка), что-то ты упустил. Перенеси полезное к себе, лишнее выкинь.

Обрати внимание: `helm create` генерирует `resources: {}` — пустые ресурсы. Это осознанное решение авторов (не навязывать значения), но для собственного чарта лучше задать разумные дефолты.

---

## 🔧 Задание 4: несколько окружений (1.5 ч)

Создай `values-dev.yaml` и `values-prod.yaml`:

```yaml
# values-dev.yaml
replicaCount: 1
image: { tag: "latest" }
resources:
  requests: { cpu: 50m, memory: 64Mi }
ingress:
  enabled: true
  hosts: [{ host: dev.myservice.lab, paths: [{ path: /, pathType: Prefix }] }]
config: { logLevel: debug }
```

```yaml
# values-prod.yaml
replicaCount: 3
autoscaling: { enabled: true, minReplicas: 3, maxReplicas: 15 }
podDisruptionBudget: { enabled: true, minAvailable: 2 }
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: kubernetes.io/hostname
    whenUnsatisfiable: ScheduleAnyway
    labelSelector:
      matchLabels:
        app.kubernetes.io/name: myservice
config: { logLevel: warn }
```

Установи оба, проверь работу:

```bash
helm upgrade --install myservice-dev ./mychart -n dev --create-namespace -f values-dev.yaml
helm upgrade --install myservice-prod ./mychart -n prod --create-namespace -f values-prod.yaml
helm list -A
```

**Проверь приоритет values** (спрашивают): `values.yaml` чарта → `-f file1` → `-f file2` (последний побеждает) → `--set` (побеждает всё).

```bash
helm template ./mychart -f values-dev.yaml --set replicaCount=7 | grep replicas
```

---

## 🔧 Задание 5: жизненный цикл релиза (1 ч)

```bash
# upgrade
helm upgrade myservice-prod ./mychart -f values-prod.yaml --set image.tag=1.0.1 --atomic

helm history myservice-prod -n prod
helm get values myservice-prod -n prod
helm get manifest myservice-prod -n prod | head -50

# rollback
helm rollback myservice-prod 1 -n prod
helm history myservice-prod -n prod        # обрати внимание: rollback создаёт НОВУЮ ревизию
```

Эксперименты:
1. Разверни заведомо нерабочий образ **без** `--atomic` → релиз в состоянии `deployed`, но поды падают. Helm считает, что всё хорошо. Почему?
2. То же **с** `--atomic --wait` → Helm дождётся готовности, не дождётся, откатится сам. Сравни поведение и запиши вывод: для CI обязательно `--atomic`.
3. Загляни в Secret'ы релиза (команда из теории), разожми и посмотри содержимое.
4. Удали Secret одной ревизии вручную → посмотри, что покажет `helm history`.

---

## 🔧 Задание 6: helm-diff (0.5 ч)

```bash
helm plugin install https://github.com/databus23/helm-diff
helm diff upgrade myservice-prod ./mychart -f values-prod.yaml --set image.tag=1.0.2
```

Введи это в постоянную привычку: **смотреть diff перед каждым upgrade**. Это ровно тот навык, который на неделе 12 превратится в ревью PR в GitOps-репозитории.

---

## 💥 Ломаем специально

1. Забудь `{{-` в условии `if` → получи пустые строки в YAML. Посмотри через `helm template`, найди, где именно ломается.
2. Используй `indent` вместо `nindent` в блоке `resources` → сломанный YAML. Разберись, в чём разница.
3. Внутри `range` обратись к `.Release.Name` без `$` → ошибка рендера. Прочитай текст ошибки, он информативный.
4. Положи `app.kubernetes.io/version` в `selectorLabels`, установи, потом измени `appVersion` и сделай upgrade → **релиз упадёт** на попытке изменить иммутабельный селектор. Это самая частая реальная поломка Helm-чартов; воспроизведи её обязательно и пойми, как чинить (только удаление и переустановка).
5. Задай имя релиза длиной 60+ символов и убери `trunc 63` из хелперов → ошибка валидации лейблов.
6. Включи одновременно `replicaCount: 5` и `autoscaling.enabled: true` без условия → понаблюдай борьбу Helm и HPA.

---

## ❓ Самопроверка

1. Где Helm 3 хранит состояние релиза? Чем это отличается от Helm 2?
2. Разница между `version` и `appVersion` в `Chart.yaml`. Что инкрементировать, когда обновил только шаблон?
3. Что делает `nindent` и почему он нужен чаще, чем `indent`?
4. Почему внутри `with`/`range` нужен `$` для доступа к корню?
5. Зачем в `_helpers.tpl` разделены `labels` и `selectorLabels`? Что сломается, если объединить?
6. Приоритет values: чарт, `-f`, `--set` — кто побеждает?
7. Что делает `--atomic` и почему без него CI-пайплайн ненадёжен?
8. Как сделать так, чтобы изменение ConfigMap приводило к перезапуску подов?
9. Почему `replicas` нужно убирать из шаблона при включённом HPA?
10. `helm template` vs `--dry-run=client` vs `--dry-run=server` — в чём разница и что полезнее?
11. Что произойдёт, если удалить Secret с релизом, но оставить ресурсы в кластере?
12. Rollback создаёт новую ревизию или возвращает старую?

---

## 🔗 Ссылки

| Ресурс | Зачем |
|---|---|
| [Helm: Chart Template Guide](https://helm.sh/docs/chart_template_guide/) | Главный документ недели, читать целиком |
| [Helm: Charts](https://helm.sh/docs/topics/charts/) | Структура и Chart.yaml |
| [Helm Best Practices](https://helm.sh/docs/chart_best_practices/) | Соглашения по именованию и values |
| [Sprig Function Documentation](https://masterminds.github.io/sprig/) | Все функции шаблонов |
| [Go template docs](https://pkg.go.dev/text/template) | Базовый синтаксис |
| [Artifact Hub](https://artifacthub.io/) | Каталог чартов для разбора |
| [helm-diff](https://github.com/databus23/helm-diff) | Обязательный плагин |
| [Bitnami charts](https://github.com/bitnami/charts) | Референс сложных чартов |
| [Common labels](https://kubernetes.io/docs/concepts/overview/working-with-objects/common-labels/) | Стандарт лейблов |

---

## ✅ Чек-лист недели

- [ ] Разобрал чужой чарт (bitnami/postgresql), понял его структуру и приёмы
- [ ] Написал собственный чарт **руками**, без `helm create`
- [ ] Чарт включает: probes, ресурсы, securityContext, SA, ConfigMap, Ingress, HPA, PDB — всё условно
- [ ] `_helpers.tpl` с корректным разделением labels/selectorLabels и `trunc 63`
- [ ] Чексумма конфига в аннотациях работает: изменение ConfigMap вызывает rolling update
- [ ] Установлен в двух окружениях с разными values
- [ ] Проверил приоритет values и поведение `--atomic`
- [ ] Посмотрел содержимое Secret'а релиза изнутри
- [ ] Установлен и введён в привычку `helm-diff`
- [ ] **Воспроизвёл поломку с иммутабельным селектором** — обязательно
- [ ] Все 6 экспериментов «Ломаем специально» проделаны
- [ ] Чарт лежит в `03-helm-charts/`, `notes/week-09.md` заполнен
