# Неделя 5 — Сеть: CNI, Service, DNS, Ingress, NetworkPolicy

**Цель недели:** понимать путь пакета от внешнего клиента до контейнера и уметь его чинить.
**Время:** 11 часов (4 ч теории, 7 ч практики).

Самая сложная неделя первых двух месяцев и самая ценная на собеседованиях. Сетевые вопросы отсекают тех, кто выучил манифесты, но не понимает, что происходит под ними. Не жалей на неё времени — при необходимости растяни на полторы недели.

---

## 📖 Теория

### 1. Сетевая модель Kubernetes: четыре правила

Kubernetes не реализует сеть сам — он **требует** от реализации выполнения правил:

1. Каждый под получает **свой уникальный IP** в плоском адресном пространстве.
2. Любой под может связаться с любым подом **напрямую, без NAT**.
3. Агенты на ноде (kubelet, системные демоны) могут связаться с любым подом на этой ноде.
4. Под видит себя по тому же IP, по которому его видят другие.

Из правила 2 следует важное: **никакого port mapping, как в Docker.** Два пода на разных нодах могут слушать порт 8080, и это не конфликт. Разработчику не нужно знать, на какой ноде живёт сосед.

Реализуют эти правила **CNI-плагины**.

### 2. CNI: что происходит при создании пода

Когда kubelet запускает под:

1. Создаётся **pause-контейнер**, который держит network namespace.
2. kubelet вызывает CNI-плагин (бинарник в `/opt/cni/bin`, конфиг в `/etc/cni/net.d/`).
3. Плагин создаёт `veth`-пару: один конец в namespace пода (становится `eth0`), другой — на хосте.
4. Плагин выделяет IP из подсети, назначенной этой ноде (IPAM), настраивает маршруты.
5. Все остальные контейнеры пода присоединяются к **этому же** namespace.

Отсюда: контейнеры одного пода общаются через `localhost` и не могут занять один порт.

**Основные плагины:**

| Плагин | Как связывает ноды | Особенности |
|---|---|---|
| **flannel** | VXLAN-оверлей (по умолчанию) | Простой, без NetworkPolicy. В k3s по умолчанию |
| **Calico** | BGP или IP-in-IP | Полноценные NetworkPolicy, зрелый, стандарт в энтерпрайзе |
| **Cilium** | eBPF, может без kube-proxy | Самый быстрый, L7-политики, Hubble для наблюдаемости. Куда движется индустрия |

⚠️ **В k3s с flannel NetworkPolicy работают** (k3s включает свой контроллер), но возможности ограничены. Для полноценной практики на этой неделе поставь Calico или Cilium — это само по себе полезное упражнение.

**Оверлей vs роутинг:** VXLAN упаковывает пакет пода в UDP-пакет между нодами (работает где угодно, но добавляет накладные расходы и уменьшает эффективный MTU). BGP-режим просто раздаёт маршруты — быстрее, но требует поддержки от сети.

⚠️ Классическая проблема, которую стоит знать: **MTU**. Оверлей добавляет ~50 байт заголовка. Если MTU внутри пода не уменьшен, большие пакеты фрагментируются или теряются. Симптом характерный: `curl` на маленький ответ работает, а на большой — виснет. TLS-хендшейк проходит, а передача данных нет.

### 3. Service изнутри: как ClusterIP превращается в правила

ClusterIP — **виртуальный** адрес, за которым нет интерфейса. Цепочка такая:

```
Service (ClusterIP 10.43.x.x)
   ↓ селектор по лейблам
EndpointSlice (список IP готовых подов)
   ↓ watch
kube-proxy на КАЖДОЙ ноде
   ↓ программирует
правила iptables / IPVS
```

**Режим iptables** (по умолчанию): для каждого сервиса создаётся цепочка `KUBE-SVC-XXX`, в ней — правила со `statistic mode random probability` для распределения между `KUBE-SEP-YYY` (по одной на каждый эндпоинт). Балансировка случайная, не round-robin.

⚠️ Минус iptables-режима: правила обрабатываются линейно. При тысячах сервисов это заметно деградирует. Отсюда **IPVS-режим** (хеш-таблицы, O(1), алгоритмы rr/lc/sh) и **Cilium без kube-proxy** (eBPF).

Посмотреть можно прямо на ноде:

