Terraform — это инструмент Infrastructure as Code (IaC), который позволяет описывать инфраструктуру в виде кода, безопасно и эффективно её создавать, изменять и версионировать. Он работает с компонентами низкого уровня (вычислительные инстансы, хранилища, сети) и высокоуровневыми (DNS-записи, SaaS-функции)
Ключевое отличие Terraform от инструментов, привязанных к одному облаку: он не зависит от конкретного провайдера. Один и тот же синтаксис используется для AWS, Azure, Google Cloud, Kubernetes, Helm, GitHub и сотен других систем

Архитектура Terraform
Terraform CLI сам по себе не знает, как создавать ресурсы в информационных системах. Он умеет только:
-управлять состоянием (state),
-строить граф зависимостей,
-планировать изменения.
За взаимодействие с конкретными системами отвечают провайдеры — плагины, которые транслируют HCL-конфигурацию в вызовы API целевой системы

Основные сущности Terraform
1. Конфигурация (Configuration)
Совокупность файлов .tf в директории, описывающих желаемое состояние инфраструктуры на языке HCL (HashiCorp Configuration Language). В отличие от императивных скриптов, конфигурация декларативна: описывается что должно существовать, а не как это создать.

2. Провайдер (Provider)
Плагин, который знает, как разговаривать с конкретным API. Примеры:
-aws — для Amazon Web Services,
-kubernetes — для Kubernetes API,
-helm — для Helm-чартов,
-github — для GitHub.

Пример объявления провайдера:
terraform {
  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.30"
    }
  }
}

provider "kubernetes" {
  config_path = "~/.kube/config"
}

3. Ресурс (Resource)
Единица инфраструктуры, которой управляет Terraform. Определяется блоком resource с типом (специфичен для провайдера) и локальным именем:
resource "kubernetes_namespace" "storage" {
  metadata {
    name = "storage"
  }
}
Адрес ресурса в state: kubernetes_namespace.storage. Тип (kubernetes_namespace) определяет, какой API вызывать, а имя (storage) — для ссылок внутри конфигурации.

4. Переменные (Variables), Locals, Outputs
-Variable — входной параметр (от пользователя или родительского модуля):
variable "cluster_name" {
  type        = string
  default     = "ai-platform"
  description = "Имя кластера"
}

-Locals — вычисляемые значения внутри модуля:
locals {
  full_name = "k3d-${var.cluster_name}"
}

-Output — значение, которое модуль отдаёт наружу:
output "cluster_name" {
  value = var.cluster_name
}

5. Модуль (Module)
Переиспользуемый набор ресурсов — аналог функции в программировании. Модуль вызывается блоком module:
module "storage" {
  source              = "../../modules/storage"
  minio_root_user     = var.minio_user
  minio_root_password = var.minio_password
}

Внутри модуля — те же resource, variable, output. Модуль имеет входные параметры (variables) и возвращаемые значения (outputs)

6. Состояние (State)
Ключевая сущность Terraform. Файл terraform.tfstate (JSON), который хранит маппинг между ресурсами в конфигурации и реальными объектами в облаке. Без state Terraform не знает, что уже создано, и не может вычислять diff
State критически важен:
-содержит ID и атрибуты всех управляемых ресурсов,
-может содержать секреты (пароли, ключи) в открытом виде,
-не коммитится в git (добавляется в .gitignore).

7. Backend
Конфигурация, определяющая, где хранится state. По умолчанию — локально (terraform.tfstate в директории). Для командной работы используется удалённый backend (S3, GCS, Azure Blob и др.)
terraform {
  backend "s3" {
    bucket         = "my-tfstate"
    key            = "dev/terraform.tfstate"
    region         = "eu-central-1"
    dynamodb_table = "tfstate-lock"
    encrypt        = true
  }
}

Зачем удалённый backend:
-централизованное хранение (все видят актуальный state),
-блокировки (locking) — предотвращают одновременный apply двумя людьми,
-версионирование и восстановление,
-шифрование

Блокировка работает так: перед apply Terraform создаёт запись lock (в DynamoDB, lease в БД и т.п.). Если другой процесс попытается применить изменения — получит ошибку и будет ждать или завершится. После завершения lock снимается автоматически

##Рабочий процесс (Workflow)
Четыре базовых шага:
1. Write (Написать)
Вы создаёте .tf-файлы с описанием желаемого состояния инфраструктуры.

2. Init (Инициализировать)

terraform init
-скачивает провайдеры и модули,
-инициализирует backend,
-создаёт .terraform/ и .terraform.lock.hcl.

3. Plan (Спланировать)

