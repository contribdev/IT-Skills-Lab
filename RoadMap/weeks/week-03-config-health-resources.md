# Неделя 3 — Конфигурация, здоровье, ресурсы

**Цель недели:** превратить «учебные» манифесты в продовые. После этой недели твой сервис переживает обновление без потери запросов.
**Время:** 10 часов (3 ч теории, 7 ч практики).

Три темы этой недели — **probes, requests/limits и graceful shutdown** — дают больше половины вопросов на собеседованиях по Kubernetes и больше половины реальных инцидентов в проде.

---

## 📖 Теория

### 1. ConfigMap

Хранилище неконфиденциальной конфигурации. Три способа доставки в под:

```yaml
# a) отдельные переменные
env:
  - name: LOG_LEVEL
    valueFrom:
      configMapKeyRef: { name: app-config, key: log_level }

# b) все ключи разом
envFrom:
  - configMapRef: { name: app-config }

# c) как файлы (каждый ключ — файл)
volumeMounts:
  - name: config
    mountPath: /etc/app
volumes:
  - name: config
    configMap: { name: app-config }
```

**Критическая разница между (a/b) и (c):**

| | Обновление на лету |
|---|---|
| env | ❌ никогда. Переменные окружения процесса задаются при старте |
| volume | ✅ файл в подах обновится (задержка ~1 мин), но **приложение должно уметь перечитать файл** |

Отсюда стандартный приём — **чексумма конфига в аннотации пода**, чтобы изменение ConfigMap приводило к rolling update:

```yaml
template:
  metadata:
    annotations:
      checksum/config: "{{ sha256sum (toYaml .Values.config) }}"   # синтаксис Helm, неделя 9
```

Ограничение: ConfigMap хранится в etcd, максимум **1 МБ**. Большие файлы — не сюда.

### 2. Secret

Ровно тот же механизм, но:
- значения в **base64** (это кодирование, **не шифрование** — повторяй это на собеседовании)
- по умолчанию в etcd лежат **в открытом виде**, если не включён encryption at rest
- любой, у кого есть RBAC-права на чтение секретов в namespace, читает их полностью
- монтируются в `tmpfs`, а не на диск ноды

Типы: `Opaque` (общий), `kubernetes.io/dockerconfigjson` (доступ к registry), `kubernetes.io/tls` (сертификаты).

Вывод, к которому ты придёшь на неделе 6: секреты в проде хранят **вне кластера** (Vault, облачный secret manager) и подтягивают через External Secrets Operator. А в git секреты кладут только зашифрованными (SOPS).

⚠️ `kubectl describe secret` не покажет значения, а `kubectl get secret -o yaml` покажет. Разница на собеседовании звучит хорошо.

### 3. Probes — самая важная тема недели

Три пробы, у каждой своя роль. **Путаница между ними — топ-1 причина странного поведения приложений в Kubernetes.**

| Проба | Вопрос, на который отвечает | Что делает при провале |
|---|---|---|
| **startup** | «Приложение ещё запускается?» | Блокирует остальные пробы. При исчерпании попыток — рестарт контейнера |
| **liveness** | «Приложение живо или зависло?» | **Перезапускает контейнер** |
| **readiness** | «Готово принимать трафик?» | **Убирает под из EndpointSlice.** Контейнер НЕ перезапускается |

```yaml
startupProbe:                 # для медленного старта (JVM, загрузка модели)
  httpGet: { path: /healthz, port: http }
  failureThreshold: 30
  periodSeconds: 10           # даём до 300 секунд на старт

livenessProbe:
  httpGet: { path: /healthz, port: http }
  periodSeconds: 10
  timeoutSeconds: 2
  failureThreshold: 3

readinessProbe:
  httpGet: { path: /readyz, port: http }
  periodSeconds: 5
  timeoutSeconds: 2
  failureThreshold: 2
```

**Правила, за которые платят деньги:**

1. **Liveness должна быть максимально тупой.** Только «процесс не завис»: вернуть 200 без обращения к БД, кэшу и внешним сервисам.
2. **Readiness может проверять зависимости.** БД недоступна → под не готов → трафик не идёт → но контейнер не перезапускается.
3. ⚠️ **Никогда не проверяй БД в liveness.** Классический каскадный отказ: БД подтормозила → liveness упала на всех подах разом → Kubernetes перезапустил весь сервис → нагрузка на БД от переподключений выросла → всё легло окончательно. Это разбирают на собеседованиях уровня Senior.
4. Liveness должна быть дешёвой: она выполняется на каждом поде каждые N секунд вечно.
5. Для медленного старта — **startupProbe**, а не раздутый `initialDelaySeconds` у liveness.

