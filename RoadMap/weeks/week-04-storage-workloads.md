# Неделя 4 — Хранилище и workload-контроллеры

**Цель недели:** научиться работать с состоянием и разобраться, чем StatefulSet, DaemonSet и Job отличаются от Deployment.
**Время:** 10 часов (3 ч теории, 7 ч практики).

Это последняя неделя первого месяца. К её концу твой сервис должен уметь всё, что нужно продовому приложению, и жить рядом с базой данных в кластере.

---

## 📖 Теория

### 1. Volumes: три уровня абстракции

**Уровень 0 — эфемерные тома** (живут столько же, сколько под):

- `emptyDir` — пустая директория, общая для контейнеров пода. Классика: обмен данными между sidecar и основным контейнером, кэш, временные файлы. `emptyDir: { medium: Memory }` кладёт данные в tmpfs (быстро, но ест лимит памяти пода).
- `hostPath` — каталог с ноды. ⚠️ Опасен: под может смонтировать `/etc` или сокет docker. В проде почти везде запрещён политиками. Легитимное применение — DaemonSet'ы агентов мониторинга.
- `projected` — объединение нескольких источников (secret, configMap, serviceAccountToken, downwardAPI) в одну точку монтирования.
- `downwardAPI` — метаданные самого пода (имя, namespace, лейблы, лимиты) как файлы или env.

**Уровень 1 — PersistentVolume (PV)** — кусок хранилища в кластере, cluster-scoped объект. Может быть создан администратором вручную (статически) или провижионером автоматически.

**Уровень 2 — PersistentVolumeClaim (PVC)** — заявка приложения: «мне нужно 10Gi с режимом ReadWriteOnce из класса fast». Namespaced. Приложение **никогда не работает с PV напрямую**, только через PVC. Это и есть разделение ответственности: разработчик просит объём, платформа решает, откуда его взять.

### 2. StorageClass и динамическое провижионирование

