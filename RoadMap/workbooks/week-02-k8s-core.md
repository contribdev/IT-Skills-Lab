Описать основные сущности

Описать работу kubectl apply

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





