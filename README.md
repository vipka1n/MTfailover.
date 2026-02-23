# Net Failover — система автоматического переключения интерфейсов

Система мониторинга и автоматического переключения сетевых интерфейсов. Если основной интерфейс (например, VPN) перестаёт работать, трафик автоматически переключается на резервный (Ethernet, Wi-Fi).

## Возможности

- ✅ Автоматическое переключение на резервный интерфейс при падении основного
- ✅ Поддержка WireGuard (проверка handshake)
- ✅ Проверка доступности через ping
- ✅ Гибкая настройка приоритетов интерфейсов
- ✅ Маршрутизация только нужных IP-адресов (Telegram, GitHub и др.)
- ✅ Интерактивная панель управления

## Требования

- Linux (Ubuntu/Debian)
- Python 3.8+
- Root-доступ
- Настроенные сетевые интерфейсы (Ethernet, Wi-Fi, VPN)

## Установка

### 0. Установка WireGuard на чистый сервер

На "голом" сервере (fresh Linux) могут отсутствовать необходимые компоненты. Установите их:

```bash
# Установка ядра WireGuard и утилит управления
apt install wireguard

# Установка пакета для работы с DNS (без него WireGuard не пропишет DNS из конфига)
apt install resolvconf
```

#### Настройка конфигурации WireGuard

Создайте файл конфигурации:

```bash
sudo nano /etc/wireguard/wg0.conf
```

**Пример конфига:**

```ini
[Interface]
# Приватный ключ клиента (сгенерируйте: wg genkey)
PrivateKey = ВАШ_PRIVATE_KEY
# Внутренний IP в туннеле
Address = 172.16.6.3/24
# DNS серверы (будут работать через туннель)
DNS = 1.1.1.1, 8.8.8.8

[Peer]
# Публичный ключ сервера
PublicKey = ВАШ_PUBLIC_KEY_SERVER
# Внешний IP сервера (замените на реальный)
Endpoint = 91.108.56.100:51820
# Весь трафик через туннель
AllowedIPs = 0.0.0.0/0
# Сохранять соединение (keep-alive)
PersistentKeepalive = 25
```

**Запуск WireGuard:**

```bash
# Запуск интерфейса
sudo wg-quick up wg0

# Проверка статуса
sudo wg show

# Автозапуск при загрузке (опционально)
sudo systemctl enable wg-quick@wg0
```

> **Примечание:** В этом проекте используется имя интерфейса `one`. Если вы используете `wg0`, измените соответствующие настройки в `chain.conf` и systemd-службе.

### 1. Создание директорий

```bash
sudo mkdir -p /etc/net_manager
sudo mkdir -p /usr/local/bin
```

### 2. Копирование файлов

```bash
# Скопируйте файлы проекта:
# - net_failover.py -> /usr/local/bin/net_failover.py
# - net_manager/chain.conf -> /etc/net_manager/chain.conf
# - net_manager/routes.txt -> /etc/net_manager/routes.txt

sudo cp net_failover.py /usr/local/bin/net_failover.py
sudo cp net_manager/chain.conf /etc/net_manager/chain.conf
sudo cp net_manager/routes.txt /etc/net_manager/routes.txt
```

### 3. Настройка прав

```bash
sudo chmod +x /usr/local/bin/net_failover.py
sudo chmod +x /usr/local/bin/manage.py
```

### 4. Настройка systemd-службы

Создайте файл службы:

```bash
sudo nano /etc/systemd/system/net-failover.service
```

Вставьте содержимое:

```ini
[Unit]
Description=Network Failover Service
After=network.target wg-quick@wg0.service
Requires=wg-quick@wg0.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 /usr/local/bin/net_failover.py
Restart=always
RestartSec=10
RestartPreventExitStatus=1

# Безопасность
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/etc/net_manager /var/log

# Логирование в journal
StandardOutput=journal
StandardError=journal
SyslogIdentifier=net-failover

[Install]
WantedBy=multi-user.target
```

> **Важно:** В этом примере используется интерфейс `wg0`. Если вы используете имя `one` (или другое), замените `wg-quick@wg0.service` на `wg-quick@one.service` в строках `After=` и `Requires=`.