StorageClass описывает «сорт» хранилища: какой провижионер, с какими параметрами.

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: fast
provisioner: rancher.io/local-path
reclaimPolicy: Delete
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
```

Ключевые параметры:

- **`reclaimPolicy`**: `Delete` — при удалении PVC удаляется и PV с данными. `Retain` — PV остаётся в состоянии `Released`, данные сохранены, но переиспользовать его автоматически нельзя (нужно вручную чистить `claimRef`). ⚠️ Для продовых БД — всегда `Retain`.
- **`volumeBindingMode`**: `Immediate` — том создаётся сразу при создании PVC. `WaitForFirstConsumer` — только когда появится под, и **на той ноде, куда его запланировал scheduler**. Второй режим критичен для локальных дисков и зональных облачных дисков: иначе scheduler может отправить под на ноду, где тома нет.
- **`allowVolumeExpansion`** — можно ли увеличить том, отредактировав PVC. Уменьшить нельзя никогда.

### 3. Access modes и почему RWX — это боль

| Режим | Расшифровка | Реальность |
|---|---|---|
| **RWO** (ReadWriteOnce) | Чтение-запись **одной нодой** | Блочные диски: EBS, облачные диски, local-path. 95% случаев |
| **ROX** (ReadOnlyMany) | Только чтение многими нодами | Редко |
| **RWX** (ReadWriteMany) | Чтение-запись многими нодами | Только сетевые ФС: NFS, CephFS, облачные file-сервисы. Медленно и дорого |
| **RWOP** (ReadWriteOncePod) | Только один под | Появился в 1.22, для строгих гарантий |

⚠️ Тонкость, которую спрашивают: **RWO — это «одна нода», а не «один под».** Два пода на одной ноде могут писать в один RWO-том. Именно поэтому появился RWOP.

Практический вывод: если архитектура приложения требует RWX (несколько реплик пишут в один каталог) — почти всегда это признак того, что приложение не готово к контейнерам, и правильнее переделать его на объектное хранилище (S3/MinIO).

### 4. StatefulSet

Deployment считает поды взаимозаменяемыми. Для баз данных это неверно: у реплики есть идентичность, свой диск и своя роль.

Что даёт StatefulSet:

| Свойство | Deployment | StatefulSet |
|---|---|---|
| Имена подов | `web-7d4f8c-x9k2l` (случайные) | `db-0`, `db-1`, `db-2` (стабильные, ordinal) |
| DNS каждого пода | нет | `db-0.db.ns.svc.cluster.local` |
| Персональный том | нет | `volumeClaimTemplates` — свой PVC на каждый под |
| Порядок создания | параллельно | по очереди, 0 → 1 → 2 |
| Порядок удаления | параллельно | обратный: 2 → 1 → 0 |
| Обновление | RollingUpdate по ReplicaSet | по одному, с конца; есть `partition` для канареек |

Требует **headless-сервис** (`clusterIP: None`) — именно он даёт per-pod DNS.

⚠️ Важнейший момент: **при удалении StatefulSet PVC не удаляются.** Это защита от потери данных. Чистить нужно руками. С 1.27 есть `persistentVolumeClaimRetentionPolicy`, но по умолчанию поведение прежнее.

⚠️ Второй момент: StatefulSet **не делает приложение кластерным**. Он даёт идентичность и диски, а репликацию данных, выбор лидера и failover настраиваешь ты сам (или оператор). Поэтому в проде БД чаще ставят операторами (CloudNativePG, Percona, Zalando postgres-operator), а не голым StatefulSet.

### 5. DaemonSet

По одному поду **на каждую ноду** (или на каждую подходящую по селектору). Новая нода в кластере → под появляется автоматически.

Применение: агенты сбора логов (Promtail — неделя 15), node-exporter (неделя 14), CNI-плагины, CSI-драйверы, NVIDIA device plugin (неделя 22).

Особенности:
- Обычно нужны `tolerations`, чтобы попадать в том числе на control-plane и на taint'ованные ноды
- Часто требуются `hostPath`, `hostNetwork`, повышенные привилегии — это легитимный случай для исключений в политиках безопасности
- Стратегия обновления `RollingUpdate` с `maxUnavailable`

### 6. Job и CronJob

**Job** — задача, которая должна завершиться успешно.

```yaml
spec:
  completions: 5            # сколько успешных завершений нужно
  parallelism: 2            # сколько выполнять одновременно
  backoffLimit: 4           # сколько раз перезапускать при падении
  activeDeadlineSeconds: 600  # жёсткий таймаут на всю Job
  ttlSecondsAfterFinished: 3600  # автоудаление после завершения
  template:
    spec:
      restartPolicy: OnFailure   # или Never; Always запрещён для Job