Типы проб: `httpGet`, `tcpSocket`, `exec`, `grpc`. `exec` — самая дорогая (форк процесса на каждую проверку), не злоупотребляй.

### 4. Requests, limits и QoS

**Request** — то, что резервируется. Именно по нему **scheduler** решает, влезет ли под на ноду.
**Limit** — потолок. Его применяет kubelet через cgroups.

| Ресурс | Превышение limit |
|---|---|
| **CPU** | Троттлинг — процесс просто замедляется. Контейнер не убивают. Компрессируемый ресурс |
| **Memory** | **OOMKilled** — контейнер убивают мгновенно. Некомпрессируемый ресурс |

**QoS-классы** (назначаются автоматически, определяют порядок выселения при нехватке памяти на ноде):

| Класс | Условие | Выселяется |
|---|---|---|
| **Guaranteed** | requests == limits для всех ресурсов всех контейнеров | последним |
| **Burstable** | requests заданы, но меньше limits | вторым |
| **BestEffort** | ничего не задано | первым |

**Практические выводы:**

- CPU limit часто **вреден**. Приложение троттлится, даже когда на ноде свободный CPU. Распространённая продовая практика: задавать CPU request и **не задавать** CPU limit.
- Memory limit **обязателен всегда**. Без него утечка в одном поде положит всю ноду.
- Для критичных сервисов — `Guaranteed` (requests == limits по памяти).
- Слишком высокие requests → поды не влезают на ноды, кластер стоит полупустой и дорогой. Это тема FinOps.

Единицы:
- CPU: `1` = одно ядро, `500m` = 0.5 ядра
- Память: `Mi`/`Gi` (степени 1024), `M`/`G` (степени 1000). `1Gi ≠ 1G` — на CKA на этом ловят

### 5. Graceful shutdown: полная последовательность

Что происходит при `kubectl delete pod` (или при rolling update):

1. Под помечается `Terminating`, ставится `deletionTimestamp`.
2. **Параллельно и асинхронно** запускаются две вещи:
   - endpoints controller убирает IP пода из EndpointSlice → kube-proxy на всех нодах обновляет правила
   - kubelet выполняет `preStop` hook, затем шлёт **SIGTERM** главному процессу
3. Ждём `terminationGracePeriodSeconds` (по умолчанию 30).
4. Если процесс не вышел — **SIGKILL**.

⚠️ **Ключевая гонка:** шаг 2 выполняется параллельно. Обновление правил iptables на десятках нод занимает время, и запросы продолжают приходить в под, который уже получил SIGTERM. Отсюда — 502-е при деплое.

**Стандартное решение** — пауза перед SIGTERM:

```yaml
lifecycle:
  preStop:
    exec:
      command: ["sh", "-c", "sleep 5"]
terminationGracePeriodSeconds: 30
```

Пять секунд достаточно, чтобы правила разъехались по кластеру. Приложение продолжает обслуживать запросы это время, потом получает SIGTERM и корректно дренирует.

⚠️ Обрати внимание: `terminationGracePeriodSeconds` включает в себя время preStop. Если preStop спит 25 секунд, приложению останется 5.

### 6. Namespace, ResourceQuota, LimitRange

- **Namespace** — логическая группировка + граница для RBAC, квот и сетевых политик. Namespaced объекты: поды, сервисы, секреты. Cluster-scoped: ноды, PV, StorageClass, ClusterRole.
- **ResourceQuota** — потолок на namespace (суммарные CPU/память, количество объектов). ⚠️ Если в namespace есть ResourceQuota на CPU/память, поды **без** requests/limits создаваться не будут вовсе.
- **LimitRange** — значения по умолчанию и границы для отдельных контейнеров. Решает проблему выше, подставляя дефолты.

---

## 🔧 Задание 1: выносим конфигурацию (1.5 ч)

1. Вынеси всю конфигурацию сервиса в ConfigMap, секреты (токены Jira/Artifactory, пароль БД) — в Secret.
2. Сделай две доставки: часть через `envFrom`, часть — файлом через volume.
3. Проверь опытом:
   ```bash
   kubectl edit configmap app-config      # поменяй значение
   kubectl exec deploy/myservice -- env | grep LOG_LEVEL         # НЕ изменилось
   kubectl exec deploy/myservice -- cat /etc/app/log_level       # изменилось (через ~60 сек)
   ```
