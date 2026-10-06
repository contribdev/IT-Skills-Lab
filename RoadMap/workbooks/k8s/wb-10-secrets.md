Kubernetes Secrets

Secret — объект Kubernetes для хранения чувствительных данных: паролей, токенов, SSH-ключей, сертификатов.

Отличие от ConfigMap:

                   ConfigMap	      Secret
Данные	          Обычные конфиги	 Чувствительные
Хранение в etcd	  Plaintext	         Base64 (по умолчанию)
Размер	          до 1 MiB	         до 1 MiB
Шифрование	      Нет	             Возможно (EncryptionConfiguration)

base64 — это не шифрование, а кодирование. По умолчанию секреты в etcd лежат в открытом виде. Для реальной защиты нужно настроить EncryptionConfiguration на API-сервере.

Типы Secret
Тип	                                    Назначение
Opaque	                                По умолчанию, произвольные данные
kubernetes.io/service-account-token	    Токен ServiceAccount
kubernetes.io/dockerconfigjson	        Доступ к Docker registry
kubernetes.io/basic-auth	            Логин/пароль
kubernetes.io/ssh-auth	                SSH-ключи
kubernetes.io/tls	                    TLS-сертификат и ключ

как использовать:
```
spec:
  containers:
  - name: app
    image: nginx
    env:
    - name: USERNAME
      valueFrom:
        secretKeyRef:
          name: my-secret
          key: username
    envFrom:
    - secretRef:
        name: my-secret   # все ключи сразу
```

Практика: использование Secrets для получения образа из приватного регистри ghcr

kubectl create namespace ai-doc-platform

kubectl create secret docker-registry ghcr-secret \
    --docker-server=ghcr.io \
    --docker-username=$GH_USER \
    --docker-password=$GH_PAT \
    --namespace=ai-doc-platform

Использование декларативным способом:
apiVersion: v1
kind: Pod
metadata:
  name: "test-private-pull"
  namespace: ai-doc-platform
  labels:
    app: "MYAPP"
spec:
  restartPolicy: Never
  imagePullSecrets:
  - name: ghcr-secret
  containers:
  - name: test
    image: "ghcr.io/contribdev/ai-document-platform-api:0.1.0"
    command: ["sh", "-c", "echo 'Private pull OK'"]

Использование в helm charts:

apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Release.Name}}-deployment
  labels:
    app: {{ .Release.Name}}-deployment
spec:
  replicas: {{ .Values.replicaCount }}
  selector:
    matchLabels:
      project: {{ .Release.Name}}-deployment
  template:
    metadata:
      labels:
        project: {{ .Release.Name}}-deployment
    spec:
      {{- with .Values.imagePullSecrets }}
      imagePullSecrets:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      containers:
        - name: {{ .Release.Name}}-deployment
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          command: ["sh", "-c", "echo 'Private pull OK'"]

