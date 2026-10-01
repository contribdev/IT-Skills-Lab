Kubernetes Job

Job — ресурс Kubernetes, который запускает pod'ы до успешного завершения задачи. В отличие от Deployment (pod'ы работают постоянно), Job завершается, когда работа сделана.

Сценарий	                         Почему Job, а не Deployment
Миграция БД при деплое	             Выполнить один раз при обновлении
Предсоздание очередей RabbitMQ	     Идемпотентная операция один раз
Backup	                             Периодическая задача, завершается
Batch-обработка	                     Обработать N файлов и выйти
CronJob (по расписанию)	             Job, запускаемый по cron

Workflow
1. Создаёшь Job (kubectl apply / Terraform)
    ↓
2. Job создаёт Pod
    ↓
3. Pod запускает контейнер
    ↓
4. Контейнер выполняет команду
    ↓
5a. Успех (exit 0) → Job = Completed
5b. Ошибка (exit != 0) → перезапуск (backoff_limit)
    ↓
6. Job остаётся в кластере (для аудита), pod удаляется

Ключевые поля:
1) Шаблон pod'а — что запускать. Внутри — spec как у обычного Pod:

-containers — образы, команды, ресурсы.
-restartPolicy — Never, OnFailure, Always.
-volumes — если нужно.

2) spec.backoffLimit - Сколько раз повторить при ошибке.
Механика: если pod упал — Job ждёт 10 сек, потом 20, 40, 80... (экспоненциальный backoff). После backoffLimit попыток — Job = Failed.

3) spec.completions и spec.parallelism
completions — сколько успешных завершений нужно. Обычно 1.
parallelism — сколько pod'ов одновременно. Обычно 1.

4) spec.activeDeadlineSeconds - Максимум времени на Job. Если не завершился — убить.

5) spec.ttlSecondsAfterFinished - сколько Job живёт после завершения. Если указать — Job удалится через N секунд.

Особенности работы с Terraform
1) wait_for_completion = true
Terraform ждёт завершения Job. Если Job упал — terraform apply тоже упадёт с ошибкой.
узнаёшь о проблеме сразу, а не через день. Если очереди не создались — apply скажет.

2) timeouts
timeouts {
  create = "5m"
}
Максимум 5 минут на создание (то есть на завершение Job). Если дольше — Terraform оборвёт и выдаст ошибку.

3) depends_on
depends_on = [helm_release.rabbitmq]
Job не ссылается на атрибуты Helm release напрямую. Поэтому ручная зависимость. Без неё Job может стартовать до RabbitMQ.