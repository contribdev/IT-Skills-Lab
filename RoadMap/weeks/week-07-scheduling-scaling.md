# Неделя 7 — Планирование подов и масштабирование

**Цель недели:** управлять размещением подов и настроить автоматическое масштабирование, в том числе по внешним событиям.
**Время:** 10 часов (3 ч теории, 7 ч практики).

Эта неделя — прямая подготовка к неделе 22 (GPU-ноды: taints, tolerations, affinity) и к неделе 23 (KEDA для GPU-воркеров). Всё, что здесь освоишь, применишь на AI-инфраструктуре почти дословно.

---

## 📖 Теория

### 1. Как работает scheduler

Три фазы для каждого пода без `spec.nodeName`:

1. **Filtering (предикаты)** — отсеиваем неподходящие ноды: хватает ли ресурсов (по **requests**, не по фактическому потреблению), совместимы ли taints и tolerations, проходит ли nodeSelector/affinity, свободен ли hostPort, доступен ли нужный том в этой зоне.
2. **Scoring (приоритеты)** — оставшиеся ноды получают оценки: балансировка потребления ресурсов, `ImageLocality` (образ уже скачан на ноду — заметно ускоряет старт), affinity-предпочтения, spread по топологии.
3. **Binding** — записываем `spec.nodeName`.

⚠️ **Ключевое:** scheduler считает по **requests**, а не по реальному потреблению. Нода с 90% фактической загрузки, но низкими requests, будет считаться свободной. Отсюда переподписка и внезапные OOM. Это одна из главных причин, почему requests нужно ставить осмысленно (неделя 3).

⚠️ Второе: scheduler принимает решение **один раз**, при создании пода. Он не перемещает уже запущенные поды, даже если баланс кластера ухудшился. Для перебалансировки существует отдельный компонент — **descheduler**.

### 2. Способы влиять на размещение

**nodeSelector** — простейший, точное совпадение лейблов:

```yaml
nodeSelector:
  disktype: ssd
```

**Node affinity** — гибче, два типа:

```yaml
affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:      # жёсткое требование
      nodeSelectorTerms:
        - matchExpressions:
            - key: node-role.kubernetes.io/worker
              operator: Exists
    preferredDuringSchedulingIgnoredDuringExecution:     # предпочтение
      - weight: 100
        preference:
          matchExpressions:
            - key: disktype
              operator: In
              values: ["ssd"]
```

Расшифровка длинных имён: `requiredDuringScheduling` — обязательно при планировании; `IgnoredDuringExecution` — если лейбл ноды изменится потом, работающий под **не** выселят. (Вариант `RequiredDuringExecution` до сих пор не реализован.)

**Pod affinity / anti-affinity** — размещение относительно **других подов**:

```yaml
podAntiAffinity:
  requiredDuringSchedulingIgnoredDuringExecution:
    - labelSelector:
        matchLabels: { app.kubernetes.io/name: myservice }
      topologyKey: kubernetes.io/hostname     # "не более одного на ноду"
```

`topologyKey` определяет масштаб «рядом/не рядом»: `kubernetes.io/hostname` — нода, `topology.kubernetes.io/zone` — зона доступности.

⚠️ Жёсткий `requiredDuringScheduling` anti-affinity + реплик больше, чем нод = поды навсегда в Pending. Для большинства случаев правильнее `preferred`.

⚠️ Pod affinity вычислительно дорога: scheduler должен сопоставить под со всеми подами на всех нодах. На больших кластерах это заметно.

### 3. Taints и tolerations — обратная логика

nodeSelector/affinity — под выбирает ноду. Taint — **нода отталкивает** поды.

```bash
kubectl taint nodes gpu-1 nvidia.com/gpu=present:NoSchedule
```

Три эффекта:
- `NoSchedule` — новые поды без toleration не планируются
- `PreferNoSchedule` — мягкий вариант
- `NoExecute` — новые не планируются **и уже работающие выселяются**

Toleration в поде:

```yaml
tolerations:
  - key: nvidia.com/gpu
    operator: Exists
    effect: NoSchedule
```

⚠️ **Важнейшее для понимания:** toleration **не притягивает** под к ноде, она лишь снимает запрет. Под с toleration к GPU-ноде может спокойно попасть на обычную ноду. Чтобы гарантированно попасть на GPU-ноду, нужна связка **taint (чтобы чужие не пришли) + nodeAffinity/nodeSelector (чтобы свои пришли)**. Это ровно то, что ты будешь настраивать на неделе 22.