### 5. Запуск и проверка службы

```bash
# Перезагрузить systemd
sudo systemctl daemon-reload

# Включить автозапуск
sudo systemctl enable net-failover

# Запустить службу
sudo systemctl start net-failover

# Проверить статус
sudo systemctl status net-failover
```

**Ожидаемый вывод:**

```
● net-failover.service - Network Failover Service
     Loaded: loaded (/etc/systemd/system/net-failover.service; enabled)
     Active: active (running) since ...
```

### 6. Проверка работы

```bash
# Посмотреть логи
sudo journalctl -u net-failover -f

# Проверить маршруты
ip route | grep -E "149|91|185"
```

**Ожидаемый результат:**

- Маршруты Telegram через VPN (one)
- Default через основной интерфейс

## Настройка

### chain.conf — VPN интерфейсы

Файл: `/etc/net_manager/chain.conf`

Содержит **только VPN-интерфейсы**, которые используются для маршрутизации специфических IP:

```
# VPN интерфейсы для маршрутизации (в порядке приоритета)
# Если первый недоступен - пробуем следующий
# Если все недоступны - маршруты удаляются, используется системный default
one
```

**Важно:**

- **wlp2s0** (или другой основной интерфейс) НЕ указывается в chain.conf
- Он является системным default и используется автоматически
- chain.conf содержит ТОЛЬКО VPN-интерфейсы

**Логика работы:**

1. Если VPN (one) работает → маршруты для Telegram идут через VPN
2. Если VPN недоступен → маршруты удаляются, трафик идёт через wlp2s0 (default)

**Как узнать имена интерфейсов:**

```bash
ip link show
# или
ls /sys/class/net/
```

### routes.txt — IP-адреса для маршрутизации

Файл: `/etc/net_manager/routes.txt`

Содержит IP-адреса и подсети, которые будут маршрутизироваться через VPN:

```txt
# Telegram
149.154.162.123
149.154.167.255
149.154.167.41
149.154.175.211

# Telegram подсети
149.154.175.0/24
149.154.167.0/24
91.108.56.0/22
91.108.4.0/22
91.108.8.0/22
91.108.16.0/22
91.108.12.0/22
149.154.160.0/20

# GitHub
185.199.108.153

# Другие сервисы
2.23.88.29
95.161.76.0/24
```

**Добавление новых IP:**

```bash
sudo nano /etc/net_manager/routes.txt
```

Добавьте IP-адрес или подсеть (CIDR) — каждый адрес с новой строки. Строки начинающиеся с `#` — комментарии.

## Управление

### Интерактивная панель (manage.py)

```bash
sudo python3 manage.py
```

**Меню:**

```
1. Список целей (routes.txt)  - редактирование маршрутов
2. Приоритеты VPN            - настройка порядка интерфейсов
3. Проверить маршруты        - просмотр активных маршрутов
4. ПРИМЕНИТЬ (Restart)       - перезапуск службы
5. Логи                      - просмотр логов
0. Выход
```

### Команды systemctl

```bash
# Статус службы
sudo systemctl status net-failover

# Перезапуск
sudo systemctl restart net-failover

# Остановка
sudo systemctl stop net-failover

# Логи (в реальном времени)
sudo journalctl -u net-failover -f

# Логи (последние 50 строк)
sudo journalctl -u net-failover -n 50

# Логи с момента запуска
sudo journalctl -u net-failover -b
```

### Управление службой

```bash
# Остановить службу
sudo systemctl stop net-failover

# Запустить службу
sudo systemctl start net-failover

# Перезапустить службу
sudo systemctl restart net-failover

# Отключить автозапуск
sudo systemctl disable net-failover

# Включить автозапуск
sudo systemctl enable net-failover

# Проверить активна ли служба
sudo systemctl is-active net-failover
```

## Как это работает

### Логика работы

1. **Системный default** — ваш основной интерфейс (wlp2s0) НЕ в chain.conf
2. **Проверка VPN** — каждые 10 секунд демон проверяет доступность VPN из chain.conf
3. **Проверка WireGuard** — если интерфейс WireGuard, проверяется latest-handshake
4. **Проверка ping** — для всех интерфейсов делается ping до 8.8.8.8 и 1.1.1.1