```bash
sudo iptables-save -t nat | grep <cluster-ip>
# или для IPVS:
sudo ipvsadm -Ln
```

Практические следствия, которые спрашивают:

- **ClusterIP не пингуется** — ICMP не проходит через DNAT-правила, за адресом нет хоста.
- **Балансировка на уровне соединения, не запроса.** Для HTTP/1.1 с keep-alive и особенно для gRPC (одно долгоживущее HTTP/2-соединение) весь трафик уйдёт в один под. Решения: балансировка на клиенте, headless-сервис, или service mesh. **Это любимый вопрос на собеседованиях уровня Middle+.**
- `sessionAffinity: ClientIP` — липкие сессии по IP клиента.
- `externalTrafficPolicy: Local` для NodePort/LoadBalancer — сохраняет исходный IP клиента, но трафик идёт только в поды на этой ноде.

### 4. DNS: CoreDNS и подводные камни

CoreDNS — Deployment в `kube-system`, доступен через Service `kube-dns` (историческое имя). kubelet прописывает его адрес в `/etc/resolv.conf` каждого пода.

**Схема имён:**
- Сервис: `<service>.<namespace>.svc.cluster.local`
- Под StatefulSet: `<pod>.<service>.<namespace>.svc.cluster.local`
- Headless: A-записи всех подов на имя сервиса

**Про `ndots:5` — обязательно к пониманию.** В поде `/etc/resolv.conf` выглядит так:

```
search default.svc.cluster.local svc.cluster.local cluster.local
nameserver 10.43.0.10
options ndots:5
```

Правило: если в имени **меньше 5 точек**, резолвер сначала перебирает все домены из `search`. Запрос к `api.github.com` (2 точки) породит:

```
api.github.com.default.svc.cluster.local   → NXDOMAIN
api.github.com.svc.cluster.local           → NXDOMAIN
api.github.com.cluster.local               → NXDOMAIN
api.github.com                             → успех
```

Четыре запроса вместо одного (а с учётом A и AAAA — восемь). При высокой нагрузке это заметная задержка и нагрузка на CoreDNS.

Лечение: точка в конце имени (`api.github.com.`) или `dnsConfig` с `ndots: 2` в спецификации пода. Отличная история для собеседования — покажи, что понимаешь, откуда берётся «медленный DNS в Kubernetes».

### 5. Ingress

**Ingress-ресурс** — это описание правил маршрутизации. Сам по себе он не делает ничего. Работу выполняет **Ingress-контроллер** — под в кластере (обычно Deployment или DaemonSet + Service типа LoadBalancer/NodePort), который следит за Ingress-ресурсами и перестраивает свой конфиг.

Ingress работает на **L7** (HTTP/HTTPS): маршрутизация по хосту и пути, TLS-терминация, редиректы.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: myservice
  annotations:
    nginx.ingress.kubernetes.io/proxy-body-size: "50m"
spec:
  ingressClassName: nginx
  tls:
    - hosts: [app.lab.local]
      secretName: app-tls
  rules:
    - host: app.lab.local
      http:
        paths:
          - path: /api
            pathType: Prefix
            backend:
              service:
                name: myservice
                port: { name: http }
```

**pathType** — три значения, разница важна:
- `Exact` — точное совпадение
- `Prefix` — по сегментам пути (`/api` совпадёт с `/api/v1`, но **не** с `/apifoo`)
- `ImplementationSpecific` — как решит контроллер (для nginx — регулярки)

⚠️ Основная критика Ingress: почти всё нетривиальное делается **аннотациями**, специфичными для конкретного контроллера. Перенести конфиг с nginx на traefik — задача с нуля. Именно эту проблему решает **Gateway API**: он выносит настройки в типизированные ресурсы (`GatewayClass`, `Gateway`, `HTTPRoute`) и разделяет роли — платформенная команда владеет `Gateway`, продуктовые команды владеют `HTTPRoute`. Ingress формально заморожен, новые возможности идут только в Gateway API.

### 6. NetworkPolicy

По умолчанию в Kubernetes **всё разрешено**: любой под может обратиться к любому. NetworkPolicy это меняет.

Логика, которую нужно усвоить точно:

1. Политики **аддитивны**: правила складываются, запрещающих правил не существует.
2. Как только на под нацелена **хотя бы одна** политика с типом `Ingress`, весь остальной входящий трафик к нему запрещается. То же отдельно для `Egress`.
3. Политика namespaced и выбирает поды через `podSelector`. Пустой `podSelector: {}` = все поды namespace.

Базовый default-deny:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: default-deny-all, namespace: app }
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]
```