```

⚠️ `backoffLimit` считает **перезапуски пода**, а не время. При `restartPolicy: OnFailure` перезапускается контейнер в том же поде, при `Never` — создаётся новый под. Разница влияет на то, где искать логи упавших попыток.

⚠️ Без `ttlSecondsAfterFinished` завершённые поды копятся в кластере месяцами. Ставь всегда.

**CronJob** — Job по расписанию (синтаксис cron, часовой пояс через `timeZone` с 1.27).

```yaml
spec:
  schedule: "0 3 * * *"
  timeZone: "Europe/Moscow"
  concurrencyPolicy: Forbid       # Allow | Forbid | Replace
  startingDeadlineSeconds: 300
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
```

⚠️ `concurrencyPolicy: Allow` (по умолчанию) — если предыдущий запуск не успел завершиться, запустится второй параллельно. Для задач, которые ходят в БД или в Artifactory, это часто источник гонок. Ставь `Forbid` осознанно.

---

## 🔧 Задание 1: PV, PVC, StorageClass (1.5 ч)

```bash
kubectl get storageclass
kubectl describe sc local-path
```

1. Создай PVC, задеплой под, который в него пишет:
   ```yaml
   apiVersion: v1
   kind: PersistentVolumeClaim
   metadata: { name: data }
   spec:
     accessModes: [ReadWriteOnce]
     resources: { requests: { storage: 1Gi } }
     storageClassName: local-path
   ```
2. Найди, **где физически** лежат данные на ноде:
   ```bash
   kubectl get pv
   kubectl describe pv <name>     # ищи path и node affinity
   # затем на ноде: ls -la /var/lib/rancher/k3s/storage/
   ```
3. Удали под, создай заново — данные на месте.
4. Удали PVC → посмотри, что стало с PV (при `reclaimPolicy: Delete` он исчезнет вместе с данными).
5. Создай StorageClass с `reclaimPolicy: Retain`, повтори эксперимент, увидь состояние `Released` и данные, которые остались.

**Отдельно разберись с `WaitForFirstConsumer`:** создай PVC без пода при `Immediate` и при `WaitForFirstConsumer`, сравни состояние (`Bound` vs `Pending`). Объясни себе, зачем это нужно.

---

## 🔧 Задание 2: PostgreSQL как StatefulSet (2.5 ч)

Пиши руками, не через Helm-чарт — цель понять механику.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: pg
spec:
  clusterIP: None            # headless
  selector: { app: pg }
  ports: [{ port: 5432, name: pg }]
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: pg
spec:
  serviceName: pg            # обязательно, ссылается на headless-сервис
  replicas: 3
  selector:
    matchLabels: { app: pg }
  template:
    metadata:
      labels: { app: pg }
    spec:
      terminationGracePeriodSeconds: 30
      containers:
        - name: postgres
          image: postgres:16-alpine
          env:
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef: { name: pg-secret, key: password }
            - name: PGDATA
              value: /var/lib/postgresql/data/pgdata
          ports: [{ containerPort: 5432, name: pg }]
          volumeMounts:
            - name: data
              mountPath: /var/lib/postgresql/data
          readinessProbe:
            exec: { command: ["pg_isready", "-U", "postgres"] }
            periodSeconds: 5
  volumeClaimTemplates:
    - metadata: { name: data }
      spec:
        accessModes: [ReadWriteOnce]
        resources: { requests: { storage: 2Gi } }
```

⚠️ `PGDATA` в подкаталоге — не прихоть: PostgreSQL отказывается инициализироваться в каталоге, где уже есть `lost+found`.

**Эксперименты:**

1. Посмотри порядок создания подов: `kubectl get pods -w`. Убедись, что `pg-1` стартует только после готовности `pg-0`.
2. Посмотри PVC: `kubectl get pvc` — их три, с именами `data-pg-0`, `data-pg-1`, `data-pg-2`.
3. Проверь per-pod DNS из отладочного пода:
   ```bash
   nslookup pg-0.pg.default.svc.cluster.local
   nslookup pg                       # headless вернёт ВСЕ IP
   ```
4. Запиши данные в `pg-0`, убей под, дождись пересоздания — данные должны быть на месте.
5. Отмасштабируй до 1 реплики, потом обратно до 3. Что произошло с PVC при уменьшении? (Спойлер: остались.) Что произошло при увеличении?
6. Удали StatefulSet целиком. Проверь `kubectl get pvc` — они живы. Пересоздай StatefulSet и убедись, что поды подхватили старые тома.

**Обязательный вывод в журнал:** три реплики Postgres в StatefulSet — это **три независимые базы**, а не кластер с репликацией. Убедись в этом опытом (запиши данные в pg-0, прочитай из pg-1). Понимание этого отличает инженера от человека, скопировавшего манифест.

---

## 🔧 Задание 3: DaemonSet (1 ч)

Напиши DaemonSet, который на каждой ноде собирает полезную информацию:

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: node-info
spec:
  selector:
    matchLabels: { app: node-info }
  template:
    metadata:
      labels: { app: node-info }
    spec:
      tolerations:
        - operator: Exists          # попадать на все ноды, включая taint'ованные
      containers:
        - name: info
          image: busybox:1.36
          command: ["sh", "-c"]
          args:
            - |
              while true; do
                echo "=== $(date) node=$NODE_NAME ==="
                df -h /host-root | tail -n +2
                sleep 60
              done
          env:
            - name: NODE_NAME
              valueFrom:
                fieldRef: { fieldPath: spec.nodeName }
          volumeMounts:
            - name: root
              mountPath: /host-root
              readOnly: true
      volumes:
        - name: root
          hostPath: { path: / }
