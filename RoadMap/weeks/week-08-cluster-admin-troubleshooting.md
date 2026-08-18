# Неделя 8 — Администрирование кластера и troubleshooting

**Цель недели:** собрать кластер руками, научиться его чинить и восстанавливать. Превращение «пользователя кластера» в «инженера кластера».
**Время:** 11 часов (3 ч теории, 8 ч практики).

Это неделя, которая даёт больше всего материала для собеседований. Работодатель почти никогда не спрашивает «как написать Deployment» — он спрашивает «под в Pending, твои действия».

---

## 📖 Теория

### 1. Как устроен kubeadm-кластер

В отличие от k3s (один процесс), в ванильном кластере компоненты control-plane — это **статик-поды**: kubelet читает манифесты из `/etc/kubernetes/manifests/` и запускает их напрямую, минуя API server. Именно поэтому кластер может подняться сам себя: kubelet стартует apiserver до того, как apiserver существует.

Ключевые пути:

```
/etc/kubernetes/
├── manifests/                  # статик-поды control-plane
│   ├── kube-apiserver.yaml
│   ├── kube-controller-manager.yaml
│   ├── kube-scheduler.yaml
│   └── etcd.yaml
├── pki/                        # все сертификаты
│   ├── ca.crt / ca.key         # корневой CA кластера
│   ├── apiserver.crt/.key
│   ├── etcd/                   # отдельный CA для etcd
│   └── sa.pub / sa.key         # подпись ServiceAccount-токенов
├── admin.conf                  # kubeconfig администратора
├── kubelet.conf
└── controller-manager.conf, scheduler.conf

/var/lib/kubelet/config.yaml    # конфигурация kubelet
/var/lib/etcd/                  # данные etcd
```

⚠️ Приём, который стоит знать: **чтобы «выключить» компонент control-plane, достаточно убрать его манифест из `/etc/kubernetes/manifests/`.** kubelet заметит и остановит под. Вернуть — положить обратно. На CKA это встречается в задачах про сломанный scheduler.

⚠️ Сертификаты kubeadm по умолчанию живут **один год**. Их продлевает `kubeadm certs renew all` (происходит автоматически при `kubeadm upgrade`). Кластер, простоявший год без обновлений, однажды перестаёт отвечать — классический инцидент, о нём полезно знать.

### 2. etcd: бэкап и восстановление

etcd хранит **всё** состояние кластера. Потерял etcd — потерял кластер (при этом контейнеры на нодах продолжат работать, но управление исчезнет).

Кворум: `(n/2)+1`. Отсюда нечётное число членов: 3 переживает падение одного, 5 — двух. Кластер из 2 членов **хуже**, чем из 1, потому что кворум = 2 и падение любого узла останавливает запись.

Бэкап:

```bash
ETCDCTL_API=3 etcdctl snapshot save /backup/etcd-$(date +%F).db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key

etcdctl snapshot status /backup/etcd-2026-08-18.db --write-out=table
```

Восстановление (последовательность важна):

```bash
# 1. Остановить control-plane: убрать манифесты
mv /etc/kubernetes/manifests/*.yaml /tmp/

# 2. Восстановить в НОВЫЙ каталог
ETCDCTL_API=3 etcdctl snapshot restore /backup/etcd.db \
  --data-dir=/var/lib/etcd-restored

# 3. Указать новый каталог в манифесте etcd (hostPath volume)
# 4. Вернуть манифесты на место
mv /tmp/*.yaml /etc/kubernetes/manifests/
```

⚠️ Что бэкап etcd **не** содержит: данные PersistentVolume. Бэкап кластера ≠ бэкап приложений. Для приложений — Velero или инструменты уровня БД.

### 3. Обновление кластера

Порядок строгий: **etcd/control-plane → воркеры**. По одной ноде за раз.