Затем точечные разрешения:

```yaml
spec:
  podSelector:
    matchLabels: { app.kubernetes.io/name: myservice }
  policyTypes: [Ingress, Egress]
  ingress:
    - from:
        - namespaceSelector:
            matchLabels: { kubernetes.io/metadata.name: ingress-nginx }
      ports: [{ port: 8000, protocol: TCP }]
  egress:
    - to:
        - podSelector:
            matchLabels: { app: pg }
      ports: [{ port: 5432, protocol: TCP }]
    - to:                                    # DNS — забывают почти всегда
        - namespaceSelector:
            matchLabels: { kubernetes.io/metadata.name: kube-system }
          podSelector:
            matchLabels: { k8s-app: kube-dns }
      ports:
        - { port: 53, protocol: UDP }
        - { port: 53, protocol: TCP }
```

⚠️ **Топ-1 ошибка при внедрении NetworkPolicy:** закрыли egress и забыли разрешить DNS. Приложение перестаёт резолвить вообще всё, а симптом выглядит как «сеть сломалась», хотя политика формально «только про базу».

⚠️ Второй нюанс: `namespaceSelector` и `podSelector` в **одном** элементе списка `from` работают как AND (поды с такими лейблами в namespace с такими лейблами). Разделённые дефисом — как OR. Синтаксически разница в один символ, семантически огромная.

⚠️ Третий: NetworkPolicy работает на L3/L4. Ограничить доступ «только к `/api/public`» она не может — это уровень service mesh или Cilium с L7-политиками.

---

## 🔧 Задание 1: препарируем Service (2 ч)

1. Разверни отладочный под и походи по кластеру:
   ```bash
   kubectl run netshoot --rm -it --image=nicolaka/netshoot --restart=Never -- bash
   ```
   Внутри: `ip a`, `ip route`, `cat /etc/resolv.conf`, `nslookup myservice`, `dig myservice.app.svc.cluster.local`.

2. На ноде найди правила своего сервиса:
   ```bash
   kubectl get svc myservice -o jsonpath='{.spec.clusterIP}'
   sudo iptables-save -t nat | grep <ip>
   ```
   Проследи цепочку `KUBE-SERVICES` → `KUBE-SVC-*` → `KUBE-SEP-*`. Найди правила вероятностного распределения.

3. Убедись, что ClusterIP не пингуется, но `curl` на него работает. Объясни себе почему.

4. Отмасштабируй Deployment и посмотри, как меняется EndpointSlice:
   ```bash
   kubectl get endpointslices -w
   ```

5. Выключи readiness на одном поде (рубильник с недели 3) — увидь, как IP исчезает из EndpointSlice, а правило iptables пропадает.

6. **Эксперимент с балансировкой:** сделай 100 запросов через `curl` и посчитай распределение по подам (добавь в ответ имя пода через downwardAPI). Затем сделай 100 запросов в одном keep-alive соединении (`curl` с `--keepalive` или простой Python-скрипт с `requests.Session`). Сравни распределение. **Это и есть та самая проблема с gRPC.**

---

## 🔧 Задание 2: DNS и ndots (1 ч)

1. Измерь эффект ndots:
   ```bash
   # в netshoot
   time nslookup api.github.com
   time nslookup api.github.com.        # с точкой в конце
   ```

2. Посмотри реальные запросы:
   ```bash
   kubectl logs -n kube-system -l k8s-app=kube-dns --tail=100
   # включи логирование в Corefile, если не включено: плагин log
   ```

3. Настрой в своём Deployment:
   ```yaml
   dnsConfig:
     options:
       - name: ndots
         value: "2"
   ```
   Повтори замер, зафиксируй разницу в журнале.

4. Сломай DNS специально: удали поды CoreDNS (`kubectl delete pod -n kube-system -l k8s-app=kube-dns`). Что произошло с приложением? Насколько быстро восстановилось? Кэшируется ли что-нибудь?

---

## 🔧 Задание 3: Ingress и TLS (2.5 ч)

