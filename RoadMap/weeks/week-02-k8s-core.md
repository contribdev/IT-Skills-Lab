# Неделя 2 — Кластер, kubectl, базовые объекты

**Цель недели:** понять, из чего состоит кластер и что происходит внутри при применении манифеста; развернуть свой сервис.
**Время:** 10–11 часов (3.5 ч теории, 7 ч практики).

Главный результат недели — не «умею писать Deployment», а **умение рассказать путь `kubectl apply` по шагам**. Этот вопрос задают почти на каждом собеседовании, и по глубине ответа сразу видно уровень.

---

## 📖 Теория

### 1. Архитектура кластера

**Control plane:**

| Компонент | Ответственность |
|---|---|
| **kube-apiserver** | Единственная точка входа. Аутентификация, авторизация, admission, валидация, запись в etcd. Больше **никто** не пишет в etcd напрямую |
| **etcd** | Распределённое key-value хранилище. Всё состояние кластера. Raft, кворум `(n/2)+1` — отсюда нечётное число членов |
| **kube-scheduler** | Выбирает ноду для подов, у которых `spec.nodeName` пуст. Только выбирает — не запускает |
| **kube-controller-manager** | Набор контроллеров (deployment, replicaset, node, endpoint, job...). Каждый крутит цикл сверки «желаемое vs фактическое» |
| **cloud-controller-manager** | Интеграция с облаком: LoadBalancer, ноды, роуты |

**На каждой ноде:**

| Компонент | Ответственность |
|---|---|
| **kubelet** | Агент. Следит за подами, назначенными **его** ноде. Запускает контейнеры через CRI, выполняет probes, репортит статус |
| **kube-proxy** | Программирует правила iptables/IPVS для Service |
| **container runtime** | containerd / CRI-O. Собственно запуск контейнеров |

### 2. Что происходит при `kubectl apply -f deployment.yaml`

**Заучи эту цепочку.** Разбери её вслух минимум трижды за неделю.

1. **kubectl** читает YAML, находит kubeconfig, формирует HTTP-запрос к API server (`POST /apis/apps/v1/namespaces/default/deployments`).
2. **Аутентификация** — по клиентскому сертификату, токену или OIDC. API server выясняет, *кто* ты.
3. **Авторизация (RBAC)** — можно ли *этому* субъекту создавать Deployment в *этом* namespace.
4. **Admission controllers:**
   - *mutating* — изменяют объект (подставляют defaults, инжектят sidecar, добавляют ServiceAccount-токен)
   - валидация схемы
   - *validating* — принимают или отклоняют (ResourceQuota, PodSecurity, твои Kyverno-политики с недели 17)
5. **Запись в etcd.** С этого момента объект существует. API server отвечает `201`. `kubectl` завершился — а работа только начинается.
6. **Deployment controller** (в controller-manager) видит через watch новый Deployment → создаёт **ReplicaSet**.
7. **ReplicaSet controller** видит RS с `replicas: 3` и нулём подов → создаёт 3 объекта **Pod** с пустым `spec.nodeName`.
8. **Scheduler** видит поды без ноды → фаза **filtering** (какие ноды вообще подходят: ресурсы, taints, affinity, порты) → фаза **scoring** (какая лучше) → пишет `spec.nodeName` через binding-подобъект.
9. **kubelet** на выбранной ноде видит пода, назначенного ему → вызывает CNI (настроить сеть), CSI (примонтировать тома), CRI (скачать образ, запустить контейнеры).
10. **kubelet** обновляет `status` пода в API server. Probes начинают работать; при успешном readiness **endpoints controller** добавляет IP пода в EndpointSlice сервиса — и трафик пошёл.

Ключевая мысль, которую нужно проговорить на собеседовании: **никакой компонент не командует другим напрямую.** Все общаются через API server и работают по модели «наблюдаю за состоянием — привожу к желаемому». Это и есть *reconciliation loop*, и именно поэтому Kubernetes самовосстанавливается.

### 3. Pod

Под — минимальная единица планирования. Один или несколько контейнеров, которые:
- разделяют **network namespace** (общий IP, общаются через `localhost`, не могут занять один порт)
- могут разделять volumes
- всегда на одной ноде, живут и умирают вместе