4. Реализуй временный обходной приём: аннотация с хешем конфига, обновляемая вручную:
   ```bash
   kubectl patch deployment myservice -p \
     "{\"spec\":{\"template\":{\"metadata\":{\"annotations\":{\"config-hash\":\"$(date +%s)\"}}}}}"
   ```
   На неделе 9 это станет одной строкой в Helm-шаблоне.

5. Посмотри, где секрет лежит на самом деле:
   ```bash
   kubectl get secret app-secrets -o jsonpath='{.data.token}' | base64 -d
   ```
   Осознай, насколько это «не защита».

---

## 🔧 Задание 2: probes по-настоящему (2 ч)

Добавь в свой сервис **два разных** эндпоинта:

```python
@app.get("/healthz")           # liveness — тупая проверка
async def healthz():
    return {"status": "ok"}

@app.get("/readyz")            # readiness — проверка зависимостей
async def readyz():
    if not await db_ping():
        raise HTTPException(status_code=503, detail="db unavailable")
    if not await artifactory_reachable():
        raise HTTPException(status_code=503, detail="artifactory unavailable")
    return {"status": "ready"}
```

Добавь также «рубильник» для экспериментов:

```python
_ready = True

@app.post("/debug/toggle-ready")
async def toggle():
    global _ready
    _ready = not _ready
    return {"ready": _ready}
```

**Эксперименты (обязательно все три):**

1. Выключи readiness через рубильник на одном поде:
   ```bash
   kubectl get endpointslices -w        # IP пода исчезает
   kubectl get pods                     # READY 0/1, но RESTARTS = 0
   ```
   Ключевой вывод: readiness **не перезапускает** контейнер.

2. Сломай liveness (сделай, чтобы `/healthz` отдавал 500) → контейнер перезапускается, `RESTARTS` растёт.

3. Смоделируй медленный старт (`sleep 60` перед стартом приложения) **без** startupProbe → под попадёт в цикл перезапусков, потому что liveness убьёт его раньше, чем он поднимется. Затем добавь startupProbe и убедись, что проблема ушла. Это очень наглядное упражнение.

---

## 🔧 Задание 3: ресурсы и QoS (1.5 ч)

1. Создай три пода с разными настройками и проверь классы:
   ```bash
   kubectl get pod <name> -o jsonpath='{.status.qosClass}'
   ```
   Добейся всех трёх: Guaranteed, Burstable, BestEffort.

2. **Поймай OOMKilled.** Поставь `limits.memory: 64Mi` приложению, которому нужно больше:
   ```bash
   kubectl describe pod <name>
   # Last State: Terminated, Reason: OOMKilled, Exit Code: 137
   ```
   Запомни код 137 (128 + 9 = SIGKILL).

3. **Поймай троттлинг.** Поставь `limits.cpu: 100m`, нагрузи CPU-интенсивной задачей, посмотри:
   ```bash
   kubectl exec <pod> -- cat /sys/fs/cgroup/cpu.stat | grep throttled
   ```
   Значение `nr_throttled` растёт — вот он, троттлинг. На неделе 14 ты выведешь это в Grafana.

4. Посчитай осмысленные requests для своего сервиса: сними реальное потребление под нагрузкой (`kubectl top pod`, нужен metrics-server) и задай requests с запасом ~20–30%.

---

## 🔧 Задание 4: ноль потерянных запросов (2 ч)

Главное задание недели. Цель: **rolling update без единого не-200 ответа.**

1. Нагрузи сервис (k6 или простой цикл с curl), запусти обновление образа, посчитай ошибки. Скорее всего, они будут — это результат недели 2.
2. Добавляй по одному и замеряй эффект каждого шага:
   - корректная обработка SIGTERM в приложении (сделано на неделе 1)
   - `readinessProbe`
   - `preStop: sleep 5`
   - `terminationGracePeriodSeconds: 30`
   - `maxUnavailable: 0`
3. Зафиксируй в журнале таблицу: «конфигурация → количество ошибок». Это готовый материал для статьи на неделе 25 и отличная история для собеседования.

Скрипт нагрузки на k6:

