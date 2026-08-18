# Неделя 11 — Kustomize, публикация чартов, CI для чартов

**Цель недели:** освоить второй подход к конфигурации, научиться публиковать чарты и автоматизировать их проверку.
**Время:** 10.5 часов (2.5 ч теории, 8 ч практики).

Неделя, которая даёт готовый ответ на классический вопрос «Helm или Kustomize?» — и, что важнее, задание, которое можно принести на текущую работу.

---

## 📖 Теория

### 1. Kustomize: другая философия

Helm — **шаблонизация**: генерируем текст, потом парсим как YAML. Kustomize — **наложение патчей**: работаем с валидным YAML как со структурой данных.

Ключевое следствие: в Kustomize нет `{{ }}`, нет условий, нет циклов. Базовые манифесты остаются валидными YAML, которые можно применить напрямую. Это одновременно и сила (простота, отсутствие «программирования в YAML»), и ограничение.

Kustomize встроен в kubectl: `kubectl apply -k ./overlays/prod`.

### 2. Base и overlays

```
k8s/
├── base/
│   ├── kustomization.yaml
│   ├── deployment.yaml
│   ├── service.yaml
│   └── configmap.yaml
└── overlays/
    ├── dev/
    │   ├── kustomization.yaml
    │   └── patch-replicas.yaml
    ├── staging/
    └── prod/
        ├── kustomization.yaml
        ├── patch-resources.yaml
        └── hpa.yaml            # ресурс только для прода
```

```yaml
# base/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - deployment.yaml
  - service.yaml
  - configmap.yaml
commonLabels:
  app.kubernetes.io/name: myservice
```

```yaml
# overlays/prod/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: prod
namePrefix: prod-
resources:
  - ../../base
  - hpa.yaml
images:
  - name: registry.lab/myservice
    newTag: 1.4.2
replicas:
  - name: myservice
    count: 5
patches:
  - path: patch-resources.yaml
configMapGenerator:
  - name: app-config
    behavior: merge
    literals:
      - LOG_LEVEL=warn
```

### 3. Типы патчей

**Strategic merge patch** — пишешь фрагмент нужной структуры, Kustomize сливает:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myservice
spec:
  template:
    spec:
      containers:
        - name: app                    # ключ поиска
          resources:
            limits: { memory: 2Gi }
```

⚠️ Со списками сложнее: Kubernetes-специфичные merge-ключи определяют, сливать по имени или заменять целиком. Для контейнеров ключ — `name`, поэтому пример выше работает. Для произвольных списков (например, `args`) — замена целиком.

**JSON 6902 patch** — точечные операции по пути:

```yaml
patches:
  - target:
      kind: Deployment
      name: myservice
    patch: |-
      - op: replace
        path: /spec/template/spec/containers/0/image
        value: registry.lab/myservice:1.4.2
      - op: add
        path: /spec/template/spec/tolerations/-
        value: { key: gpu, operator: Exists }
      - op: remove
        path: /spec/template/spec/containers/0/livenessProbe
```

Мощнее, но хрупче: путь по индексу сломается при изменении порядка.

### 4. Генераторы и hash suffix

```yaml
configMapGenerator:
  - name: app-config
    files: [config/app.yaml]
    literals: [LOG_LEVEL=info]
secretGenerator:
  - name: app-secrets
    envs: [.env.prod]
