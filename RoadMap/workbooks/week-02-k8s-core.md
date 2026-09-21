Описать основные сущности

Namespace
  └── Deployment
        └── ReplicaSet
              └── Pod (1..N)
                    └── Container (1..N)

Control Plane (управляет всем)
  ├── kube-apiserver
  ├── etcd
  ├── kube-scheduler
  └── kube-controller-manager

Node (где всё работает)
  ├── kubelet
  ├── kube-proxy
  └── container runtime

Control Plane - набор компонентов, которые управляют кластром. Включает в себя:
*kube-apiserver - единственная точка входа в кластер, принимает все запросы от клиентов (kubelet, контроллеров, kubectl), проверяет права, ввалидирует объекты и сохраняет их в etcd
*etcd - key-value-хранилище, единственное место, где хранится состояние кластера
*kube-scheduler - компонент, распределяющий поды по нодам, учитывая ресурсы
*kube-controller-manager - набор контроллеров, которые следят за тем, чтобы текущее состояние совпадало с желаемым (Deployment Controller, ReplicaSet Controller, Node Controller и т.д.)
*cloud-controller-manager - интеграция с облачным провайдером

node - рабочая машина, на которой реально запускается под. На каждой ноде работают:
*kubelet - агент, который получает от API Server список под, назначенных на эту ноду и следит за их жизненным циклом (запуск, остановка, health check)
*kube-proxy - отвечает за сетевые правила: маршрутизация трафика к Pod через Service
*container runtime - то, что реально запускает контейнеры
Если нода падает, её Pods через некоторое время пересоздаются на других нодах (этим занимается Node Controller + ReplicaSet)

pod - обертка над одним или несколькими контейнерами, которые:
*делят общую сеть (один IP, один network namespace),
*могут делить общие тома (volumes),
*всегда запускаются и умирают вместе на одной ноде.
Pod — эфемерная сущность: если он упал, Kubernetes не «лечит» его, а создаёт новый.

ReplicaSet - объект, который следит за тем, чтобы в кластере всегда было запущено заданное количество реплик Pod'а.
У ReplicaSet есть:
*replicas — желаемое количество,
*selector — по каким лейблам он находит «свои» Pods,
*template — шаблон, по которому создаются новые Pods.
ReplicaSet обычно не создают вручную — его создаёт Deployment. Deployment управляет ReplicaSet'ами, а ReplicaSet — Pods.

hpa - это Horizontal Pod Autoscaler, отдельный объект Kubernetes, который автоматически меняет количество реплик в Deployment'е в зависимости от нагрузки (CPU, память, кастомные метрики).

deployments - объект для управления stateless-приложениями. Он описывает:
*какой образ использовать,
*сколько реплик нужно,
*как обновлять приложение (стратегия RollingUpdate / Recreate),
*историю версий (revision history) для отката.

Namespace — это логическое разделение кластера на изолированные «виртуальные кластеры» внутри одного физического. Namespace'ы позволяют:
*разделять ресурсы между командами / проектами / средами (dev / staging / prod),
*ограничивать квоты (ResourceQuota) и права (RBAC) в рамках одного namespace,
*избегать конфликтов имён (в разных namespace можно создать Pod с одинаковым именем).


Services — это абстракция, которая даёт стабильную точку доступа к группе Pod'ов (Deployments). Pods эфемерны: у них меняются IP-адреса при пересоздании, их количество меняется при скейлинге и rolling update.
Service, как и ReplicaSet, использует label selector. Он не привязан к Deployment'у или ReplicaSet'у — он просто выбирает все Pods с нужными лейблами в своём namespace.
Четыре типа Service
1. ClusterIP (по умолчанию)
Доступ только внутри кластера. Даёт виртуальный IP, по которому Pods общаются между собой. Снаружи недоступен.
Для чего: frontend → backend → database.
2. NodePort
Открывает один и тот же порт (30000–32767) на всех нодах. Трафик на <NodeIP>:<NodePort> идёт на Pods.
Для чего: быстрый доступ снаружи для тестов. Минусы — случайный порт, ноды должны быть доступны.
3. LoadBalancer
Создаёт NodePort + внешний балансировщик от облачного провайдера (ELB, GLB и т.д.).
Для чего: продакшн-доступ снаружи. В k3s эмулируется через Klipper LB.
4. ExternalName
Не проксирует трафик, а просто возвращает CNAME-запись в DNS на внешний сервис.
Для чего: чтобы Pods обращались к внешней БД по внутреннему имени.