```javascript
import http from 'k6/http';
import { check } from 'k6';

export const options = { vus: 20, duration: '3m' };

export default function () {
  const res = http.get('http://myservice.lab/');
  check(res, { 'status 200': (r) => r.status === 200 });
}
```

---

## 🔧 Задание 5: квоты (1 ч)

```yaml
apiVersion: v1
kind: ResourceQuota
metadata: { name: dev-quota, namespace: dev }
spec:
  hard:
    requests.cpu: "2"
    requests.memory: 4Gi
    limits.cpu: "4"
    limits.memory: 8Gi
    pods: "20"
    persistentvolumeclaims: "5"
---
apiVersion: v1
kind: LimitRange
metadata: { name: dev-limits, namespace: dev }
spec:
  limits:
    - type: Container
      default:        { cpu: 500m, memory: 512Mi }
      defaultRequest: { cpu: 100m, memory: 128Mi }
      max:            { cpu: "2",  memory: 2Gi }
```

Эксперименты:
1. Попробуй превысить квоту — прочитай текст ошибки внимательно.
2. Удали LimitRange и создай под **без** requests в namespace с квотой → получишь отказ. Пойми, почему.
3. `kubectl describe quota -n dev` — посмотри текущее потребление.

---

## 💥 Ломаем специально

1. Поставь `livenessProbe` с проверкой БД, затем «положи» БД. Наблюдай, как перезапускается весь сервис, хотя проблема не в нём. **Это упражнение стоит целой лекции.**
2. Задай `initialDelaySeconds: 0` и `failureThreshold: 1` для liveness → получи бесконечный CrashLoopBackOff на медленно стартующем приложении.
3. Сделай `terminationGracePeriodSeconds: 1` и убедись, что запросы теряются при деплое.
4. Смонтируй в под несуществующий ConfigMap → под зависнет в `ContainerCreating`. Найди причину через `describe`.
5. Задай `requests.memory` больше, чем есть на любой ноде → вечный `Pending` с понятным сообщением в Events.

---

## ❓ Самопроверка

1. Liveness, readiness, startup — назначение каждой и что происходит при провале.
2. Почему нельзя проверять БД в liveness-пробе? Опиши сценарий каскадного отказа.
3. Три QoS-класса, условия назначения, порядок выселения.
4. Что случится при превышении CPU limit? А memory limit? Почему поведение разное?
5. Зачем нужен `preStop: sleep`, если приложение и так обрабатывает SIGTERM?
6. Изменил ConfigMap — что произойдёт с подами? Ответь отдельно для env и для volume.
7. `1Gi` и `1G` — это одно и то же?
8. Почему в namespace с ResourceQuota поды без requests не создаются?
9. Exit code 137 — что это значит?
10. Почему CPU limit часто советуют не ставить, а memory limit — ставить обязательно?

---

## 🔗 Ссылки

| Ресурс | Зачем |
|---|---|
| [Configure Probes](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/) | Основной документ недели |
| [Resource Management](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/) | requests/limits |
| [Pod QoS](https://kubernetes.io/docs/concepts/workloads/pods/pod-qos/) | Классы и выселение |
| [Pod Lifecycle](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/) | Раздел про termination |
| [learnk8s: Graceful shutdown](https://learnk8s.io/graceful-shutdown) | Разбор гонки с EndpointSlice — читать обязательно |
| [ConfigMaps](https://kubernetes.io/docs/concepts/configuration/configmap/) | |
| [Secrets](https://kubernetes.io/docs/concepts/configuration/secret/) | Раздел про риски |
| [k6](https://k6.io/docs/) | Нагрузочное тестирование |

---

## ✅ Чек-лист недели

- [ ] Конфигурация в ConfigMap, секреты в Secret; понимаю разницу env vs volume при обновлении
- [ ] Раздельные `/healthz` и `/readyz`, все три пробы настроены осмысленно
- [ ] Проверил опытом: readiness выводит из EndpointSlice, liveness перезапускает контейнер
- [ ] Воспроизвёл проблему медленного старта и решил её через startupProbe
- [ ] Поймал OOMKilled (код 137) и CPU-троттлинг, знаю, где смотреть
- [ ] **Rolling update под нагрузкой без единой ошибки**, таблица «конфигурация → ошибки» в журнале
- [ ] ResourceQuota + LimitRange настроены, поведение при превышении проверено
- [ ] Все 5 экспериментов «Ломаем специально» проделаны
- [ ] Манифесты обновлены в репозитории, `notes/week-03.md` заполнен
