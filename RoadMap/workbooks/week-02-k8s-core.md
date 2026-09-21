Описать основные сущности

cp

node

pod

ReplicaSet

hpa - это Horizontal Pod Autoscaler, отдельный объект Kubernetes, который автоматически меняет количество реплик в Deployment'е в зависимости от нагрузки (CPU, память, кастомные метрики).

deployments

Namespace

Services



Описать работу kubectl apply


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
При создании манифеста необходимо помнить, что Service селектит не деплойменты, а поды, поэтому необходимо указывать лейб пода


#TODO
Почему автоскейлинг может работать без селектинга?