Pods

Pod - минимальная единица развертывания в k8s

Создание подов
для быстрого создания пода можно использовать императивную команду 

kubectl run nginx --image=nginx:latest --port=80

В таком случае создасться объект типа deployment, нужен именно Pod:
kubectl run nginx --image=nginx:latest --port=80 --restart=Never

pod/nginx created


Рекомендуемый способ создавать поды - декларативный yaml
Файл можно пресоздать автоматически с помощью kubectl run, но без создания пода, только генерация файла

kubectl run nginx --image=nginx:latest --port=80 --restart=Never --dry-run=client -o yaml > ./src/pods/nginx.yaml

apiVersion: v1
kind: Pod
metadata:
  labels:
    run: nginx
  name: nginx
spec:
  containers:
  - image: nginx:latest
    name: nginx
    ports:
    - containerPort: 80
    resources: {}
  dnsPolicy: ClusterFirst
  restartPolicy: Never
status: {}

Далее используем этот файл для поднятия пода
kubectl apply -f src/pods/nginx.yaml 
pod/nginx created

Как запустить команду на поде
kubectl exec -it nginx -- sh

Посмотреть лог контейнера
kubectl logs nginx

Для доступа к сервису необходимо делать порт форвардинг
kubectl port-forward nginx 7788:80
Forwarding from 127.0.0.1:7788 -> 80
Forwarding from [::1]:7788 -> 80

![alt text](pict\welcome_to_nginx.png)

При указании containerPort важно понимать, что необходимо указывать порт, который реально слушается приложением, иначе порт форвард разоврвется


Deployments

Deployment - обеспечивает создание ReplicaSet и обновление в них подов

Создание Deployment
kubectl create deployment my-nginx --image nginx:latest

Скейлинг - расширение подов

kubectl scale deployment nginx-deployments --replicas 3
deployment.apps/nginx-deployments scaled
cheaster@DESKTOP-BIHDH0E:/mnt/c/Users/Dmitry/Desktop/projects/IT-Skills-Lab$ kubectl get deploy
NAME                READY   UP-TO-DATE   AVAILABLE   AGE
nginx-deployments   3/3     3            3           4m16s
cheaster@DESKTOP-BIHDH0E:/mnt/c/Users/Dmitry/Desktop/projects/IT-Skills-Lab$ kubectl get pods
NAME                               READY   STATUS    RESTARTS   AGE
nginx-deployments-5ccf7dc5-5qtcx   1/1     Running   0          59s
nginx-deployments-5ccf7dc5-cwj5n   1/1     Running   0          59s
nginx-deployments-5ccf7dc5-svc4q   1/1     Running   0          5m2s

При создании Deployments автоматически создается ReplicaSet

cheaster@DESKTOP-BIHDH0E:/mnt/c/Users/Dmitry/Desktop/projects/IT-Skills-Lab$ kubectl get rs
NAME                         DESIRED   CURRENT   READY   AGE
nginx-deployments-5ccf7dc5   3         3         3       6m14s

Если убить один под, то replicaset создаст новый

cheaster@DESKTOP-BIHDH0E:/mnt/c/Users/Dmitry/Desktop/projects/IT-Skills-Lab$ kubectl delete pods nginx-deployments-5ccf7dc5-svc4q
pod "nginx-deployments-5ccf7dc5-svc4q" deleted from default namespace
cheaster@DESKTOP-BIHDH0E:/mnt/c/Users/Dmitry/Desktop/projects/IT-Skills-Lab$ kubectl get pods
NAME                               READY   STATUS    RESTARTS   AGE
nginx-deployments-5ccf7dc5-5qtcx   1/1     Running   0          2m51s
nginx-deployments-5ccf7dc5-cwj5n   1/1     Running   0          2m51s
nginx-deployments-5ccf7dc5-gc2fb   1/1     Running   0          3s

Команда autoscale создает сущность hpa

Процесс изменения Deployment
В процессе будет изменен контейнер, поэтому необходимо получить его имя (nginx)

cheaster@DESKTOP-BIHDH0E:/mnt/c/Users/Dmitry/Desktop/projects/IT-Skills-Lab$ kubectl set image deployments nginx-deployments nginx=nginx:1.26.0
deployment.apps/nginx-deployments image updated