terraform plan
Terraform:
-читает конфигурацию,
-обращается к реальной инфраструктуре (refresh) — получает текущее состояние,
-сравнивает с желаемым,
-показывает план действий: что создать (+), изменить (~), удалить (-).

Plan никогда не изменяет инфраструктуру. Это preview. Всегда читайте его перед apply.

4. Apply (Применить)

terraform apply
Выполняет план: вызывает API провайдеров, создаёт/обновляет/удаляет ресурсы и обновляет state.

5. Destroy (Уничтожить)

terraform destroy
Удаляет всё, что описано в конфигурации и есть в state. Использовать с осторожностью

Практика:

Пройдем по описанному workflow
Минимальный файл:
terraform {
  required_version = ">= 1.6.0"

  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.30"
    }
  }
}

provider "kubernetes" {
  config_path = "~/.kube/config-lab"
}

resource "kubernetes_namespace" "demo" {
  metadata {
    name = "terraform-demo"
  }
}

terraform init

-Terraform прочитает main.tf.
-Увидит требование провайдера hashicorp/kubernetes ~> 2.30.
-Скачает его в .terraform/providers/.
-Создаст .terraform.lock.hcl — файл с точной версией скачанного провайдера.
-Создаст .terraform/ — рабочую директорию.


terraform plan

-Terraform прочитает main.tf.
-Подключится к k3s через kubeconfig.
-Проверит: существует ли namespace terraform-demo?
-Покажет план: создать (если нет) или ничего не делать (если есть).

Условные обозначения:
+ — создать.
~ — изменить.
- — удалить.
-/+ — пересоздать (удалить и создать заново).
<= — прочитать (data source).


terraform apply - применит изменения

при повторном запуске ничего не произойдет 
No changes. Your infrastructure matches the configuration.
Apply complete! Resources: 0 added, 0 changed, 0 destroyed.

Terraform помнит через state, что namespace уже создан. Если конфигурация не изменилась — ничего не делает.

Можно добавить второй namespace, тогда при следующем plan будет создан только он. Удаление блока resource из конфига → Terraform удалит ресурс из инфраструктуры при apply.

С помощью объектов variable можно параметризировать конфиг

variable "namespace_name" {
  description = "Имя создаваемого namespace"
  type        = string
  default     = "terraform-demo"
}

resource "kubernetes_namespace" "demo" {
  metadata {
    name = var.namespace_name
  }
}

При вызове можно определять своим значением 
terraform plan -var="namespace_name=terraform-renamed"

Также данные можно отдавать наружу

output "created_namespace" {
  description = "Имя созданного namespace"
  value       = kubernetes_namespace.demo.metadata[0].name
}

Есть возможность импортировать уже существующие ресурсы 
Когда ресурс уже существует, при попытке сконфигурировать его с помощью Terraform здфт покажет, что он создаст его, но при применении apply получим ошибку 
│ Error: namespaces "manual-ns" already exists
│ 
│   with kubernetes_namespace.manual-ns,
│   on main.tf line 28, in resource "kubernetes_namespace" "manual-ns":
│   28: resource "kubernetes_namespace" "manual-ns" {

в таком случае необходимо выполнить импорт ресурса
terraform import kubernetes_namespace.manual-ns manual-ns
Команда добавит запись в state

Import — это ручное связывание существующего объекта с ресурсом в конфиге. Terraform сам не умеет «увидеть» объект в кластере и догадаться, что он соответствует resource-блоку.


Drift

Если после terraform apply вручную изменить состояние ресурса

kubectl label namespaces terra-test drift=true
namespace/terra-test labeled

terraform plan обнаружит расхождения

Перед plan он делает refresh — опрашивает реальную инфраструктуру через API провайдера и обновляет in-memory копию state. Затем сравнивает три вещи:
-Конфиг (что написано)
-State после refresh (что реально в кластере)
-State до refresh (что Terraform помнил)
Если state после refresh ≠ state до refresh — это drift. Terraform покажет это в плане:
metadata {
          ~ labels           = {
              - "drift" = "true" -> null
            }
            name             = "terra-test"
            # (5 unchanged attributes hidden)
        }
    }

Что сделает Terraform:

-Если label есть в реальности, но нет в конфиге — Terraform удалит его при следующем apply (потому что конфиг — источник истины).
-Если label добавлен в конфиг, но нет в реальности — Terraform добавит его.

Drift — это расхождение между реальностью и state, вызванное действиями вне Terraform.

Если изменения необходимо принять apply -refresh-only

kubectl label namespaces terra-test drift=true
namespace/terra-test labeled
Apply complete! Resources: 0 added, 0 changed, 0 destroyed.
В state будет прописан
"labels": {
                  "drift": "true"
                },

При следующем запуске terraform apply должен удалить лейбл, так как его нет в конфиге 
