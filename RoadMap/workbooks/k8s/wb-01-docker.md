Три механизма Linux, которые выполняют ограничения процесса контейнера:
- Изоляция видимости. Процесс видит только свое
- Ограничения потребления - cgroups
- Слои. Образ = стек read-only слоёв. Контейнер = этот стек + один writable слой сверху.

Каждая инструкция `RUN`, `COPY`, `ADD` создаёт слой. Docker кэширует слои и переиспользует их, пока не изменится **инструкция или её входные данные**. Как только один слой инвалидирован — все последующие пересобираются.

Полезные ENV для использования python

1. PYTHONDONTWRITEBYTECODE=1
Python не создаёт .pyc файлы (байткод).
-В контейнере — нет смысла кэшировать байткод.** Каждый запуск — новый контейнер.
-Меньше мусора в образе.
-Чуть быстрее старт (не тратит время на запись).
Без него: Python создаёт __pycache__/ при импорте — лишние файлы.

2. PYTHONUNBUFFERED=1
stdout/stderr не буферизуются — пишутся сразу.
-Логи видны мгновенно.** K8s читает stdout — важна скорость.
-Без него: логи буферизуются — видишь только при закрытии процесса (или большими блоками).
-Для отладки — критично в K8s.

3. PIP_DISABLE_PIP_VERSION_CHECK=1
pip не проверяет новую версию себя в PyPI.
-Экономит время сборки (не ходит в сеть лишний раз
-Убирает шум в логах


Практика для Python-проектов:
-Всегда копируй сначала requirements.txt / pyproject.toml / uv.lock.
-Устанавливай зависимости.
-Потом копируй код.


CMD vs ENTRYPOINT
CMD — «команда по умолчанию»
Что это: что запускать, если пользователь не указал свою команду.
Можно переопределить в docker run:
# CMD в Dockerfile: ["python", "app.py"]
docker run myimage                    # запустит python app.py
docker run myimage python other.py    # запустит python other.py
docker run myimage bash               # запустит bash

ENTRYPOINT — «основная команда»
Что это: что запускать всегда.** Всё, что передаёт пользователь — идёт как аргументы к ENTRYPOINT.
# ENTRYPOINT в Dockerfile: ["python"]
# CMD в Dockerfile: ["app.py"]
docker run myimage                    # python app.py
docker run myimage other.py           # python other.py
docker run myimage --version          # python --version
ENTRYPOINT — «всегда это, аргументы — от пользователя».

kubectl create secret docker-registry ghcr-secret \
    --docker-server=ghcr.io \
    --docker-username=$GH_USER \
    --docker-password="токен"\--namespace=default