cheaster@DESKTOP-BIHDH0E:/mnt/c/Users/Dmitry/Desktop/projects/IT-Skills-Lab$ kubectl rollout status deployment nginx-deployments 
Waiting for deployment "nginx-deployments" rollout to finish: 1 out of 2 new replicas have been updated...
Waiting for deployment "nginx-deployments" rollout to finish: 1 out of 2 new replicas have been updated...
Waiting for deployment "nginx-deployments" rollout to finish: 1 out of 2 new replicas have been updated...
Waiting for deployment "nginx-deployments" rollout to finish: 1 old replicas are pending termination...
Waiting for deployment "nginx-deployments" rollout to finish: 1 old replicas are pending termination...
Waiting for deployment "nginx-deployments" rollout to finish: 1 old replicas are pending termination...
deployment "nginx-deployments" successfully rolled out

Вернуться на определенную версию Deployment 
cheaster@DESKTOP-BIHDH0E:/mnt/c/Users/Dmitry/Desktop/projects/IT-Skills-Lab$ kubectl rollout undo deployment nginx-deployments --to-revision=3


```
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-web-app
  labels:
    app: my-k8s-web-app
spec:
  selector:
    matchLabels:
      project: kgb
  template:
    metadata:
      labels:
        project: kgb
    spec:
      containers:
        - name: kgb-web
          image: nginx:latest
          ports:
            - containerPort: 80
   
```

Services

Services - объект, обеспечивающий стабильный доступ к приложениям, запущенным в подах. Бывают 4 видов:
 - ClusterIP - Общение сервисов внутри кластера
 - NodePort - Быстрый доступ снаружи для тестов
 - LoadBalancer - Продакшн-доступ снаружи (в облаке)
 - ExternalName - Прокси к внешнему сервису


1) kubectl expose deployment my-web-autoscaling --type=ClusterIP --port 80
service/my-web-autoscaling exposed

kubectl get service
NAME                 TYPE        CLUSTER-IP    EXTERNAL-IP   PORT(S)   AGE
kubernetes           ClusterIP   10.43.0.1     <none>        443/TCP   12m
my-web-autoscaling   ClusterIP   10.43.12.88   <none>        80/TCP    32s

Если зайти на одну из нод и выполнить запрос к ClusterIP увидим развернутое приложение 

```
k8s-user@node-1:~$ curl 10.43.12.88
<!DOCTYPE html>
<html>
<head>
<title>Welcome to nginx!</title>
<style>
html { color-scheme: light dark; }
body { width: 35em; margin: 0 auto;
font-family: Tahoma, Verdana, Arial, sans-serif; }
</style>
</head>
<body>
<h1>Welcome to nginx!</h1>
<p>If you see this page, the nginx web server is successfully installed and
working. Further configuration is required.</p>

<p>For online documentation and support please refer to
<a href="http://nginx.org/">nginx.org</a>.<br/>
Commercial support is available at
<a href="http://nginx.com/">nginx.com</a>.</p>

<p><em>Thank you for using nginx.</em></p>
</body>
</html>
```

2) kubectl expose deployment my-web-autoscaling --type=NodePort --port=80
service/my-web-autoscaling exposed

kubectl get service
NAME                 TYPE        CLUSTER-IP     EXTERNAL-IP   PORT(S)        AGE
kubernetes           ClusterIP   10.43.0.1      <none>        443/TCP        19m
my-web-autoscaling   NodePort    10.43.30.188   <none>        80:31261/TCP   26s

Открыт порт 80:31261 на всех нодах

Теперь можно обращаться по http://192.168.100.11:31261/

3) kubectl expose deployment my-web-autoscaling --type=LoadBalancer --port=80
service/my-web-autoscaling exposed
(моя лаборатория развернута в гипервизоре, а не в облаке, но в k3s встроен LB Klipper, который и позволяет создавать LB Services)

kubectl get svc
NAME                 TYPE           CLUSTER-IP      EXTERNAL-IP                                    PORT(S)        AGE
kubernetes           ClusterIP      10.43.0.1       <none>                                         443/TCP        30m
my-web-autoscaling   LoadBalancer   10.43.200.204   192.168.100.11,192.168.100.12,192.168.100.13   80:31298/TCP   7s

Тогда http://192.168.100.12/ приводит на страницу к моемк приложению