1. Установи ingress-nginx (Helm-чартом, пусть это будет и первое знакомство):
   ```bash
   helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
   helm install ingress-nginx ingress-nginx/ingress-nginx \
     -n ingress-nginx --create-namespace \
     --set controller.service.type=NodePort \
     --set controller.service.nodePorts.http=30080 \
     --set controller.service.nodePorts.https=30443
   ```

   Для более реалистичного варианта поставь **MetalLB** и получи настоящий LoadBalancer с внешним IP — рекомендую, это ближе к продовой картине.

2. Опубликуй сервис по имени `app.lab.local` (добавь запись в `/etc/hosts` рабочей машины или используй nip.io).

3. Разверни второй сервис и настрой маршрутизацию:
   - по хосту: `api.lab.local` и `web.lab.local`
   - по пути: `/api` → один сервис, `/` → другой
   - проверь разницу `pathType: Prefix` и `Exact` опытом

4. **cert-manager с собственным CA:**
   ```bash
   helm repo add jetstack https://charts.jetstack.io
   helm install cert-manager jetstack/cert-manager \
     -n cert-manager --create-namespace --set crds.enabled=true
   ```
   Создай самоподписанный `ClusterIssuer`, выпусти CA, затем выпускай им сертификаты для Ingress. Проверь, что Secret с сертификатом создался автоматически и что он обновляется при приближении срока.

5. Загляни в сгенерированный конфиг nginx — полезно понимать, во что превращается твой Ingress:
   ```bash
   kubectl exec -n ingress-nginx deploy/ingress-nginx-controller -- cat /etc/nginx/nginx.conf | less
   ```

6. Поэкспериментируй с 3–4 аннотациями: `proxy-body-size`, `rewrite-target`, `ssl-redirect`, `rate-limit`. Найди каждую в сгенерированном конфиге.

---

## 🔧 Задание 4: NetworkPolicy (2 ч)

Если у тебя k3s с flannel — установи Calico или Cilium. Cilium интереснее (eBPF, Hubble для визуализации трафика), но Calico проще.

1. Создай в namespace `app` политику `default-deny-all`. Убедись, что **всё сломалось**: приложение не ходит в БД, не резолвит DNS, Ingress не достучится.

2. Восстанавливай доступ по частям, каждый раз проверяя:
   - разреши DNS (egress к kube-dns) → резолв заработал
   - разреши ingress от namespace ingress-nginx → внешний доступ вернулся
   - разреши egress к Postgres по 5432 → БД доступна
   - разреши egress в интернет (к Artifactory/Jira) — обрати внимание, что тут придётся указывать `ipBlock` с CIDR, потому что внешние адреса не описываются селекторами

3. Проверяй каждый шаг из отладочного пода:
   ```bash
   kubectl exec -it deploy/myservice -- nc -zv pg 5432
   kubectl exec -it deploy/myservice -- nslookup pg
   ```

4. Проверь изоляцию между namespace: подними под в `default` и попробуй достучаться до сервиса в `app`.

5. Если поставил Cilium — разверни **Hubble UI** и посмотри на трафик визуально. Это очень наглядно и хорошо смотрится скриншотом в README.

⚠️ Помни про AND/OR в `from`. Специально напиши обе версии и сравни, кто проходит.

---

## 🔧 Задание 5: путь пакета целиком (1.5 ч)

Итоговое упражнение недели. Нарисуй **схему** (Mermaid или excalidraw) и положи её в репозиторий: путь HTTP-запроса от браузера до кода приложения, со всеми звеньями:

```
браузер
  → DNS (внешний)
  → внешний IP / NodePort / LoadBalancer
  → нода
  → iptables DNAT → Service ingress-nginx
  → под ingress-nginx (L7-маршрутизация по Host и Path)
  → ClusterIP целевого сервиса
  → iptables DNAT → IP пода из EndpointSlice
  → veth → network namespace пода
  → процесс приложения
```

Для каждого звена ответь письменно: **что ломается, если сломается это звено, и как это выглядит для пользователя.** Такая таблица — практически готовый ответ на 20 минут собеседования.

---

## 💥 Ломаем специально