```

**Ключевая фича:** генератор добавляет к имени суффикс-хеш содержимого (`app-config-7d2fkm8b9c`) и **автоматически обновляет ссылки** во всех ресурсах. Изменил конфиг → изменилось имя → Deployment изменился → rolling update.

Это решение той же проблемы, которую в Helm ты решал через `checksum/config` в аннотациях. В Kustomize оно встроено и работает элегантнее.

Отключается через `generatorOptions: { disableNameSuffixHash: true }`.

### 5. Helm vs Kustomize — развёрнутый ответ

Заготовь этот ответ для собеседования. Ключевая мысль: **это инструменты для разных задач, а не конкуренты.**

| Критерий | Helm | Kustomize |
|---|---|---|
| Модель | шаблонизация текста | наложение патчей на YAML |
| Распространение | ✅ репозитории, версии, публикация | ❌ нет пакетного менеджера |
| Параметризация | ✅ произвольная, через values | ограниченная патчами |
| Условная логика | ✅ if/range | ❌ отсутствует принципиально |
| Порог входа | выше (Go templates) | ниже |
| Отслеживание релизов | ✅ история, rollback | ❌ (это делает kubectl/ArgoCD) |
| Hooks | ✅ | ❌ (решается sync waves в ArgoCD) |
| Читаемость исходников | шаблоны нечитаемы без рендера | ✅ валидный YAML |
| Установка стороннего ПО | ✅ основной способ | неудобно |

**Практическое правило индустрии:**
- **Стороннее ПО** (Prometheus, cert-manager, ingress-nginx) — Helm, потому что его так распространяют.
- **Свои приложения**, где нужны 3–4 окружения — Kustomize часто проще и прозрачнее.
- **Свои приложения на продажу/для других команд** — Helm, потому что нужна параметризация и распространение.
- **Комбинация** — Helm-чарт как источник, Kustomize-патчи поверх. ArgoCD это поддерживает нативно (`helm template` → kustomize).

Твой личный аргумент на собеседовании: у тебя есть Ansible-инсталлятор, который параметризуется под клиентов. Это ровно тот случай, где Helm выигрывает — нужна упаковка и распространение с параметрами.

### 6. Публикация чартов

**Классический репозиторий** — просто HTTP-сервер с `index.yaml` и `.tgz`:

```bash
helm package ./mychart -d ./dist
helm repo index ./dist --url https://charts.company.com
# положить содержимое dist/ на веб-сервер (можно GitHub Pages)
```

**OCI-registry** (современный способ, поддерживается с Helm 3.8):

```bash
helm package ./mychart
helm push myservice-1.4.2.tgz oci://artifactory.company.com/helm-local
helm install myservice oci://artifactory.company.com/helm-local/myservice --version 1.4.2
```

Преимущества OCI: одно хранилище для образов и чартов, единая аутентификация, единые политики хранения, поддержка подписи через cosign (неделя 17). **Artifactory это умеет** — вот твоя рабочая задача.

**Подпись чарта (provenance):**

```bash
helm package --sign --key 'you@company.com' --keyring ~/.gnupg/secring.gpg ./mychart
helm verify myservice-1.4.2.tgz
helm install --verify myservice ./myservice-1.4.2.tgz
```

### 7. CI для чартов

Стандартный конвейер:

1. **`helm lint`** — базовые проверки
2. **`helm template`** — рендер проходит без ошибок
3. **`kubeconform`** — валидация отрендеренных манифестов против схем Kubernetes API
4. **политики** — `kube-score`, `kube-linter`, позже Kyverno в CLI-режиме
5. **`ct install`** (chart-testing) — установка в эфемерный kind-кластер + `helm test`
6. **упаковка и публикация** по git-тегу

Инструменты:

```bash
# kubeconform — проверка схем, включая CRD
helm template ./mychart | kubeconform -strict -summary \
  -schema-location default \
  -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'

# kube-score — проверка практик (probes, ресурсы, securityContext)
helm template ./mychart | kube-score score -