```bash
# На control-plane
kubeadm upgrade plan
kubeadm upgrade apply v1.3x.y
kubectl drain cp-1 --ignore-daemonsets
apt install -y kubelet=1.3x.y-* kubectl=1.3x.y-*
systemctl restart kubelet
kubectl uncordon cp-1

# На каждом воркере
kubectl drain node-1 --ignore-daemonsets --delete-emptydir-data
kubeadm upgrade node
apt install -y kubelet=1.3x.y-*
systemctl restart kubelet
kubectl uncordon node-1
```

**Version skew policy** — что с чем совместимо:
- kubelet может отставать от apiserver **на 3 минорные версии**, но не опережать
- controller-manager/scheduler — не новее apiserver
- kubectl — ±1 минорная версия от apiserver
- **Перескакивать минорные версии нельзя**: 1.29 → 1.31 напрямую не поддерживается, только 1.29 → 1.30 → 1.31

### 4. Дерево диагностики: от симптома к причине

Это главный практический артефакт недели. Разбери каждую ветку.

**Pod в `Pending`** — scheduler не смог разместить:
- Недостаточно ресурсов → `describe pod` → Events: `Insufficient cpu/memory`
- Taint без toleration → `describe node`, смотри Taints
- nodeSelector/affinity не совпадает → `describe pod`, смотри условия
- PVC не привязан (`Pending`) → проблема StorageClass или зоны
- ResourceQuota исчерпана → `describe quota`
- Кластер вообще без готовых нод → `get nodes`

**`ImagePullBackOff` / `ErrImagePull`:**
- Опечатка в имени или теге
- Нет доступа к приватному registry → нужен `imagePullSecrets`
- Registry недоступен с ноды (DNS, firewall, прокси) → проверь `crictl pull` **на ноде**
- Rate limit Docker Hub

**`CrashLoopBackOff`** — контейнер стартует и падает:
- `kubectl logs <pod> --previous` — **ключевая команда**, логи предыдущего запуска
- Ошибка конфигурации, недоступная зависимость
- Неверные `command`/`args` (перепутали с ENTRYPOINT/CMD)
- OOMKilled → `describe`, Last State, exit code **137**
- Liveness убивает медленно стартующее приложение → нужен startupProbe
- Приложение завершается штатно (exit 0), а `restartPolicy: Always` → перезапуск бесконечно

**`ContainerCreating` надолго:**
- Не смонтировался том (нет PVC, ошибка CSI)
- Отсутствует ConfigMap или Secret → `describe` покажет прямо
- Проблема CNI → смотри логи CNI-подов
- Долгое скачивание большого образа

**Pod `Running`, но `0/1 READY`:**
- Readiness не проходит → `describe`, смотри Events; проверь эндпоинт руками через `exec`

**Сервис не отвечает:**
1. `kubectl get endpointslices` — пусто? → селектор не совпадает с лейблами подов, или ни один под не readiness-ready
2. Есть эндпоинты, но нет ответа → проверь `targetPort` и порт, который слушает приложение
3. Проверь изнутри кластера из netshoot, чтобы исключить Ingress
4. Проверь NetworkPolicy
5. Проверь DNS

**Нода `NotReady`:**
- `kubectl describe node` → Conditions (MemoryPressure, DiskPressure, PIDPressure)
- На ноде: `systemctl status kubelet`, `journalctl -u kubelet -f`
- Кончилось место на диске (частая причина — незачищенные образы) → `crictl images`, `crictl rmi --prune`
- Проблема с container runtime → `systemctl status containerd`
- Сеть до control-plane

### 5. Инструменты диагностики на ноде

Когда `kubectl` не помогает, идёшь на ноду. Там нет docker — там **crictl**:

```bash
crictl ps -a                 # контейнеры
crictl logs <container-id>
crictl images
crictl inspect <id>
crictl pull <image>          # проверить доступность registry с ноды
```

Логи компонентов:
```bash
journalctl -u kubelet -f --no-pager
journalctl -u containerd -f
crictl logs $(crictl ps -a --name kube-apiserver -q | head -1)   # apiserver как статик-под
```

