RabbitMQ — распределённый и горизонтально масштабируемый брокер сообщений. Упрощённо его устройство можно описать так:

┌──────────┐    publish    ┌────────┐    consume    ┌──────────┐
│ Producer │ ─────────────▶│ Queue │ ─────────────▶│ Consumer │
└──────────┘               └────────┘               └──────────┘

Producer — отправляет сообщения. Не знает про consumer'ов.
Queue — буфер сообщений. Хранит, пока consumer не заберёт.
Consumer — забирает сообщения. Не знает про producer'ов.

Exchange — «маршрутизатор» сообщений. Producer отправляет в exchange, exchange решает, в какие очереди положить.
Типы exchange:
-Direct	     По точному совпадению routing key
-Fanout	     Во все очереди
-Topic	     По шаблону (logs.*.error)
-Headers	 По заголовкам сообщения

Binding — связь между exchange и queue. Говорит: «сообщения с этим routing key — в эту очередь».

Virtual host — изолированное пространство: свои очереди, exchange, пользователи.

Connection — TCP-соединение между клиентом и RabbitMQ.
Channel — логический поток внутри connection. Можно много channel в одном connection.
создавать TCP-соединение дорого. Channel — дёшево. Один connection, много channel.

Гарантии доставки 
Ack / Nack
Consumer получает сообщение → обрабатывает → отправляет ack (подтверждение).
-Если ack пришёл — RabbitMQ удаляет сообщение.
-Если consumer упал до ack — RabbitMQ возвращает сообщение в очередь. Другой consumer обработает.
-Nack — consumer явно отказывается. Сообщение возвращается или уходит в DLQ (если настроено).

Dead Letter Queue (DLQ)
DLQ — очередь для «мёртвых» сообщений:
-consumer не смог обработать (nack),
-сообщение истекло по TTL,
-очередь переполнена (max-length).
Зачем: не терять проблемные сообщения. Разобраться потом — вручную или отдельным consumer'ом.

Prefetch (QoS)
Prefetch — сколько сообщений consumer берёт одновременно.
Default — unlimited (все в очереди). Плохо: один consumer заберёт всё, остальные голодают.
prefetch = 1 — по одному за раз. Равномерная нагрузка.

Durable queue
Durable queue — сохраняется на диск. Переживёт перезапуск RabbitMQ.
Non-durable — в памяти. Пропадёт при рестарте


Persistent message
Persistent message — сохраняется на диск. Переживёт перезапуск.
Non-persistent — в памяти.

Management API и UI
Plugin rabbitmq_management даёт:
-Web UI на порту 15672 — визуальный интерфейс.
-HTTP API на 15672 — программное управление.


RabbitMQ в Kubernetes
StatefulSet, не Deployment
RabbitMQ — stateful (очереди, сообщения). В Kubernetes разворачивается как StatefulSet:
-Постоянные имена pod'ов: rabbitmq-0, rabbitmq-1
-Свои PVC на каждый pod.
-Стабильные DNS-имена.