Декларативный метод создания 
При создании манифеста необходимо помнить, что Service селектит не деплойменты, а поды, поэтому необходимо указывать лейбл пода
см. src\services\service-3-lb-autoscaling.yaml

#TODO
- Почему автоскейлинг может работать без селектинга?
Автоскейлинг работает через поле:
scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: avengers-app-deployment-autoscaling  <-- имя Deployment


- Полный путь kubectl apply по шагам
kubectl apply — это декларативный способ управления объектами.
Шаг 1. kubectl читает YAML-файл и определяет apiVersion, kind, namespace, name объекта.

Шаг 2. Проверка существования объекта (клиент → API Server)
kubectl делает GET-запрос к API Server: есть ли уже объект с таким именем?
Если объекта нет → будет создан (POST).
Если объект есть → будет обновлён (PATCH).

Шаг 3. Трёхстороннее слияние (Client-Side Apply)
Если объект существует, kubectl читает из кластера аннотацию kubectl.kubernetes.io/last-applied-configuration (это предыдущий применённый YAML) и выполняет three-way merge:
*последний применённый конфиг (что мы хотели раньше),
*новый конфиг из файла (что мы хотим сейчас),
*текущее состояние в кластере (что реально есть).
На основе этого вычисляется patch — какие поля добавить, изменить или удалить.

Шаг 4. Отправка запроса на API Server
kubectl отправляет POST (создание) или PATCH (обновление) на API Server.

Шаг 5. бработка на стороне API Server
Запрос проходит три стадии:
Аутентификация — кто ты? (сертификат, токен, OIDC).
Авторизация — можно ли тебе это? (RBAC: Role / ClusterRole + Binding).
Admission Controllers — можно ли так делать? Здесь работают:
Mutating — могут менять объект (например, автоматически проставлять resources, инжектить sidecar).
Validating — могут только отклонять (например, проверять, что образ из доверенного registry).

Шаг 6. Запись в etcd
Если всё прошло успешно, объект сохраняется в etcd — это единственное место, где хранится состояние кластера.

Шаг 7. Реакция контроллеров через Watch
Все компоненты (Scheduler, Controller Manager, kubelet) подписаны на изменения через Watch API. Как только объект записан, событие рассылается:
Scheduler видит Pending Pod → выбирает ноду → записывает в spec.nodeName.
kubelet на этой ноде видит, что Pod назначен ему → тянет образ → запускает контейнер.
Deployment Controller видит новый Deployment → создаёт ReplicaSet → тот создаёт Pods.
Итог: kubectl apply = отправить желаемое состояние → API Server проверил и сохранил → контроллеры через Watch привели реальность к этому состоянию.

- рассказать принцип взаимодействия клиентов с API сервером
API Server — это единственная точка входа (мозг: принимает и проверяет) и единственный источник событий (почта: хранит в etcd и рассылает через Watch). Все остальные компоненты — пассивные подписчики, которые реагируют на изменения и делают свою часть работы. Именно поэтому Kubernetes — это не монолит, а набор слабосвязанных контроллеров, объединённых вокруг API Server.

                       ┌─────────────────────┐
   kubectl apply ─────▶│                     │
                       │    API Server       │
   Scheduler ◀──Watch──│  (мозг + почта)     │──▶ etcd (хранит состояние)
   Controller ◀─Watch──│                     │
   kubelet   ◀──Watch──│  authn → authz →    │
   kube-proxy ◀─Watch──│  admission → etcd   │
                       └─────────────────────┘
                              │
                              ▼
                    Watch-события (ADDED/MODIFIED/DELETED)
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
   Scheduler             Controllers            kubelet
   (выбирает ноду)    (создаёт Pods)      (запускает контейнеры)

   Watch-события — это поток изменений объектов (ADDED / MODIFIED / DELETED), который API Server пушит подписчикам через долгоживущее соединение. Именно на нём держится вся event-driven архитектура Kubernetes: Scheduler, контроллеры и kubelet не опрашивают кластер, а реагируют на события, превращая декларации в реально работающие Pods.

- что такое stateless приложения

Stateless (без состояния) — это приложение, которое не хранит данные между запросами. Каждый запрос обрабатывается независимо, и результат зависит только от того, что пришло в этом запросе. Приложение не помнит, что было раньше.

Противоположность — stateful (с состоянием): приложение помнит предыдущие взаимодействия и хранит данные, которые влияют на будущие запросы.