Отладка внутри пода без shell в образе (**ephemeral containers**):

```bash
kubectl debug -it <pod> --image=nicolaka/netshoot --target=app
```

Отладка ноды:
```bash
kubectl debug node/node-1 -it --image=busybox
# корень ноды окажется в /host
```

События кластера — часто самый быстрый путь к причине:
```bash
kubectl get events -A --sort-by=.lastTimestamp | tail -40
kubectl events --for pod/myservice-xxx        # современный вариант
```

---

## 🔧 Задание 1: собираем кластер kubeadm (3 ч)

Один раз пройти этот путь обязательно — без него понимание архитектуры остаётся книжным.

Возьми **три новые ВМ** (не трогай рабочий k3s — он ещё понадобится).

```bash
# На всех нодах: containerd
sudo apt install -y containerd
containerd config default | sudo tee /etc/containerd/config.toml
sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
sudo systemctl restart containerd
```
⚠️ `SystemdCgroup = true` — обязательно. Без этого kubelet и containerd используют разные cgroup-драйверы, и ноды ведут себя нестабильно под нагрузкой. Классическая ошибка.

```bash
# Репозиторий и пакеты (версию подставь актуальную)
sudo apt install -y kubelet kubeadm kubectl
sudo apt-mark hold kubelet kubeadm kubectl

# На control-plane
sudo kubeadm init --pod-network-cidr=10.244.0.0/16

# CNI (Calico — чтобы были полноценные NetworkPolicy)
kubectl apply -f https://raw.githubusercontent.com/projectcalico/calico/master/manifests/calico.yaml

# На воркерах — команда из вывода kubeadm init
sudo kubeadm join ...
```

После установки **обязательно исследуй**:

```bash
ls -la /etc/kubernetes/manifests/
ls -la /etc/kubernetes/pki/
sudo cat /etc/kubernetes/manifests/kube-apiserver.yaml    # прочитай флаги!
kubectl get pods -n kube-system                            # вот они, статик-поды
openssl x509 -in /etc/kubernetes/pki/apiserver.crt -text -noout | grep -A2 Validity
kubeadm certs check-expiration
```

Сравни с k3s и запиши отличия в журнал. Это готовый ответ на вопрос «чем отличаются дистрибутивы Kubernetes».

---

## 🔧 Задание 2: etcd — бэкап и восстановление (2 ч)

Полный цикл, как на CKA:

1. Создай в кластере заметный объект: namespace `canary` с несколькими Deployment и ConfigMap.
2. Сделай снапшот etcd, проверь его `snapshot status`.
3. **Удали namespace `canary` полностью.**
4. Восстановись из снапшота по процедуре из теории.
5. Убедись, что namespace вернулся со всем содержимым.

Дополнительно:
- Проверь, что произойдёт, если восстановить снапшот **в существующий** каталог данных (не сработает — etcd откажется).
- Посмотри размер снапшота и прикинь, как он растёт с числом объектов.
- Настрой CronJob, который делает бэкап etcd регулярно и складывает в PVC. Полезное упражнение и хороший артефакт для репозитория.

---

## 🔧 Задание 3: обновление кластера (1.5 ч)

Обнови свежесобранный kubeadm-кластер на одну минорную версию.

Обязательно наблюдай:
1. Что происходит с рабочей нагрузкой во время обновления (запусти k6 в фоне и посчитай ошибки).
2. Работает ли PDB, настроенный на неделе 7.
3. Сколько времени занимает обновление одной ноды.

Затем попробуй **перескочить** версию (1.x → 1.x+2) и прочитай, как kubeadm откажется это делать. Зафиксируй version skew policy в журнале своими словами.

---

## 🔧 Задание 4: killercoda troubleshooting (2 ч)