Внутри есть скрытый **pause-контейнер** — он держит namespaces, пока остальные контейнеры перезапускаются.

**init-контейнеры** выполняются по очереди до старта основных, каждый должен завершиться успешно. Применение: ожидание БД, миграции, скачивание конфигов/весов моделей (пригодится на неделе 22 для vLLM).

**Sidecar** — вспомогательный контейнер рядом с основным (сбор логов, прокси, синхронизация). С Kubernetes 1.29 есть нативные sidecar-контейнеры — это init-контейнер с `restartPolicy: Always`.

Под **никогда не «переезжает»**. Он умирает на одной ноде и создаётся заново на другой — с новым именем и новым IP. Отсюда: нельзя завязываться на IP пода, для этого есть Service.

### 4. Deployment → ReplicaSet → Pod

Deployment управляет ReplicaSet'ами, ReplicaSet — подами. При обновлении образа Deployment **создаёт новый ReplicaSet** и постепенно перекладывает реплики.

```yaml
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxSurge: 1          # сколько подов сверх желаемого можно создать
    maxUnavailable: 0    # сколько можно недосчитаться
```

`maxUnavailable: 0` + `maxSurge: 1` = обновление без просадки мощности (медленнее, но безопаснее). Для stateful-нагрузок и БД используется `Recreate` — сначала убить все, потом поднять новые.

Старые ReplicaSet'ы сохраняются (`revisionHistoryLimit`, по умолчанию 10) — именно за счёт них работает `kubectl rollout undo`.

⚠️ **Частое заблуждение:** «rollout undo откатывает данные». Нет. Он откатывает только спецификацию подов. Миграции БД он не отменит — это важно помнить при проектировании релизов (актуально для твоей текущей работы).

### 5. Labels и selectors

Labels — это то, чем в Kubernetes всё связано со всем. Deployment находит свои поды по селектору, Service находит поды по селектору, NetworkPolicy выбирает поды по селектору.

⚠️ `spec.selector` у Deployment **иммутабелен** после создания. Ошибся — только пересоздавать.