```

Задачи:
1. Убедись, что подов ровно столько же, сколько нод.
2. Добавь новую ноду (или сними taint) — под появится автоматически.
3. Обрати внимание на использование `downwardAPI` (`fieldRef`) — так контейнер узнаёт имя своей ноды. Это пригодится на неделе 14 для node-exporter.
4. Ограничь DaemonSet только worker-нодами через `nodeSelector`.

---

## 🔧 Задание 4: Job и CronJob для своих задач (2 ч)

Это задание максимально близко к твоей текущей работе — используй реальные сценарии.

**Job — миграции БД:**

```yaml
apiVersion: batch/v1
kind: Job
metadata: { name: db-migrate }
spec:
  backoffLimit: 3
  activeDeadlineSeconds: 600
  ttlSecondsAfterFinished: 3600
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: migrate
          image: registry.lab/myservice:1.0.0
          command: ["alembic", "upgrade", "head"]
          envFrom:
            - secretRef: { name: app-secrets }
```

**CronJob — регулярная проверка дистрибутивов в Artifactory:**

```yaml
apiVersion: batch/v1
kind: CronJob
metadata: { name: artifact-check }
spec:
  schedule: "*/15 * * * *"
  timeZone: "Europe/Moscow"
  concurrencyPolicy: Forbid
  startingDeadlineSeconds: 120
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      backoffLimit: 2
      ttlSecondsAfterFinished: 1800
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: checker
              image: registry.lab/artifact-checker:1.0.0
              args: ["--repo", "dist-local", "--verify-checksums"]
```

Эксперименты:
1. Сделай задачу, которая падает всегда → посмотри, как отрабатывает `backoffLimit` и в каком состоянии остаётся Job.
2. Сравни поведение `restartPolicy: OnFailure` и `Never`: в первом случае перезапускается контейнер, во втором создаются новые поды. Где искать логи в каждом случае?
3. Сделай CronJob с задачей длиннее интервала запуска. Сравни `concurrencyPolicy: Allow` и `Forbid` — увидь наложение запусков.
4. Проверь `ttlSecondsAfterFinished`: без него поды копятся, с ним — исчезают.

⚠️ Для отладки: `kubectl create job --from=cronjob/artifact-check manual-run` — запуск CronJob вручную, не дожидаясь расписания. Полезнейшая команда.

---

## 🔧 Задание 5: собираем всё вместе (1.5 ч)

Финальная задача первого месяца. Один namespace `app`, в нём:

- **Deployment** твоего сервиса: 3 реплики, все три probes, requests/limits, preStop, конфиг из ConfigMap, секреты из Secret
- **Service** ClusterIP
- **StatefulSet** PostgreSQL с PVC
- **Job** миграций, который должен отработать **до** старта приложения
- **CronJob** периодической проверки
- **ResourceQuota** и **LimitRange** на namespace

Для порядка «сначала миграции, потом приложение» на этом этапе используй **init-контейнер**, который ждёт БД:

```yaml
initContainers:
  - name: wait-for-db
    image: busybox:1.36
    command: ['sh', '-c', 'until nc -z pg 5432; do echo waiting; sleep 2; done']
