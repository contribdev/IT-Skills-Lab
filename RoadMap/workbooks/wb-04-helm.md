Helm — это пакетный менеджер для Kubernetes. Он позволяет устанавливать, обновлять и удалять приложения одним командным действием, а не вручную применять десятки YAML-файлов.

Чарт — это директория с фиксированной структурой :

mychart/
├── Chart.yaml          # метаданные чарта
├── values.yaml         # значения по умолчанию
├── charts/             # зависимые чарты (subcharts)
├── templates/          # шаблоны манифестов
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── _helpers.tpl    # вспомогательные шаблоны
│   └── NOTES.txt       # текст справки после установки
└── values.schema.json  # (опционально) схема валидации values

Chart.yaml — обязательные поля

apiVersion: v2          # обязательно для Helm 3
name: my-app            # имя чарта (только строчные буквы, цифры, дефисы)
version: 0.1.0          # версия чарта (SemVer, меняется при каждом изменении)
appVersion: "1.16.0"    # версия приложения (независима от версии чарта)
description: "My first chart"
type: application        # "application" или "library"

name не может содержать заглавные буквы — Helm отклонит такой чарт, что у меня и случилось

templates/ — шаблоны
Helm использует Go template с дополнительными функциями из библиотеки Sprig . В шаблонах доступны:

.Values — значения из values.yaml
.Release.Name — имя релиза
.Release.Namespace — namespace
.Chart.Name — имя чарта

Пример templates/deployment.yaml:

apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Release.Name }}-deployment
spec:
  replicas: {{ .Values.replicaCount }}
  template:
    spec:
      containers:
      - name: {{ .Chart.Name }}
        image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"

Шпаргалка команд

# Установка
helm install <release> <chart> -f values.yaml --atomic --timeout 5m
# Обновление
helm upgrade <release> <chart> -f values.yaml --atomic
# Откат
helm rollback <release> <revision>
# История
helm history <release>
# Список релизов
helm list -A
# Удаление
helm uninstall <release>
# Отладка
helm lint <chart>
helm template <release> <chart> --debug
helm install <release> <chart> --dry-run --debug
helm get manifest <release>