Используй [рекомендованные лейблы](https://kubernetes.io/docs/concepts/overview/working-with-objects/common-labels/):

```yaml
labels:
  app.kubernetes.io/name: myservice
  app.kubernetes.io/instance: myservice-prod
  app.kubernetes.io/version: "1.4.2"
  app.kubernetes.io/component: api
  app.kubernetes.io/managed-by: Helm
```

Пригодится на неделе 9: именно этот набор Helm генерирует в `_helpers.tpl`.

**Annotations** — для метаданных, по которым не ищут: описания, конфиг для контроллеров (`nginx.ingress.kubernetes.io/...`), чексуммы конфигов.

### 6. Service

Стабильная точка входа к меняющемуся набору подов.

| Тип | Что делает |
|---|---|
| **ClusterIP** | Виртуальный IP внутри кластера (по умолчанию) |
| **NodePort** | То же + порт 30000–32767 на **каждой** ноде |
| **LoadBalancer** | То же + внешний балансировщик (в облаке — реальный, в лабе — MetalLB/ServiceLB) |
| **ExternalName** | CNAME на внешнее имя, без проксирования |
| **Headless** (`clusterIP: None`) | Без виртуального IP; DNS возвращает IP всех подов. Нужен для StatefulSet |

**ClusterIP не существует физически.** Это запись в iptables/IPVS на каждой ноде, которую программирует kube-proxy. Нельзя пингануть ClusterIP — и это нормально, спрашивают на собеседованиях.

Связка: `Service` → селектор → **EndpointSlice** (список IP готовых подов) → kube-proxy → правила iptables. Под, не прошедший readiness, из EndpointSlice исключается.

**DNS:** `<service>.<namespace>.svc.cluster.local`. Внутри одного namespace достаточно `<service>`.

---

## 🔧 Задание 1: разведка кластера (1 ч)

```bash
kubectl get nodes -o wide
kubectl describe node cp-1                # Capacity, Allocatable, Conditions, Taints
kubectl get pods -A
kubectl api-resources                     # все типы объектов, их short names и apiVersion
kubectl explain deployment.spec.strategy  # встроенная документация, на CKA спасает
```

Найди ответы в самом кластере:
1. Сколько подов может максимум запуститься на одной ноде? (`Capacity: pods`)
2. Чем `Capacity` отличается от `Allocatable` и куда девается разница?
3. Какие taints стоят на control-plane? Почему в k3s поведение отличается от ванильного кластера?

Затем сравни с ванильным K8s: запусти `kind create cluster` и посмотри `kubectl get pods -n kube-system` — увидишь статик-поды control-plane, которых в k3s нет. Зафиксируй разницу в журнале.

---

## 🔧 Задание 2: killercoda (2 ч)

Пройди бесплатные сценарии, они интерактивные и не требуют своего кластера.

🔗 [killercoda: Kubernetes Basics](https://killercoda.com/killer-shell-cka)

Минимум на эту неделю: сценарии по Pod, Deployment, Service, namespaces. Разделы про RBAC и сеть оставь на недели 5–6.

---

## 🔧 Задание 3: деплой своего сервиса (2 ч)

Разверни образ, собранный на неделе 1. Пиши манифесты руками — генерацию через `--dry-run` используй как черновик, но разбирай каждое поле.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myservice
  labels:
    app.kubernetes.io/name: myservice
spec:
  replicas: 3
  revisionHistoryLimit: 5
  selector:
    matchLabels:
      app.kubernetes.io/name: myservice
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  template:
    metadata:
      labels:
        app.kubernetes.io/name: myservice
        app.kubernetes.io/version: "1.0.0"
    spec:
      terminationGracePeriodSeconds: 30
      containers:
        - name: app
          image: registry.lab/myservice:1.0.0
          imagePullPolicy: IfNotPresent
          ports:
            - name: http
              containerPort: 8000
          env:
            - name: LOG_LEVEL
              value: info
---
apiVersion: v1
kind: Service
metadata:
  name: myservice
spec:
  type: ClusterIP
  selector:
    app.kubernetes.io/name: myservice
  ports:
    - name: http
      port: 80
      targetPort: http
```

⚠️ `targetPort: http` (по имени порта, а не числом) — хорошая привычка: при смене порта в контейнере Service чинить не придётся.

Проверка изнутри кластера:

```bash
kubectl run tmp --rm -it --image=nicolaka/netshoot --restart=Never -- bash
# внутри:
curl http://myservice.default.svc.cluster.local
nslookup myservice
```

---

## 🔧 Задание 4: наблюдаем rolling update (1.5 ч)

Терминал 1 — постоянная нагрузка:
```bash
kubectl run load --rm -it --image=nicolaka/netshoot --restart=Never -- \
  sh -c 'while true; do curl -s -o /dev/null -w "%{http_code}\n" http://myservice; sleep 0.2; done'
```

Терминал 2 — наблюдение:
```bash
kubectl get pods -w
```

Терминал 3 — обновление:
```bash
kubectl set image deployment/myservice app=registry.lab/myservice:1.0.1
kubectl rollout status deployment/myservice
```

Вопросы, на которые нужно ответить по результатам:
- Сколько подов существовало одновременно на пике? Совпало ли с `maxSurge`?
- Появились ли коды, отличные от 200? Если да — **запомни это**, чинить будешь на неделе 3 (probes + graceful shutdown).

Далее:

```bash
kubectl rollout history deployment/myservice
kubectl get rs                                    # старый и новый ReplicaSet
kubectl rollout undo deployment/myservice
kubectl rollout undo deployment/myservice --to-revision=1
```

Найди, **где именно** хранится история ревизий (подсказка: аннотация на ReplicaSet).

Отдельно попробуй `strategy: Recreate` и сравни поведение под нагрузкой.

---

## 🔧 Задание 5: самовосстановление (1 ч)

```bash
# 1. Убить под
kubectl delete pod <имя>
# Кто его пересоздал? Проверь: kubectl describe rs <rs> и kubectl get events --sort-by=.lastTimestamp

# 2. Убить ноду (выключить ВМ)
kubectl get nodes -w
kubectl get pods -o wide -w
```

Засеки тайминги: через сколько нода станет `NotReady`, через сколько поды начнут пересоздаваться на других нодах. Найди в документации параметры `node-monitor-grace-period` и `tolerationSeconds` для `node.kubernetes.io/not-ready` — это они определяют задержку (по умолчанию суммарно около 5 минут). Отличный материал для ответа на собеседовании.

---

## 🔧 Задание 6: скорость императивных команд (1 ч)

Отработай до автоматизма — это фундамент для CKA:

```bash
k run nginx --image=nginx $do > pod.yaml
k create deploy web --image=nginx --replicas=3 $do > deploy.yaml
k expose deploy web --port=80 --target-port=8000 $do > svc.yaml
k create ns dev
k create cm app-config --from-literal=key=value $do
k set image deploy/web nginx=nginx:1.25
k scale deploy web --replicas=5
k delete pod nginx --force --grace-period=0
```

Сделай шпаргалку `notes/kubectl-cheatsheet.md` **своими словами** — переписанная шпаргалка запоминается, скопированная нет.

---

## 💥 Ломаем специально

1. Укажи несуществующий тег образа → поймай `ImagePullBackOff`. Найди точную причину в `kubectl describe pod` (смотри Events, а не Status).
2. Сделай `command: ["/bin/false"]` → поймай `CrashLoopBackOff`. Посмотри, как растёт интервал перезапусков (backoff удваивается до 5 минут).
3. Поставь `replicas: 50` на маленькой лабе → часть подов в `Pending`. Найди в `describe` причину (`Insufficient cpu/memory`).
4. Создай Service с селектором, который не совпадает ни с одним подом. `kubectl get endpointslices` покажет пустоту. Это самая частая причина «сервис не отвечает» в реальной жизни.
5. Удали ReplicaSet, не трогая Deployment. Что произойдёт и почему?

---

## ❓ Самопроверка

1. Расскажи путь `kubectl apply` по шагам, от команды до запущенного контейнера. **Вслух, без подглядывания.**
2. Кто именно создаёт под — Deployment, ReplicaSet или scheduler?
3. Почему нельзя пингануть ClusterIP?
4. Что такое EndpointSlice и как под туда попадает?
5. Deployment vs ReplicaSet: зачем нужна промежуточная сущность?
6. `maxSurge: 0, maxUnavailable: 0` — что произойдёт при обновлении?
7. Под перезапустился — сохранится ли его IP?
8. Чем headless-сервис отличается от обычного и зачем он нужен?
9. Что произойдёт с подами на ноде, если она потеряет связь с control-plane на 3 минуты? А на 30?
10. Почему `spec.selector` у Deployment иммутабелен?

---

## 🔗 Ссылки

| Ресурс | Зачем |
|---|---|
| [Kubernetes Components](https://kubernetes.io/docs/concepts/overview/components/) | Архитектура |
| [Pods](https://kubernetes.io/docs/concepts/workloads/pods/) | Основы |
| [Deployments](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/) | Читать целиком, включая раздел про стратегии |
| [Service](https://kubernetes.io/docs/concepts/services-networking/service/) | Типы и EndpointSlice |
| [Labels and Selectors](https://kubernetes.io/docs/concepts/overview/working-with-objects/labels/) | |
| [What happens when I type kubectl apply](https://github.com/jamiehannaford/what-happens-when-k8s) | Разбор пути запроса очень подробно |
| [killercoda CKA](https://killercoda.com/killer-shell-cka) | Интерактивная практика |
| [Kubernetes in Action, гл. 3–4](https://www.manning.com/books/kubernetes-in-action-second-edition) | Лучшее объяснение «почему так» |

---

## ✅ Чек-лист недели

- [ ] Могу рассказать путь `kubectl apply` из 10 шагов вслух, не подглядывая
- [ ] Свой сервис работает в кластере: Deployment (3 реплики) + Service + DNS-доступ изнутри
- [ ] Наблюдал rolling update под нагрузкой, зафиксировал, теряются ли запросы
- [ ] Сделал rollout undo и нашёл, где хранится история ревизий
- [ ] Замерил тайминги реакции кластера на отказ ноды
- [ ] Все 5 экспериментов «Ломаем специально» проделаны и записаны
- [ ] `kubectl-cheatsheet.md` написан своими словами
- [ ] Манифесты закоммичены в `02-k8s-manifests/`
- [ ] `notes/week-02.md` заполнен