# chart-testing — полный цикл
ct lint --chart-dirs charts --target-branch main
ct install --chart-dirs charts
```

### 8. Renovate

Автоматическое отслеживание версий: образов, зависимостей чартов, Terraform-модулей, GitHub Actions. Создаёт PR при выходе новых версий.

```json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": ["config:recommended"],
  "packageRules": [
    { "matchUpdateTypes": ["minor", "patch"], "automerge": true },
    { "matchUpdateTypes": ["major"], "dependencyDashboardApproval": true }
  ]
}
```

Это важный элемент зрелого процесса: без него зависимости устаревают незаметно, а потом обновление превращается в проект.

---

## 🔧 Задание 1: переводим манифесты на Kustomize (2.5 ч)

Возьми свои манифесты из месяцев 1–2 (не чарт, а сырые YAML) и оформи их в Kustomize.

1. Создай `base/` со всеми ресурсами и общими лейблами.
2. Создай три overlay: `dev`, `staging`, `prod`. Различия:
   - dev: 1 реплика, debug-логи, без HPA, минимальные ресурсы
   - staging: 2 реплики, свой хост в Ingress
   - prod: 5 реплик, HPA, PDB, topology spread, увеличенные лимиты
3. Используй разные механизмы намеренно, чтобы освоить все:
   - `replicas:` для количества
   - `images:` для тега
   - strategic merge patch для ресурсов
   - JSON 6902 patch для добавления toleration
   - `configMapGenerator` для конфигурации
   - дополнительный ресурс (`hpa.yaml`) только в prod

4. Проверь результат:
   ```bash
   kubectl kustomize overlays/prod | less
   kubectl apply -k overlays/dev --dry-run=server
   diff <(kubectl kustomize overlays/dev) <(kubectl kustomize overlays/prod)
   ```

5. **Эксперимент с hash suffix:** измени значение в `configMapGenerator`, посмотри, как изменилось имя ConfigMap и как автоматически обновилась ссылка в Deployment. Примени и убедись, что произошёл rolling update. Сравни с тем, как ты решал это в Helm.

---

## 🔧 Задание 2: сравнительный документ (1 ч)

Напиши `notes/helm-vs-kustomize.md` — это заготовка ответа на собеседовании, поэтому пиши развёрнуто:

Структура:
1. Одна и та же задача, решённая обоими способами (приложи фрагменты кода).
2. Таблица сравнения по критериям из теории — **своими словами**.
3. Три конкретных сценария с выбором и обоснованием:
   - «нужно поставить Prometheus» → ...
   - «наш микросервис в трёх окружениях» → ...
   - «продукт, который ставят внешние клиенты с разными параметрами» → ...
4. Гибридный подход: когда и зачем комбинируют.
5. Личный вывод: что бы ты выбрал для своего рабочего инсталлятора и почему.

---

## 🔧 Задание 3: публикация чарта в OCI (2 ч) — *делается на работе*

**Локально (для тренировки):**

```bash
# поднять registry с поддержкой OCI
docker run -d -p 5000:5000 --name registry registry:2

helm package ./myservice
helm push myservice-0.1.0.tgz oci://localhost:5000/helm
helm show chart oci://localhost:5000/helm/myservice --version 0.1.0
helm install test oci://localhost:5000/helm/myservice --version 0.1.0
```

**На работе (Artifactory):**

1. Создай (или попроси создать) Helm-репозиторий в Artifactory, лучше сразу OCI.
2. Настрой аутентификацию: `helm registry login`.
3. Опубликуй тестовый чарт.
4. Установи его из Artifactory в тестовый кластер или локальный kind.

Дополнительно освой классический репозиторий на GitHub Pages — полезно для своего портфолио:
```bash
helm package ./mychart -d docs/
helm repo index docs/ --url https://<username>.github.io/devops-lab/
# включить GitHub Pages из папки docs/
```
Теперь любой может поставить твой чарт одной командой — хороший штрих для README портфолио.

---

## 🔧 Задание 4: CI-пайплайн для чарта (2.5 ч)

Сделай **два** варианта — в Jenkins (твоя сильная сторона) и в GitHub Actions (то, что нужно для рынка). Это же и первый шаг к неделе 18.

**GitHub Actions:**

```yaml
name: chart-ci
on: [push, pull_request]