### Пример работы

```
chain.conf: one (только VPN)

Ситуация 1: VPN (one) работает
→ Маршруты для Telegram идут через one (VPN)

Ситуация 2: VPN (one) недоступен
→ Маршруты удаляются
→ Трафик Telegram идёт через wlp2s0 (системный default)
```

### Поток трафика

```
┌─────────────────────────────────────────────────────────────┐
│                     Telegram IP (149.154...)                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                  ┌───────────────────────┐
                  │   VPN (one) работает? │
                  └───────────────────────┘
                     │              │
                    ДА             НЕТ
                     │              │
                     ▼              ▼
            ┌──────────────┐   ┌──────────────────┐
            │ Через VPN   │   │  Через default   │
            │ ( маршруты  │   │  (wlp2s0 - без   │
            │  добавлены) │   │   маршрутов)     │
            └──────────────┘   └──────────────────┘
```

## Устранение проблем

### Служба не запускается

```bash
# Проверить логи
sudo journalctl -u net-failover -n 50

# Проверить права
ls -la /usr/local/bin/net_failover.py
```

### Интерфейс не найден

```bash
# Проверить доступные интерфейсы
ip link show
ls /sys/class/net/

# Обновить chain.conf
sudo nano /etc/net_manager/chain.conf
```

### Маршруты не применяются

```bash
# Проверить текущие маршруты
ip route show

# Проверить routes.txt
cat /etc/net_manager/routes.txt

# Перезапустить службу
sudo systemctl restart net-failover
```

### Нет доступа к Telegram

```bash
# Добавить IP Telegram в routes.txt
echo "149.154.175.211" | sudo tee -a /etc/net_manager/routes.txt

# Перезапустить
sudo systemctl restart net-failover
```

## Дополнительные настройки

### Изменить интервал проверки

В файле `net_failover.py` найдите строку:

```python
time.sleep(10)  # Проверка каждые 10 секунд
```

Измените на нужное значение (в секундах).

### Изменить цели проверки

```python
CHECK_TARGETS = ["8.8.8.8", "1.1.1.1"]
```

Добавьте или измените IP-адреса для проверки.

## Полезные команды

```bash
# Просмотр текущего default маршрута
ip route show default

# Просмотр всех маршрутов
ip route show

# Просмотр конкретного маршрута
ip route show 149.154.175.0/24

# Тестирование интерфейса
ping -I <интерфейс> 8.8.8.8

# Статус WireGuard
sudo wg show
```

## Структура файлов после установки

```
/usr/local/bin/
├── net_failover.py    # Демон
└── manage.py          # Панель управления

/etc/net_manager/
├── chain.conf         # VPN интерфейсы (только VPN!)
└── routes.txt         # IP-адреса для маршрутизации через VPN

/etc/systemd/system/
└── net-failover.service  # Служба
```

## Примеры конфигураций

### Пример 1: Один VPN (WireGuard)

**chain.conf:**

```
one
```

**routes.txt:**

```
149.154.175.211
149.154.167.0/24
91.108.56.0/22
```

**Результат:** Трафик до Telegram идёт через VPN. Если VPN недоступен — через wlp2s0.

### Пример 2: Несколько VPN

**chain.conf:**

```
wg0
wg1
```

**Результат:** Сначала пробуем wg0, если недоступен — wg0. Оба недоступны — default.

### Пример 3: Только routes.txt (без chain.conf)

Если chain.conf пустой или отсутствует:

- Маршруты не добавляются
- Всё идёт через системный default

## Удаление службы

```bash
# Остановить службу
sudo systemctl stop net-failover

# Отключить автозапуск
sudo systemctl disable net-failover

# Удалить файл службы
sudo rm /etc/systemd/system/net-failover.service

# Перезагрузить systemd
sudo systemctl daemon-reload

# Удалить файлы (опционально)
sudo rm -rf /usr/local/bin/net_failover.py
sudo rm -rf /usr/local/bin/manage.py
sudo rm -rf /etc/net_manager
```