Kubernetes сам ставит taints при проблемах: `node.kubernetes.io/not-ready`, `unreachable`, `memory-pressure`, `disk-pressure`. И сам добавляет подам toleration к `not-ready`/`unreachable` с `tolerationSeconds: 300` — вот откуда те самые 5 минут до выселения при отказе ноды (эксперимент с недели 2).

### 4. Topology spread constraints

Современная замена «anti-affinity для равномерности»:

```yaml
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: topology.kubernetes.io/zone
    whenUnsatisfiable: ScheduleAnyway        # или DoNotSchedule
    labelSelector:
      matchLabels: { app.kubernetes.io/name: myservice }
```

`maxSkew` — максимально допустимая разница в количестве подов между топологическими доменами. Гибче anti-affinity: позволяет «примерно поровну», а не «строго по одному».

### 5. PriorityClass и preemption

```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata: { name: high-priority }
value: 1000000
globalDefault: false
preemptionPolicy: PreemptLowerPriority
```

Если высокоприоритетный под не влезает, scheduler **вытесняет** (preempt) низкоприоритетные, освобождая место. Практическое применение: критичные системные компоненты, а также «batch-нагрузка, которую можно потеснить» — типичный сценарий для ML-обучения на GPU.

### 6. PodDisruptionBudget

Защита от **добровольных** нарушений (drain ноды, обновление кластера, автоскейлер). От отказа железа PDB не спасает.

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata: { name: myservice }
spec:
  minAvailable: 2          # или maxUnavailable: 1
  selector:
    matchLabels: { app.kubernetes.io/name: myservice }
```

⚠️ Ловушка: `minAvailable: 2` при `replicas: 2` заблокирует drain **навсегда** — освободить ноду будет невозможно. Правило: PDB должен оставлять запас (`minAvailable` строго меньше `replicas`), либо используй `maxUnavailable`.

### 7. Автомасштабирование: три уровня

| Механизм | Что масштабирует | Комментарий |
|---|---|---|
| **HPA** | количество реплик | По CPU/памяти или произвольным метрикам |
| **VPA** | requests/limits пода | Пересоздаёт под. Конфликтует с HPA по тем же метрикам |
| **Cluster Autoscaler** / Karpenter | количество нод | Только в облаке |
| **KEDA** | реплики по внешним событиям | Надстройка над HPA, умеет scale-to-zero |

**HPA** требует metrics-server. Формула проста:

```
желаемые_реплики = ceil( текущие × (текущая_метрика / целевая_метрика) )
```

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
spec:
  scaleTargetRef: { apiVersion: apps/v1, kind: Deployment, name: myservice }
  minReplicas: 2
  maxReplicas: 20
  metrics:
    - type: Resource
      resource:
        name: cpu
        target: { type: Utilization, averageUtilization: 70 }
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300     # защита от «дребезга»
      policies:
        - type: Percent
          value: 50
          periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
        - type: Percent
          value: 100
          periodSeconds: 15
```

⚠️ `averageUtilization` считается **от requests**, а не от лимитов и не от ёмкости ноды. Не задал requests — HPA по CPU работать не будет вовсе.

⚠️ HPA по CPU плохо подходит для нагрузок, где узкое место не в процессоре: очереди, IO-bound сервисы, LLM-инференс (там определяющий фактор — глубина очереди запросов и загрузка GPU). Отсюда — KEDA.

**KEDA** — операторы-скейлеры для десятков источников: Redis, RabbitMQ, Kafka, Prometheus, cron, S3 и т.д. Главное преимущество — **scale-to-zero**.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
spec:
  scaleTargetRef: { name: worker }
  minReplicaCount: 0
  maxReplicaCount: 10
  cooldownPeriod: 300
  triggers:
    - type: redis
      metadata:
        address: redis:6379
        listName: tasks
        listLength: "5"        # 1 реплика на каждые 5 задач в очереди