```

На неделе 10 ты заменишь это на Helm hook, а на неделе 13 — на ArgoCD sync waves. Полезно пройти все три способа и понимать разницу.

**Проверка:** снеси namespace целиком и разверни заново одной командой `kubectl apply -k .`. Всё должно подняться в правильном порядке без ручного вмешательства.

---

## 💥 Ломаем специально

1. Создай PVC с несуществующим `storageClassName` → вечный `Pending`. Найди причину в Events.
2. Попробуй смонтировать один RWO-том в поды на **разных** нодах → второй под зависнет в `ContainerCreating` с ошибкой `Multi-Attach`. Затем сделай так, чтобы оба пода попали на одну ноду, и убедись, что монтирование прошло. Это то самое отличие «одна нода ≠ один под».
3. Уменьши размер в PVC (например, с 2Gi до 1Gi) → получи отказ. Увеличь до 5Gi при `allowVolumeExpansion: true` → посмотри, как том вырастет.
4. Удали PVC, который используется работающим подом. Он не удалится сразу (finalizer `kubernetes.io/pvc-protection`) — разберись, что такое finalizers и когда объект реально исчезнет.
5. Задай StatefulSet без `serviceName` или с несуществующим headless-сервисом → поды поднимутся, но per-pod DNS работать не будет.

---

## ❓ Самопроверка

1. Зачем нужна связка PV + PVC, почему под не может обратиться к диску напрямую?
2. `reclaimPolicy: Delete` vs `Retain` — когда что выбирать?
3. Что даёт `volumeBindingMode: WaitForFirstConsumer` и какую проблему он решает?
4. RWO — это ограничение на ноду или на под? Как проверить?
5. Пять отличий StatefulSet от Deployment.
6. Почему StatefulSet требует headless-сервис?
7. Удалил StatefulSet — что стало с данными? Почему сделано именно так?
8. Три реплики Postgres в StatefulSet — это отказоустойчивый кластер? Обоснуй.
9. `backoffLimit` — это про количество или про время? В чём разница между `restartPolicy: OnFailure` и `Never` для Job?
10. `concurrencyPolicy: Allow` — в каком сценарии это выстрелит в ногу?
11. Зачем DaemonSet'у обычно нужны tolerations?
12. Что такое finalizer и почему объект может «зависнуть» в состоянии Terminating?

---

## 🔗 Ссылки

| Ресурс | Зачем |
|---|---|
| [Persistent Volumes](https://kubernetes.io/docs/concepts/storage/persistent-volumes/) | Главный документ недели, читать целиком |
| [Storage Classes](https://kubernetes.io/docs/concepts/storage/storage-classes/) | Параметры провижионинга |
| [StatefulSet Basics (туториал)](https://kubernetes.io/docs/tutorials/stateful-application/basic-stateful-set/) | Пошаговая практика |
| [StatefulSet концепт](https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/) | |
| [DaemonSet](https://kubernetes.io/docs/concepts/workloads/controllers/daemonset/) | |
| [Jobs](https://kubernetes.io/docs/concepts/workloads/controllers/job/) | Разделы про backoff и параллелизм |
| [CronJob](https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/) | |
| [local-path-provisioner](https://github.com/rancher/local-path-provisioner) | Что стоит за StorageClass в k3s |
| [CloudNativePG](https://cloudnative-pg.io/) | Как БД разворачивают в проде на самом деле |

---

## ✅ Чек-лист недели

- [ ] Понимаю связку PV → PVC → StorageClass, знаю, где физически лежат данные
- [ ] Проверил опытом `reclaimPolicy` Delete и Retain
- [ ] PostgreSQL как StatefulSet: стабильные имена, per-pod DNS, персональные PVC
- [ ] Убедился опытом, что три реплики StatefulSet — это три независимые БД
- [ ] Данные переживают удаление пода и удаление самого StatefulSet
- [ ] DaemonSet работает на всех нодах, использует downwardAPI
- [ ] Job миграций и CronJob проверки написаны, поведение `backoffLimit` и `concurrencyPolicy` проверено
- [ ] Весь стек разворачивается в чистом namespace одной командой
- [ ] Все 5 экспериментов «Ломаем специально» проделаны
- [ ] `notes/week-04.md` заполнен

---

## 🏁 Контрольная точка месяца 1

Прежде чем идти дальше, ответь себе честно:

- [ ] Могу рассказать путь `kubectl apply` вслух за 2 минуты
- [ ] Могу за 10 минут диагностировать под в Pending, ImagePullBackOff, CrashLoopBackOff
- [ ] Мой сервис обновляется под нагрузкой без потери запросов
- [ ] В репозитории 25+ осмысленных манифестов, которые я могу объяснить построчно
- [ ] Журнал `notes/` содержит 5 файлов с реальными разборами поломок

Если два и более пункта не закрыты — **потрать неделю на добор**, не переходи к сети. Второй месяц строится на первом, и пробелы здесь будут дорого стоить на неделях 5 и 8.