1. Поменяй лейбл на подах так, чтобы селектор Service перестал совпадать. `kubectl get endpointslices` пуст, `curl` виснет. Именно так выглядит топ-1 реальная проблема с сервисами.
2. Создай два Ingress с одинаковым хостом и путём, но разными бэкендами. Кто победит? Найди в документации правило разрешения конфликтов.
3. Забудь `ingressClassName` — Ingress создастся, но контроллер его проигнорирует. Пойми, как это диагностировать (`kubectl describe ingress` → отсутствие Events от контроллера, пустой ADDRESS).
4. Закрой egress без DNS-правила и посмотри, как приложение падает по таймаутам, а не по «connection refused». Разница в симптомах важна.
5. Убей все поды CoreDNS и замерь время до восстановления сервиса.
6. Если поставил Calico: сломай MTU (поставь 9000 на оверлее в сети с MTU 1500) и увидь классический симптом — маленькие запросы работают, большие виснут.

---

## ❓ Самопроверка

1. Четыре правила сетевой модели Kubernetes.
2. Что делает CNI-плагин в момент создания пода? Опиши по шагам.
3. Почему ClusterIP не пингуется?
4. Как выглядит цепочка Service → под на уровне iptables?
5. Что произойдёт с балансировкой при gRPC-трафике и почему? Три способа решения.
6. Что такое `ndots:5` и какую проблему создаёт? Как чинится?
7. Ingress-ресурс и Ingress-контроллер — в чём разница? Что будет, если создать ресурс без контроллера?
8. `pathType: Prefix` — совпадёт ли `/api` с `/apifoo`?
9. Почему Ingress считается устаревающим и что предлагает Gateway API?
10. Что происходит с подом, на который нацелена NetworkPolicy с `policyTypes: [Ingress]` и пустым списком правил?
11. В чём разница между `namespaceSelector` и `podSelector` в одном элементе `from` и в разных?
12. Может ли NetworkPolicy ограничить доступ к конкретному HTTP-пути?
13. Что такое `externalTrafficPolicy: Local` и какой у него побочный эффект?

---

## 🔗 Ссылки

| Ресурс | Зачем |
|---|---|
| [Cluster Networking](https://kubernetes.io/docs/concepts/cluster-administration/networking/) | Модель и требования |
| [Service](https://kubernetes.io/docs/concepts/services-networking/service/) | Перечитать после недели 2, теперь глубже |
| [DNS for Services and Pods](https://kubernetes.io/docs/concepts/services-networking/dns-pod-service/) | Схема имён и ndots |
| [Ingress](https://kubernetes.io/docs/concepts/services-networking/ingress/) | |
| [ingress-nginx docs](https://kubernetes.github.io/ingress-nginx/) | Аннотации — справочник |
| [Gateway API](https://gateway-api.sigs.k8s.io/) | Куда движется экосистема |
| [Network Policies](https://kubernetes.io/docs/concepts/services-networking/network-policies/) | |
| [Network Policy Editor (Cilium)](https://editor.networkpolicy.io/) | Визуальный конструктор политик, очень помогает |
| [Isovalent Labs](https://isovalent.com/resource-library/labs/) | Бесплатные интерактивные лабы по Cilium/eBPF |
| [cert-manager](https://cert-manager.io/docs/) | TLS-автоматизация |
| [MetalLB](https://metallb.universe.tf/) | LoadBalancer в bare-metal лабе |
| [learnk8s: Service discovery](https://learnk8s.io/kubernetes-services-and-load-balancing) | Разбор балансировки и keep-alive |

---

## ✅ Чек-лист недели

- [ ] Нашёл правила своего Service в iptables и проследил цепочку до подов
- [ ] Воспроизвёл проблему балансировки с keep-alive-соединением, знаю три решения
- [ ] Измерил эффект `ndots:5` и настроил `dnsConfig`
- [ ] ingress-nginx работает, маршрутизация по хосту и по пути настроена
- [ ] TLS через cert-manager с собственным CA, сертификат выпускается автоматически
- [ ] Прошёл путь default-deny → пошаговое восстановление доступа через NetworkPolicy
- [ ] Проверил изоляцию между namespace
- [ ] Схема пути пакета нарисована и лежит в репозитории
- [ ] Таблица «звено → как выглядит его отказ» написана
- [ ] Все 6 экспериментов «Ломаем специально» проделаны
- [ ] `notes/week-05.md` заполнен
