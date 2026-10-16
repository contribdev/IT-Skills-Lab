# Этап 5. Ingress и TLS

**Цель:** сделать API доступным снаружи по `https://documents.local`

## Contour + Envoy

**Envoy** — edge proxy:
- Принимает TCP/HTTP-соединения снаружи
- Роутит HTTP-запросы на backend'ы
- Балансирует нагрузку
- TLS-терминация

**Contour** — control plane для Envoy:
- Читает HTTPProxy, Ingress, Service из Kubernetes API
- Строит конфигурацию для Envoy через xDS

---

## Схема прохождения трафика

```
Windows (браузер)
  │
  │ 1. hosts: documents.local → 192.168.100.11
  │ 2. TCP connect :443
  │ 3. TLS handshake (SNI=documents.local)
  │
  ▼
ServiceLB (192.168.100.11)
  │ iptables: 443 → pod svclb-contour-envoy
  │
  ▼
Pod contour-envoy
  │ 4. TLS завершён, SNI=documents.local
  │ 5. HTTPProxy → Service api:8080
  │
  ▼
kube-proxy (iptables)
  │ ClusterIP → pod IP (DNAT)
  │
  ▼
Pod api
  │ FastAPI: GET /healthz → {"status": "ok"}
```

---

## TLS с cert-manager

### Цепочка сертификатов

| Этап | Ресурс | Что происходит |
|------|--------|----------------|
| 1 | ClusterIssuer `selfsigned-issuer` | Выпускает самоподписанные сертификаты |
| 2 | Certificate `selfsigned-ca` | Корневой CA (`isCA: true`) |
| 3 | ClusterIssuer `selfsigned-ca-issuer` | Подписывает сертификаты нашим CA |
| 4 | Certificate `documents-local-tls` | Сертификат для домена |
| 5 | HTTPProxy | Использует Secret с сертификатом |

### Реализованные ресурсы

| Ресурс | Тип | Scope | Описание |
|--------|-----|-------|----------|
| `selfsigned-issuer` | ClusterIssuer | cluster | Самоподписанные |
| `selfsigned-ca` | Certificate | cert-manager | Корневой CA |
| `selfsigned-ca-issuer` | ClusterIssuer | cluster | Подписывает CA |
| `documents-local-tls` | Certificate | ai-doc-platform | Сертификат домена |
| `api-proxy` | HTTPProxy | ai-doc-platform | Роутинг Contour |

---

## Ключевые концепции

**SNI (Server Name Indication)** — расширение TLS, позволяющее клиенту указать hostname до установки шифрованного соединения. Envoy по SNI выбирает нужный сертификат.

**Edge proxy** — прокси на границе сети. Принимает трафик снаружи и передаёт внутрь кластера.

**TLS-терминация** — расшифровка TLS на Envoy. Внутри кластера трафик идёт без TLS.

---

## Проблемы

**Ошибка:** Недоступность `https://documents.local`

**Диагностика:**
Резолвится ли имя
ping documents.local

Доступен ли 443 порт
Test-NetConnection -ComputerName 192.168.100.11 -Port 443

Проверка External IP contour-envoy
kubectl -n projectcontour get svc

Проверка работают ли поды 
kubectl -n projectcontour get pods

Проверка, настроен ли роутинг
kubectl -n ai-doc-platform get httpproxies.projectcontour.io

NAME        FQDN              TLS SECRET            STATUS   STATUS DESCRIPTION
api-proxy   documents.local   documents-local-tls   valid    Valid HTTPProxy

Проверка, существует ли сертификат
kubectl -n ai-doc-platform get secret documents-local-tls


**Решение:** 
Выключить vpn