🔗 [killercoda: CKA scenarios](https://killercoda.com/killer-shell-cka)

Пройди все сценарии по разделам troubleshooting и cluster maintenance. Работай **с таймером** — на реальном экзамене время критично.

После каждого сценария записывай в `notes/`: симптом → команда, которая дала подсказку → причина.

---

## 🔧 Задание 5: chaos-час (1.5 ч)

Главное задание недели. Нужен «сломанный» кластер, который ты чинишь вслепую.

**Вариант А (лучший):** попроси коллегу или знакомого сломать 5 вещей в твоём кластере, не говоря, что именно.

**Вариант Б:** напиши скрипт, который случайно выбирает 5 поломок из списка, выполняет их и **не выводит, какие**. Запусти, подожди день, потом чини.

Список поломок для скрипта:

```bash
# 1. Сломать kubelet на ноде
sudo sed -i 's|/var/lib/kubelet|/var/lib/kubelet-broken|' /var/lib/kubelet/kubeadm-flags.env

# 2. Убрать манифест scheduler
sudo mv /etc/kubernetes/manifests/kube-scheduler.yaml /tmp/

# 3. Испортить образ в Deployment
kubectl set image deploy/myservice app=registry.lab/myservice:nonexistent

# 4. Сломать RBAC
kubectl delete rolebinding myservice-binding -n app

# 5. Испортить селектор Service
kubectl patch svc myservice -n app -p '{"spec":{"selector":{"app":"wrong"}}}'

# 6. Заполнить диск ноды
sudo fallocate -l 20G /var/lib/bloat

# 7. Поставить taint NoExecute
kubectl taint node node-1 broken=yes:NoExecute

# 8. Удалить ConfigMap, используемый подом
kubectl delete cm app-config -n app

# 9. Сломать CoreDNS
kubectl scale deploy coredns -n kube-system --replicas=0

# 10. Испортить NetworkPolicy (default-deny без DNS)
```

**Правила игры:**
- Замеряй время на каждую поломку.
- Записывай путь рассуждений, а не только решение.
- Цель к неделе 18 — любая типовая поломка за **менее чем 10 минут**.

---

## 🔧 Задание 6: собственный playbook (1 ч)

Оформи `notes/troubleshooting-playbook.md` — дерево решений по симптомам. Структура:

```markdown
## Симптом: Pod в Pending

### Шаг 1: kubectl describe pod <name> → раздел Events
| Сообщение | Причина | Проверить | Решение |
|---|---|---|---|
| Insufficient cpu | не хватает ресурсов | `kubectl describe node` → Allocated resources | снизить requests / добавить ноду |
| had taint that pod didn't tolerate | taint | `kubectl describe node` → Taints | добавить toleration или снять taint |
| ...

### Шаг 2: если Events пусты — жив ли scheduler?
kubectl get pods -n kube-system | grep scheduler
```

Пиши **своими словами**. Этот файл — твой персональный артефакт: он останется полезным и на работе, и как заготовка ответов на собеседовании.

---

## 💥 Ломаем специально

Дополнительно к chaos-часу:

1. Останови etcd на control-plane. Что происходит с `kubectl`? А с уже работающими подами на воркерах? Запусти новый под — получится?
2. Удали `/etc/kubernetes/pki/apiserver.crt` и перезапусти kubelet. Восстанови через `kubeadm init phase certs apiserver`.
3. Переведи системные часы на ноде на час вперёд — увидь, как ломается TLS (сертификаты «ещё не действительны»). Верни.
4. Заполни диск на ноде до 90% — поймай taint `disk-pressure` и выселение подов. Найди в документации пороги eviction kubelet (`--eviction-hard`).
5. Испорти `/var/lib/kubelet/config.yaml` (например, неверный cgroupDriver) → kubelet не стартует. Читай `journalctl` и чини.

---

## ❓ Самопроверка

1. Что такое статик-под и почему control-plane реализован именно так?
2. Как «выключить» scheduler на kubeadm-кластере одной командой?
3. Что произойдёт с кластером через год после установки, если ни разу не обновлять?
4. Опиши процедуру восстановления etcd из снапшота по шагам.
5. Содержит ли бэкап etcd данные PersistentVolume?
6. Почему кластер etcd из 2 узлов хуже, чем из 1?
7. Version skew: на сколько версий kubelet может отставать от apiserver? Можно ли перескочить минорную версию?
8. Под в Pending — перечисли шесть возможных причин и как отличить их друг от друга.
9. `kubectl logs` пуст, под в CrashLoopBackOff. Твои следующие две команды?
10. Сервис не отвечает — алгоритм проверки из пяти шагов.
11. Чем `crictl` отличается от `docker` и когда он нужен?
12. Что такое ephemeral container и зачем он, если есть `kubectl exec`?
13. Нода NotReady — где смотреть в первую очередь?
14. Почему `SystemdCgroup = true` в containerd так важен?

---

## 🔗 Ссылки

| Ресурс | Зачем |
|---|---|
| [Creating a cluster with kubeadm](https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/create-cluster-kubeadm/) | Задание 1 |
| [Operating etcd clusters](https://kubernetes.io/docs/tasks/administer-cluster/configure-upgrade-etcd/) | Бэкап и восстановление |
| [Upgrading kubeadm clusters](https://kubernetes.io/docs/tasks/administer-cluster/kubeadm/kubeadm-upgrade/) | |
| [Version Skew Policy](https://kubernetes.io/releases/version-skew-policy/) | |
| [Troubleshooting Clusters](https://kubernetes.io/docs/tasks/debug/debug-cluster/) | |
| [Debug Running Pods](https://kubernetes.io/docs/tasks/debug/debug-application/debug-running-pod/) | Ephemeral containers |
| [Debugging with crictl](https://kubernetes.io/docs/tasks/debug/debug-cluster/crictl/) | |
| [Node-pressure Eviction](https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/) | Пороги вытеснения |
| [killercoda CKA](https://killercoda.com/killer-shell-cka) | Практика |
| [Kubernetes The Hard Way](https://github.com/kelseyhightower/kubernetes-the-hard-way) | Опционально, +6–8 ч, максимальное понимание |
| [Velero](https://velero.io/docs/) | Бэкап приложений, а не только etcd |

---

## ✅ Чек-лист недели

- [ ] Собрал kubeadm-кластер с нуля, изучил `/etc/kubernetes/` и флаги apiserver
- [ ] Записал отличия kubeadm-кластера от k3s
- [ ] Сделал бэкап etcd и **восстановился** из него после удаления namespace
- [ ] Настроил CronJob регулярного бэкапа etcd
- [ ] Обновил кластер на минорную версию под нагрузкой, замерил ошибки
- [ ] Прошёл сценарии killercoda по troubleshooting с таймером
- [ ] Провёл chaos-час: 5 неизвестных поломок, все найдены и починены
- [ ] Написал `troubleshooting-playbook.md` своими словами
- [ ] Все 5 экспериментов «Ломаем специально» проделаны
- [ ] `notes/week-08.md` заполнен

---

## 🏁 Контрольная точка месяца 2

Честная самооценка перед переходом к Helm:

- [ ] Могу собрать кластер с нуля и объяснить роль каждого компонента
- [ ] Могу восстановить etcd из бэкапа без подглядывания в документацию
- [ ] Диагностирую любую из типовых поломок за 10 минут
- [ ] Могу нарисовать путь пакета от клиента до контейнера и объяснить каждое звено
- [ ] Настраиваю RBAC с минимальными правами, а не `cluster-admin`
- [ ] Управляю размещением подов и настраиваю автоскейлинг под нагрузку

**Если всё закрыто — ты уже прошёл больше половины требований типовой вакансии на Kubernetes.** Дальше начинается то, что превращает знание Kubernetes в промышленную доставку: Helm и GitOps.

**Практическое действие прямо сейчас:** открой 20 вакансий уровня выше твоего текущего и выпиши все незнакомые слова. Половина из них попадёт в месяцы 4–5 плана, оставшиеся — это твой персональный список на месяцы 7–8.
