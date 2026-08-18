# Неделя 1 — Docker вглубь

**Цель недели:** перейти от «умею запускать контейнеры» к «понимаю, как они устроены, и умею собирать продовый образ».
**Время:** 10–11 часов (3 ч теории, 7–8 ч практики).

Ты почти наверняка уже пользуешься Docker. Соблазн пропустить неделю велик — не надо. Половина проблем в Kubernetes (CrashLoopBackOff, зависшие поды при удалении, раздутые образы, странности с правами на файлы) — это на самом деле проблемы образа и процесса внутри, а не Kubernetes.

---

## 📖 Теория

### 1. Контейнер — это не виртуалка, а процесс с ограничениями

Три механизма ядра Linux:

**Namespaces — изоляция видимости.** Процесс видит только своё:
- `pid` — своё дерево процессов (в контейнере твоё приложение имеет PID 1)
- `net` — свой сетевой стек, интерфейсы, таблица маршрутизации
- `mnt` — своё дерево монтирования
- `uts` — свой hostname
- `ipc` — своя разделяемая память
- `user` — своё отображение UID/GID (в Docker по умолчанию **не используется**, отсюда многие проблемы безопасности)

**cgroups — ограничение потребления.** CPU, память, IO, количество процессов. Именно cgroups превращают `--memory=512m` в реальный лимит, а превышение — в OOM-kill.

**Union filesystem (overlay2) — слои.** Образ = стек read-only слоёв. Контейнер = этот стек + один writable слой сверху. Отсюда следствия, которые нужно понимать:
- Удаление файла в верхнем слое не уменьшает образ — файл всё ещё лежит в нижнем слое (whiteout-запись просто прячет его).
- Данные в writable-слое исчезают вместе с контейнером → нужны volumes.

Проверь сам:

```bash
docker run -d --name test nginx
sudo ls -l /proc/$(docker inspect -f '{{.State.Pid}}' test)/ns/
# увидишь ссылки на namespaces
```

### 2. Слои и кэш сборки — почему порядок инструкций критичен

Каждая инструкция `RUN`, `COPY`, `ADD` создаёт слой. Docker кэширует слои и переиспользует их, пока не изменится **инструкция или её входные данные**. Как только один слой инвалидирован — все последующие пересобираются.

**Плохо:**
```dockerfile
COPY . /app
RUN pip install -r requirements.txt
```
Изменил одну строку в коде → инвалидировался `COPY` → заново ставятся все зависимости. Сборка 3 минуты вместо 5 секунд.

**Хорошо:**
```dockerfile
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app
```
Зависимости пересобираются только при изменении `requirements.txt`.

Правило: **от редко меняющегося к часто меняющемуся.**

### 3. Multi-stage build

Разделяем «что нужно для сборки» и «что нужно для запуска». Компилятор, dev-заголовки, тестовые зависимости не должны попадать в финальный образ — это и размер, и площадь атаки.

```dockerfile
FROM python:3.12-slim AS builder
WORKDIR /app
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim AS runtime
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /app
COPY . .
CMD ["python", "-m", "myservice"]
```

### 4. PID 1, сигналы и почему поды «долго удаляются»

Процесс с PID 1 в Linux имеет особый статус: **ядро не применяет к нему обработчики сигналов по умолчанию**. Если твоё приложение не обрабатывает SIGTERM явно, оно его просто проигнорирует. Docker (и Kubernetes) подождут grace period, а потом убьют SIGKILL.

Отсюда классический симптом: `kubectl delete pod` висит 30 секунд, а запросы в момент удаления теряются.

Второй нюанс — **форма инструкции**:

```dockerfile
CMD python app.py          # shell-форма → запускается /bin/sh -c "python app.py"
                           # PID 1 = sh, сигналы до python не доходят
CMD ["python", "app.py"]   # exec-форма → PID 1 = python. Правильно.
```

Всегда используй exec-форму (JSON-массив).

Третий нюанс — **зомби-процессы**. Если приложение порождает дочерние процессы, PID 1 обязан их reaping'ом заниматься. Python этого не делает. Решение — `tini`:

```dockerfile
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "app.py"]
```
(в Docker есть флаг `--init`, в Kubernetes — нет, поэтому tini кладут в образ).

### 5. ENTRYPOINT vs CMD

| | Назначение | Переопределяется |
|---|---|---|
| `ENTRYPOINT` | что запускать (неизменяемая часть) | `--entrypoint` |
| `CMD` | аргументы по умолчанию | аргументами после имени образа |

Продовый паттерн: `ENTRYPOINT ["/app/entrypoint.sh"]` + `CMD ["serve"]`. Тогда `docker run myimage migrate` запустит миграции тем же образом.

В Kubernetes: `command` в манифесте перекрывает `ENTRYPOINT`, `args` перекрывает `CMD`. Путаница между ними — частая причина CrashLoopBackOff.

### 6. Non-root и права на файлы

По умолчанию контейнер работает от root. Это плохо: root в контейнере = root на хосте при выходе из изоляции (user namespace, напомню, по умолчанию выключен).

