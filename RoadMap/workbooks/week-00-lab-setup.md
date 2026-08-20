# Подготовка рабочего окружения

Установлена версия Pro версия Windows.
Аппаратная виртуализация включена.

На машине имеется 32 Гб оперативной памяти.

Далее необходимо освободить место на дисковом пространстве

# Настройка лаборатории

Основная задача - настроить сетевую доступность машин для их взаимодествия. 
Буду использовать внутренний коммутатор и собственный NAT

## Создать внутренний коммутатор
New-VMSwitch -SwitchName "k8s-lab" -SwitchType Internal

Name    SwitchType NetAdapterInterfaceDescription
----    ---------- ------------------------------
k8s-lab Internal

## Найти индекс появившегося интерфейса
Get-NetAdapter | Where-Object Name -like "*k8s-lab*"

Name                      InterfaceDescription                    ifIndex Status       MacAddress             LinkSpeed
----                      --------------------                    ------- ------       ----------             ---------
vEthernet (k8s-lab)       Hyper-V Virtual Ethernet Adapter #3          43 Up           00-15-5D-01-7D-00        10 Gbps

## Назначить хосту адрес шлюза 
New-NetIPAddress -IPAddress 192.168.100.1 -PrefixLength 24 -InterfaceIndex 43

IPAddress         : 192.168.100.1
InterfaceIndex    : 43
InterfaceAlias    : vEthernet (k8s-lab)
AddressFamily     : IPv4
Type              : Unicast
PrefixLength      : 24
PrefixOrigin      : Manual
SuffixOrigin      : Manual
AddressState      : Tentative
ValidLifetime     : Infinite ([TimeSpan]::MaxValue)
PreferredLifetime : Infinite ([TimeSpan]::MaxValue)
SkipAsSource      : False
PolicyStore       : ActiveStore

IPAddress         : 192.168.100.1
InterfaceIndex    : 43
InterfaceAlias    : vEthernet (k8s-lab)
AddressFamily     : IPv4
Type              : Unicast
PrefixLength      : 24
PrefixOrigin      : Manual
SuffixOrigin      : Manual
AddressState      : Invalid
ValidLifetime     : Infinite ([TimeSpan]::MaxValue)
PreferredLifetime : Infinite ([TimeSpan]::MaxValue)
SkipAsSource      : False
PolicyStore       : PersistentStore

## Включить NAT для выхода ВМ в интернет
New-NetNat -Name "k8s-lab-nat" -InternalIPInterfaceAddressPrefix 192.168.100.0/24

Итоговая адресация должна выглядеть следующим образом:

| Хост | IP | Роль |
|---|---|---|
| Windows (шлюз) | 192.168.100.1 | хост |
| cp-1 | 192.168.100.11 | k3s server |
| node-1 | 192.168.100.12 | k3s agent |
| node-2 | 192.168.100.13 | k3s agent |

Команды для проверки 

Get-VMSwitch -Name k8s-lab

Name    SwitchType NetAdapterInterfaceDescription
----    ---------- ------------------------------
k8s-lab Internal


Get-NetIPAddress -InterfaceAlias "vEthernet (k8s-lab)" -AddressFamily IPv4


IPAddress         : 192.168.100.1
InterfaceIndex    : 11
InterfaceAlias    : vEthernet (k8s-lab)
AddressFamily     : IPv4
Type              : Unicast
PrefixLength      : 24
PrefixOrigin      : Manual
SuffixOrigin      : Manual
AddressState      : Preferred
ValidLifetime     : Infinite ([TimeSpan]::MaxValue)
PreferredLifetime : Infinite ([TimeSpan]::MaxValue)
SkipAsSource      : False
PolicyStore       : ActiveStore


Get-NetNat

Name                             : k8s-lab-nat
ExternalIPInterfaceAddressPrefix :
InternalIPInterfaceAddressPrefix : 192.168.100.0/24
IcmpQueryTimeout                 : 30
TcpEstablishedConnectionTimeout  : 1800
TcpTransientConnectionTimeout    : 120
TcpFilteringBehavior             : AddressDependentFiltering
UdpFilteringBehavior             : AddressDependentFiltering
UdpIdleSessionTimeout            : 120
UdpInboundRefresh                : False
Store                            : Local
Active                           : True


Get-NetIPInterface -InterfaceAlias "vEthernet (k8s-lab)" -AddressFamily IPv4 | Select Forwarding

Forwarding
----------
   Enabled


Get-NetConnectionProfile -InterfaceAlias "vEthernet (k8s-lab)"

Name                     : Unidentified network
InterfaceAlias           : vEthernet (k8s-lab)
InterfaceIndex           : 11
NetworkCategory          : Private
DomainAuthenticationKind : None
IPv4Connectivity         : NoTraffic
IPv6Connectivity         : NoTraffic

При настройке сети потребовалось включить форвардинг на всех необходимых интерфейсах, в моем случае и на k8s-lab, и на wsl

Get-NetIPInterface -AddressFamily IPv4 | Where-Object InterfaceAlias -like "vEthernet*" | Select InterfaceAlias, Forwarding

InterfaceAlias             Forwarding
--------------             ----------
vEthernet (k8s-lab)           Enabled
vEthernet (WSL)               Enabled
vEthernet (Default Switch)   Disabled

В таком случае будет полный доступ к узлу

Также потребовалось включить icmp на хосте для пинга вм

## Создание ВМ

New-VM -Name "cp-1" -MemoryStartupBytes 4GB -Generation 2 -NewVHDPath "D:\HyperV\cp-1.vhdx" -NewVHDSizeBytes 40GB -SwitchName "k8s-lab"

Set-VM -Name "cp-1" -ProcessorCount 2 -StaticMemory
Set-VMFirmware -VMName "cp-1" -EnableSecureBoot Off      # важно для Ubuntu
Add-VMDvdDrive -VMName "cp-1" -Path "D:\images\ubuntu-24.04.4-live-server-amd64.iso"

Настроил сеть руками на вм при установке ОС

subnet 192.168.100.0/24
Address 192.168.100.11
Gateway 192.168.100.1
servers 8.8.8.8, 1.1.1.1