jobs:
  lint-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }

      - uses: azure/setup-helm@v4
      - uses: helm/chart-testing-action@v2

      - name: Lint
        run: ct lint --target-branch ${{ github.event.repository.default_branch }}

      - name: Render and validate schemas
        run: |
          helm dependency update charts/myservice
          helm template charts/myservice | \
            kubeconform -strict -summary -schema-location default

      - name: Policy checks
        run: helm template charts/myservice | kube-score score - --output-format ci

      - name: Create kind cluster
        uses: helm/kind-action@v1

      - name: Install and test
        run: ct install --target-branch ${{ github.event.repository.default_branch }}

  publish:
    needs: lint-and-test
    if: startsWith(github.ref, 'refs/tags/')
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: azure/setup-helm@v4
      - name: Package and push
        run: |
          VERSION=${GITHUB_REF#refs/tags/v}
          helm package charts/myservice --version $VERSION
          helm registry login ${{ secrets.REGISTRY }} \
            -u ${{ secrets.REGISTRY_USER }} -p ${{ secrets.REGISTRY_PASS }}
          helm push myservice-$VERSION.tgz oci://${{ secrets.REGISTRY }}/helm
```

**Проверь, что пайплайн реально ловит проблемы:**
1. Сломай отступ в шаблоне → падает на рендере.
2. Убери probes → предупреждение от kube-score.
3. Задай `apiVersion: apps/v1beta1` → падает на kubeconform.
4. Сломай приложение так, чтобы `helm test` не прошёл → падает `ct install`.

Каждый из этих четырёх случаев должен останавливать пайплайн. Если не останавливает — пайплайн бесполезен.

---

## 🔧 Задание 5: Renovate (1 ч)

1. Подключи Renovate к своему репозиторию (GitHub App, бесплатно для публичных репозиториев).
2. Настрой `renovate.json`: автомёрж патч-версий, ручное одобрение мажорных.
3. Дождись первых PR — обычно приходят в течение часа.
4. Посмотри Dependency Dashboard (issue, который создаёт Renovate) — там видно всё, что устарело.

Это хорошо смотрится в портфолио: показывает, что ты думаешь о поддержке, а не только о создании.

---

## 💥 Ломаем специально

1. В strategic merge patch укажи `name` контейнера, которого нет → патч применится «мимо», создав второй контейнер. Одна из самых коварных ошибок Kustomize.
2. В JSON 6902 patch укажи путь с несуществующим индексом → внятная ошибка. Сравни диагностируемость с предыдущим пунктом.
3. Отключи `disableNameSuffixHash` и измени конфиг → под **не** перезапустится. Пойми, зачем нужен хеш.
4. Опубликуй чарт с версией, которая уже есть в репозитории → посмотри на поведение (перезапись или отказ). Подумай, почему immutable-версии важны.
5. Собери `helm dependency update` без интернета/с недоступным репозиторием → пойми, зачем в CI кэшировать зависимости или вендорить `charts/`.

---

## ❓ Самопроверка

1. Принципиальная разница подходов Helm и Kustomize.
2. Может ли Kustomize сделать «если включён ingress, то создать Ingress»? Как обходят это ограничение?
3. Что такое hash suffix у генераторов и какую проблему он решает? Как та же задача решается в Helm?
4. Strategic merge vs JSON 6902 — когда что применять?
5. Три сценария с обоснованным выбором инструмента.
6. Как выглядит классический Helm-репозиторий (какие файлы)? Чем OCI лучше?
7. Что делает `kubeconform` и чем отличается от `helm lint`?
8. Зачем в CI поднимать kind, если есть `--dry-run=server`?
9. Почему версии чартов должны быть immutable?
10. Что даёт `helm package --sign` и как это проверяется?

---

## 🔗 Ссылки

| Ресурс | Зачем |
|---|---|
| [Kustomize: официальная документация](https://kubectl.docs.kubernetes.io/references/kustomize/) | Справочник по полям |
| [Kustomize примеры](https://github.com/kubernetes-sigs/kustomize/tree/master/examples) | Практика |
| [Helm: OCI Registries](https://helm.sh/docs/topics/registries/) | Публикация |
| [Helm: Provenance and Integrity](https://helm.sh/docs/topics/provenance/) | Подпись |
| [chart-testing (ct)](https://github.com/helm/chart-testing) | CI для чартов |
| [kubeconform](https://github.com/yannh/kubeconform) | Валидация манифестов |
| [kube-score](https://github.com/zegl/kube-score) | Проверка практик |
| [CRDs-catalog](https://github.com/datreeio/CRDs-catalog) | Схемы CRD для kubeconform |
| [helm/kind-action](https://github.com/helm/kind-action) | kind в GitHub Actions |
| [Renovate](https://docs.renovatebot.com/) | Автообновление зависимостей |
| [Artifactory: Helm OCI](https://jfrog.com/help/r/jfrog-artifactory-documentation/helm-oci-repositories) | Для рабочей задачи |

---

## ✅ Чек-лист недели

- [ ] Манифесты оформлены в Kustomize: base + три overlay
- [ ] Использованы все механизмы: replicas, images, оба типа патчей, генераторы, доп. ресурсы
- [ ] Проверил hash suffix и его эффект на rolling update
- [ ] Написан развёрнутый `helm-vs-kustomize.md` с примерами кода и тремя сценариями
- [ ] Чарт опубликован в OCI-registry (локально и, если получилось, в Artifactory на работе)
- [ ] Чарт доступен через GitHub Pages для портфолио
- [ ] CI-пайплайн: lint → template → kubeconform → kube-score → kind + helm test → публикация по тегу
- [ ] Проверил, что пайплайн ловит все четыре типа проблем
- [ ] Renovate подключён, первые PR получены
- [ ] Все 5 экспериментов «Ломаем специально» проделаны
- [ ] `notes/week-11.md` заполнен