```

---

## 🔧 Задание 1: управляем размещением (2 ч)

1. Разметь ноды осмысленно:
   ```bash
   kubectl label node node-1 disktype=ssd tier=general
   kubectl label node node-2 disktype=hdd tier=general
   ```

2. Отправь под на конкретную ноду через nodeSelector, потом переделай на nodeAffinity с `preferred` — увидь разницу в поведении, когда подходящей ноды нет.

3. **Anti-affinity:** настрой «не более одной реплики на ноду» жёстко (`required`), поставь `replicas: 3` при двух рабочих нодах. Один под зависнет в Pending — прочитай точную причину в `describe`. Затем переключи на `preferred` и убедись, что все три поднялись.

4. **Topology spread:** размести 6 реплик равномерно по нодам через `topologySpreadConstraints` с `maxSkew: 1`. Убей одну ноду и посмотри, как перераспределятся поды.

5. **Taints:** поставь taint на node-2, убедись, что новые поды туда не идут. Затем поставь `NoExecute` и увидь, как уже работающие поды выселяются. Верни всё назад.

6. **Связка taint + affinity** (репетиция недели 22): сделай так, чтобы на node-2 попадали **только** поды помеченного типа и **все** такие поды попадали именно туда. Убедись, что одной toleration недостаточно.

---

## 🔧 Задание 2: HPA под нагрузкой (2 ч)

1. Установи metrics-server (в k3s обычно уже есть):
   ```bash
   kubectl top nodes && kubectl top pods
   ```

2. Настрой HPA по CPU с `behavior` из теории.

3. Нагрузи через k6 ступенчато:
   ```javascript
   export const options = {
     stages: [
       { duration: '2m', target: 50 },
       { duration: '3m', target: 200 },
       { duration: '2m', target: 200 },
       { duration: '3m', target: 0 },
     ],
   };
   ```

4. Наблюдай в трёх терминалах: `kubectl get hpa -w`, `kubectl get pods -w`, `kubectl top pods`.

5. **Замерь и запиши:**
   - через сколько секунд после роста нагрузки появился новый под
   - через сколько он стал `Ready` (сюда входит скачивание образа и startup probe)
   - через сколько после спада началось уменьшение (должно совпасть со `stabilizationWindowSeconds`)

6. Поэкспериментируй: убери `behavior` и увидь «дребезг» (флаппинг) при колеблющейся нагрузке. Верни и объясни разницу в журнале.

7. Убери `requests.cpu` — HPA сломается. Прочитай, что покажет `kubectl describe hpa`.

---

## 🔧 Задание 3: KEDA и очередь (2.5 ч)

Задание, максимально близкое к твоей рабочей области: воркер, обрабатывающий задачи проверки дистрибутивов.

1. Разверни Redis и напиши воркер на Python, который берёт задачи из списка (`BLPOP`) и обрабатывает их с задержкой в несколько секунд.

2. Установи KEDA:
   ```bash
   helm repo add kedacore https://kedacore.github.io/charts
   helm install keda kedacore/keda -n keda --create-namespace
   ```

3. Настрой `ScaledObject` с `minReplicaCount: 0`.

4. Эксперименты:
   - При пустой очереди подов **ноль**. Убедись.
   - Закинь 100 задач → посмотри, за сколько секунд поднимутся воркеры и сколько их будет.
   - Закинь 1000 задач → должен упереться в `maxReplicaCount`.
   - Дождись опустошения очереди → через `cooldownPeriod` реплики уйдут в ноль.

5. Посмотри, что KEDA создала под капотом: `kubectl get hpa` — там будет HPA с внешней метрикой. Пойми, что KEDA не заменяет HPA, а питает его метриками.

6. Добавь второй триггер — по cron (например, держать минимум 2 реплики в рабочие часы). KEDA умеет комбинировать триггеры.

Это задание — прямой прототип того, что ты будешь делать на неделе 23 для GPU-воркеров ComfyUI.

---

## 🔧 Задание 4: PDB и обслуживание ноды (1.5 ч)

1. Создай PDB с `minAvailable: 2` для Deployment с 3 репликами.

2. Под нагрузкой (k6 в фоне) сделай:
   ```bash
   kubectl cordon node-1
   kubectl drain node-1 --ignore-daemonsets --delete-emptydir-data
   ```
   Наблюдай: drain выселяет поды **постепенно**, соблюдая PDB. Запросы не теряются (если ты корректно сделал неделю 3).

3. **Ловушка:** поставь `minAvailable: 3` при `replicas: 3` и повтори drain. Он зависнет навсегда. Разберись, как это выглядит в выводе, и почему это опасно в проде при обновлении кластера.

4. Верни ноду: `kubectl uncordon node-1`. Обрати внимание — поды **не вернутся** сами. Это то самое «scheduler не перебалансирует».

5. Опционально: разверни **descheduler** и посмотри, как он перераспределяет поды после возврата ноды.

---

## 💥 Ломаем специально

1. Поставь requests больше, чем есть на любой ноде → вечный Pending. Прочитай сообщение scheduler'а в Events — оно очень информативное, научись его читать.
2. Жёсткий anti-affinity + реплик больше числа нод → часть подов навсегда в Pending.
3. Поставь `NoExecute` taint на ноду, где живёт вся твоя нагрузка → мгновенное выселение всего. Посмотри, куда всё переехало и сколько это заняло.
4. Создай PriorityClass и запусти высокоприоритетный под на заполненном кластере → увидь preemption: кого-то выселят. Найди событие `Preempted` в Events жертвы.
5. Настрой HPA с `maxReplicas` больше, чем кластер физически может вместить → поды в Pending, HPA рапортует об успехе. Пойми, почему HPA «не знает» о ёмкости кластера и что это значит для облака (там нужен Cluster Autoscaler).
6. Настрой VPA в режиме `Auto` рядом с HPA по CPU → получи конфликт (VPA меняет requests, HPA считает от requests). Разберись, почему их не комбинируют по одной метрике.

---

## ❓ Самопроверка

1. Три фазы работы scheduler.
2. Scheduler считает по requests или по фактическому потреблению? Какие проблемы из этого следуют?
3. Перемещает ли scheduler уже запущенные поды? Что делать, если баланс кластера ухудшился?
4. Расшифруй `requiredDuringSchedulingIgnoredDuringExecution`.
5. Toleration гарантирует, что под попадёт на taint'ованную ноду? Как гарантировать?
6. Три эффекта taint. Какой выселяет работающие поды?
7. Откуда берутся 5 минут задержки перед выселением подов с отказавшей ноды?
8. `topologyKey` — что это и какие значения типичны?
9. От чего защищает PDB, а от чего нет?
10. `minAvailable: 3` при `replicas: 3` — что произойдёт при drain?
11. От какой величины HPA считает `averageUtilization`?
12. Почему HPA по CPU плохо работает для очередей и LLM-инференса?
13. Что KEDA создаёт под капотом и в чём её главное преимущество над голым HPA?
14. Почему VPA в режиме Auto конфликтует с HPA?

---

## 🔗 Ссылки

| Ресурс | Зачем |
|---|---|
| [Assigning Pods to Nodes](https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/) | affinity целиком |
| [Taints and Tolerations](https://kubernetes.io/docs/concepts/scheduling-eviction/taint-and-toleration/) | |
| [Pod Topology Spread Constraints](https://kubernetes.io/docs/concepts/scheduling-eviction/topology-spread-constraints/) | |
| [Pod Priority and Preemption](https://kubernetes.io/docs/concepts/scheduling-eviction/pod-priority-preemption/) | |
| [PodDisruptionBudget](https://kubernetes.io/docs/tasks/run-application/configure-pdb/) | |
| [HPA Walkthrough](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale-walkthrough/) | Практика |
| [HPA: behavior](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/#configurable-scaling-behavior) | Управление скоростью |
| [KEDA Scalers](https://keda.sh/docs/latest/scalers/) | Каталог триггеров |
| [descheduler](https://github.com/kubernetes-sigs/descheduler) | Перебалансировка |
| [Karpenter](https://karpenter.sh/) | Современная альтернатива Cluster Autoscaler (обзорно) |

---

## ✅ Чек-лист недели

- [ ] Управляю размещением через nodeSelector, nodeAffinity, pod anti-affinity, topology spread
- [ ] Понял на опыте: toleration ≠ притяжение; настроил связку taint + affinity
- [ ] Воспроизвёл выселение подов через `NoExecute`
- [ ] HPA работает под ступенчатой нагрузкой, замерил задержки масштабирования вверх и вниз
- [ ] Увидел эффект `stabilizationWindowSeconds` и «дребезг» без него
- [ ] KEDA масштабирует воркер по длине очереди Redis, включая scale-to-zero
- [ ] Разобрался, что KEDA питает обычный HPA внешними метриками
- [ ] PDB защищает сервис при drain; воспроизвёл ловушку с заблокированным drain
- [ ] Наблюдал preemption с PriorityClass
- [ ] Все 6 экспериментов «Ломаем специально» проделаны
- [ ] `notes/week-07.md` заполнен