```dockerfile
RUN useradd -u 10001 -m appuser
USER 10001
```

Числовой UID указывать важно: в Kubernetes `runAsNonRoot: true` умеет проверить только числовой UID, а имя пользователя оно не резолвит.

⚠️ **Классическая боль:** приложение под non-root не может писать в свой рабочий каталог, потому что `COPY` положил файлы от root. Лечится `COPY --chown=10001:10001` или явным `chmod`.

### 7. Что попадает в образ: .dockerignore

Без `.dockerignore` в build context уезжает `.git` (иногда сотни мегабайт), `venv`, `node_modules`, локальные `.env` **с секретами**. Секреты в слоях образа — это утечка, которую не исправить последующим `RUN rm`.

```
.git
.venv
__pycache__
*.pyc
.env
tests/
.pytest_cache
```

### 8. Registry и OCI

Образ в реестре — это манифест (JSON) + слои (blob'ы), адресуемые по sha256. «Docker-образ» и «OCI-образ» сегодня практически синонимы: формат стандартизован, поэтому containerd в Kubernetes прекрасно запускает образы, собранные Docker.

Практическое следствие для тебя: **Artifactory умеет быть OCI-registry**, и туда же можно класть Helm-чарты (неделя 11). Это прямая точка входа для рабочих задач.

---

## 🔧 Задание 1: препарируем существующий образ (1 ч)

```bash
docker pull python:3.12
docker pull python:3.12-slim
docker images | grep python           # сравни размеры

docker history python:3.12-slim       # посмотри слои
docker inspect python:3.12-slim | jq '.[0].Config'
```

Поставь **dive** и разбери любой большой образ:

```bash
dive python:3.12
```

Найди в нём слои, где место тратится впустую. Запиши вывод в журнал.

🔗 [dive](https://github.com/wagoodman/dive)

---

## 🔧 Задание 2: наивный образ своего сервиса (1 ч)

Возьми **свой реальный Python-сервис** — тот, что ходит в Jira/Artifactory. Если он завязан на корпоративную сеть, сделай урезанную версию: FastAPI с парой эндпоинтов + обращение к внешнему API.

Напиши Dockerfile «в лоб», как получится. Собери, замерь:

```bash
docker build -t myservice:naive .
docker images myservice:naive
```

Затем поменяй одну строку в коде и пересобери. Засеки время. Запиши обе цифры — это твоя точка отсчёта.

---

## 🔧 Задание 3: оптимизируем (2.5 ч)

Приведи Dockerfile к продовому виду. Целевой результат:

- **Размер < 150 МБ**
- **Пересборка при изменении кода < 10 секунд**
- non-root пользователь
- exec-форма CMD
- HEALTHCHECK
- корректный `.dockerignore`

Эталон, к которому стоит прийти:

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install -r requirements.txt


FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -u 10001 -m appuser

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=10001:10001 . .

USER 10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "myservice.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

⚠️ `PYTHONUNBUFFERED=1` — обязательно. Без него логи Python буферизуются и не появляются в `docker logs` / `kubectl logs` вовремя. Это одна из самых частых причин «а почему у меня логов нет».

**Дополнительно попробуй:** BuildKit cache mounts, они ускоряют сборку ещё сильнее:

```dockerfile
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt
```

---

## 🔧 Задание 4: graceful shutdown (1.5 ч)

Добавь в сервис корректную обработку SIGTERM. Для FastAPI/uvicorn это работает из коробки, но проверить надо явно. Для собственного цикла:

```python
import signal, threading

shutdown = threading.Event()

def handle_sigterm(signum, frame):
    print("SIGTERM received, draining...", flush=True)
    shutdown.set()

signal.signal(signal.SIGTERM, handle_sigterm)

while not shutdown.is_set():
    do_work()
    shutdown.wait(timeout=1)

print("Clean exit", flush=True)
```

Проверка:

```bash
docker run -d --name svc myservice:prod
time docker stop svc      # должно быть ~1 сек, а не 10
```

💥 Специально убери обработчик и повтори — увидишь ровно 10 секунд (дефолтный grace period Docker). Это то же поведение, которое на неделе 3 даст тебе потерю запросов при rolling update.

---

## 🔧 Задание 5: docker-compose как локальная среда (1.5 ч)

```yaml
services:
  app:
    build: .
    ports: ["8000:8000"]
    environment:
      DATABASE_URL: postgresql://app:secret@db:5432/app
      REDIS_URL: redis://cache:6379/0
    depends_on:
      db: { condition: service_healthy }
      cache: { condition: service_started }

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: app
      POSTGRES_PASSWORD: secret
      POSTGRES_DB: app
    volumes: ["pgdata:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app"]
      interval: 5s
      retries: 5

  cache:
    image: redis:7-alpine

volumes:
  pgdata:
```

Задачи:
1. Подними стек, убедись, что приложение видит БД по имени сервиса (внутренний DNS Compose — прямая аналогия Service DNS в Kubernetes).
2. Удали контейнер БД, подними заново — данные должны сохраниться.
3. Удали volume — данные должны пропасть. Осознай разницу.

---

## 🔧 Задание 6: сборка в Jenkins и публикация в Artifactory (2 ч) — *делается на работе*

Это задание из плана «протащить на текущей работе». Даже если у вас уже есть похожий пайплайн — сделай свой, с нуля, чтобы понимать каждый шаг.

```groovy
pipeline {
  agent any
  environment {
    REGISTRY = 'artifactory.company.com/docker-local'
    IMAGE    = "${REGISTRY}/myservice"
    TAG      = "${env.GIT_COMMIT.take(8)}"
  }
  stages {
    stage('Build') {
      steps { sh 'docker build -t $IMAGE:$TAG .' }
    }
    stage('Scan') {
      steps { sh 'trivy image --exit-code 1 --severity HIGH,CRITICAL $IMAGE:$TAG' }
    }
    stage('Push') {
      steps {
        withCredentials([usernamePassword(credentialsId: 'artifactory',
                          usernameVariable: 'U', passwordVariable: 'P')]) {
          sh 'echo $P | docker login $REGISTRY -u $U --password-stdin'
          sh 'docker push $IMAGE:$TAG'
        }
      }
    }
  }
}
```

Ключевые моменты для обсуждения с командой:
- **Тег = git sha, а не `latest`.** Immutable-теги — обязательное условие для GitOps на неделе 12.
- Сканирование Trivy на этапе сборки — это заготовка к неделе 17.

---

## 💥 Ломаем специально

1. Собери образ, в котором `CMD` в shell-форме, и убедись, что `docker stop` занимает 10 секунд.
2. Запусти контейнер с `--memory=50m` для приложения, которому нужно 200 МБ. Поймай OOM: `docker inspect <id> | jq '.[0].State'` → `OOMKilled: true`.
3. Положи в образ файл с «секретом», потом добавь `RUN rm secret.txt` следующим слоем. Найди секрет в слоях через `dive` или `docker save` + распаковку tar. Вывод: секреты в слоях остаются навсегда.
4. Собери образ от root, потом добавь `USER 10001` — и увидь, как приложение падает на попытке записи в свою же директорию. Почини через `--chown`.

Всё это — записи в `notes/week-01.md`.

---

## ❓ Самопроверка

1. Три механизма ядра, на которых стоит контейнеризация. Что делает каждый?
2. Почему `RUN rm -rf /var/lib/apt/lists/*` нужно писать **в той же** инструкции `RUN`, что и `apt-get install`?
3. В чём разница shell-формы и exec-формы `CMD`? К какому симптому в Kubernetes приводит ошибка?
4. Что перекрывает `command` в манифесте пода — `ENTRYPOINT` или `CMD`?
5. Почему `runAsNonRoot: true` требует числового UID в образе?
6. Приложение не пишет логи в `kubectl logs`, хотя в консоли локально всё видно. Первая гипотеза?
7. Чем `COPY` отличается от `ADD` и почему `ADD` не рекомендуют?
8. Зачем нужен `tini`, если приложение однопроцессное?

---

## 🔗 Ссылки

| Ресурс | Зачем |
|---|---|
| [Docker: Building best practices](https://docs.docker.com/build/building/best-practices/) | Официальный свод правил |
| [Docker: Multi-stage builds](https://docs.docker.com/build/building/multi-stage/) | Основной приём недели |
| [BuildKit cache mounts](https://docs.docker.com/build/cache/optimize/) | Ускорение сборки |
| [dive](https://github.com/wagoodman/dive) | Анализ слоёв |
| [tini](https://github.com/krallin/tini) | Проблема PID 1 |
| [Ivan Velichko: контейнеры изнутри](https://iximiuz.com/en/posts/container-learning-path/) | Лучшее объяснение namespaces/cgroups |
| [OCI Image Spec](https://github.com/opencontainers/image-spec) | Что такое образ формально |
| [Google: Distroless](https://github.com/GoogleContainerTools/distroless) | Следующий шаг по минимизации |

---

## ✅ Чек-лист недели

- [ ] Образ своего сервиса: **< 150 МБ**, пересборка при изменении кода **< 10 сек**
- [ ] Multi-stage, non-root (числовой UID), exec-форма CMD, tini, HEALTHCHECK
- [ ] `.dockerignore` написан, `.git` и секреты в контекст не попадают
- [ ] SIGTERM обрабатывается, `docker stop` завершается за ~1 секунду
- [ ] docker-compose со стеком app + postgres + redis работает, данные переживают пересоздание контейнера
- [ ] Пайплайн сборки и публикации в registry с тегом по git sha
- [ ] Trivy встроен в сборку (пока можно без блокировки)
- [ ] Все 4 эксперимента из «Ломаем специально» проделаны и записаны
- [ ] `01-docker/` в репозитории содержит Dockerfile, compose и README с цифрами «до/после»
