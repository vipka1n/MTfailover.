#!/usr/bin/env python3
"""
Net Failover Daemon - Система маршрутизации для прокси-сервера
===============================================================

Логика работы:
1. Пользователи подключаются к WireGuard на сервере (AllowedIPs = 0.0.0.0/0)
2. Весь их трафик приходит на сервер
3. Этот скрипт определяет куда направить трафик:
   - Специфические IP (Telegram и т.д.) -> через VPN (one)
   - Остальной трафик -> через default интерфейс

Требования к серверу:
- WireGuard с AllowedIPs = 0.0.0.0/0 (или настроенный соответственно)
- ip_forward = 1
- NAT (MASQUERADE) в iptables
"""

import os
import subprocess
import socket
import time
import signal
import sys

# ============== КОНФИГУРАЦИЯ ==============
ROUTES_FILE = "/etc/net_manager/routes.txt"
CHAIN_FILE = "/etc/net_manager/chain.conf"
CHECK_TARGETS = ["8.8.8.8", "1.1.1.1"]
CHECK_INTERVAL = 10  # секунд между проверками


# ============== КЛАСС DAEMON ==============
class FailoverDaemon:
    def __init__(self):
        self.current_iface = None
        self.default_iface = None
        self.running = True

        # Регистрируем обработчики сигналов
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def signal_handler(self, signum, frame):
        """Обработка сигналов завершения"""
        print(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] 🛑 Завершение...")
        self.cleanup()
        sys.exit(0)

    def run_cmd(self, cmd):
        """Выполнить команду shell"""
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            return result.stdout.strip(), result.stderr.strip(), result.returncode
        except Exception as e:
            return "", str(e), 1

    def check_ip_forward(self):
        """Проверить и включить ip_forward если нужно"""
        stdout, _, _ = self.run_cmd("sysctl net.ipv4.ip_forward")
        if "= 1" not in stdout:
            print("   🔧 Включаем ip_forward...")
            self.run_cmd("sysctl -w net.ipv4.ip_forward=1")
            # Добавляем в /etc/sysctl.conf для персистентности
            self.run_cmd("grep -q 'net.ipv4.ip_forward=1' /etc/sysctl.conf || echo 'net.ipv4.ip_forward=1' >> /etc/sysctl.conf")

    def check_nat(self):
        """Проверить и настроить NAT (MASQUERADE)"""
        # Проверяем есть ли правило MASQUERADE
        stdout, _, _ = self.run_cmd("iptables -t nat -L POSTROUTING -v -n")

        if "MASQUERADE" not in stdout:
            print("   🔧 Настраиваем NAT (MASQUERADE)...")
            default_iface = self.get_default_interface()
            if default_iface:
                self.run_cmd(f"iptables -t nat -A POSTROUTING -o {default_iface} -j MASQUERADE")
                self.run_cmd("iptables -A FORWARD -m state --state RELATED,ESTABLISHED -j ACCEPT")
                self.run_cmd("iptables -A FORWARD -i wg+ -j ACCEPT")

    def get_default_interface(self):
        """Получить текущий default интерфейс"""
        stdout, _, _ = self.run_cmd("ip route show default")
        if stdout:
            parts = stdout.split()
            if 'dev' in parts:
                try:
                    dev_idx = parts.index('dev')
                    return parts[dev_idx + 1]
                except:
                    pass
        return None

    def get_all_interfaces(self):
        """Получить список всех интерфейсов"""
        try:
            return [f for f in os.listdir('/sys/class/net/') if f != 'lo']
        except:
            return []

    def detect_default_interface(self):
        """Определить default интерфейс автоматически"""
        chain = self.get_config()
        default_iface = self.get_default_interface()

        # Исключаем VPN интерфейсы
        if default_iface and default_iface not in chain:
            self.default_iface = default_iface
            print(f"📌 Определён default интерфейс: {self.default_iface}")
        else:
            # Ищем первый не-VPN интерфейс
            for iface in self.get_all_interfaces():
                if iface not in chain:
                    self.default_iface = iface
                    print(f"📌 Использую интерфейс: {self.default_iface}")
                    break

    def is_ok(self, iface):
        """Проверить доступность интерфейса"""
        if not os.path.exists(f"/sys/class/net/{iface}"):
            return False

        # Проверка WireGuard Handshake (правильная команда - множественное число)
        stdout, _, _ = self.run_cmd(f"wg show {iface} latest-handshakes 2>/dev/null | awk '{{print $2}}'")
        if stdout and stdout.strip() and stdout.strip() != "0":
            return True

        # Проверка ping с коротким таймаутом
        for target in CHECK_TARGETS:
            try:
                result = subprocess.run(
                    ["ping", "-c", "1", "-W", "2", "-I", iface, target],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=3
                )
                if result.returncode == 0:
                    return True
            except:
                pass

        return False

    def get_config(self):
        """Получить список VPN интерфейсов из chain.conf"""
        if not os.path.exists(CHAIN_FILE):
            return []
        try:
            with open(CHAIN_FILE, 'r') as f:
                lines = [l.strip() for l in f.readlines()]
                return [l for l in lines if l and not l.startswith('#')]
        except:
            return []

    def get_targets(self):
        """Получить список IP-адресов для маршрутизации"""
        if not os.path.exists(ROUTES_FILE):
            return []
        try:
            with open(ROUTES_FILE, 'r') as f:
                return [l.strip() for l in f if l.strip() and not l.startswith('#')]
        except:
            return []

    def remove_vpn_default_routes(self):
        """Удалить default маршруты через VPN"""
        default_iface = self.get_default_interface()
        if default_iface and default_iface != self.default_iface:
            self.run_cmd("ip route del default 2>/dev/null")
            print(f"   🗑 Удалён default через VPN")

    def ensure_default_via_main(self):
        """Гарантировать default через основной интерфейс"""
        current = self.get_default_interface()
        if current != self.default_iface:
            self.run_cmd("ip route del default 2>/dev/null")
            self.run_cmd(f"ip route add default dev {self.default_iface}")
            print(f"   🔄 Default переключён на {self.default_iface}")

    def clear_routes(self):
        """Удалить все специфические маршруты"""
        for target in self.get_targets():
            try:
                ip = target if '/' in target else socket.gethostbyname(target)
                self.run_cmd(f"ip route del {ip} 2>/dev/null")
            except:
                pass

    def apply_routes(self, iface):
        """Применить маршруты через VPN интерфейс"""
        # 1. Удаляем default через VPN
        self.remove_vpn_default_routes()

        # 2. Гарантируем default через основной интерфейс
        self.ensure_default_via_main()

        # 3. Добавляем специфические маршруты через VPN
        for target in self.get_targets():
            try:
                ip = target if '/' in target else socket.gethostbyname(target)
                self.run_cmd(f"ip route del {ip} 2>/dev/null")
                self.run_cmd(f"ip route add {ip} dev {iface}")
            except:
                pass

    def cleanup(self):
        """Очистка при завершении"""
        self.clear_routes()

    def loop(self):
        """Основной цикл"""
        # === Инициализация ===
        print("=" * 50)
        print("🚀 Net Failover Daemon Started")
        print("=" * 50)

        # Проверяем ip_forward
        self.check_ip_forward()

        # Проверяем NAT
        self.check_nat()

        # Определяем default интерфейс
        self.detect_default_interface()

        if not self.default_iface:
            print("❌ Не удалось определить default интерфейс!")
            sys.exit(1)

        print(f"📌 Default: {self.default_iface}")
        print(f"📌 VPN: {', '.join(self.get_config())}")
        print(f"📌 Целей: {len(self.get_targets())}")

        # === Основной цикл ===
        while self.running:
            try:
                chain = self.get_config()

                # Ищем первый работающий VPN
                best_vpn = next((i for i in chain if self.is_ok(i)), None)

                # Проверяем изменение состояния
                if best_vpn != self.current_iface:
                    if best_vpn:
                        self.apply_routes(best_vpn)
                        print(f"[{time.strftime('%H:%M:%S')}] ✅ Маршруты через {best_vpn}")
                    else:
                        self.clear_routes()
                        self.ensure_default_via_main()
                        print(f"[{time.strftime('%H:%M:%S')}] ⚠️ VPN недоступен, default ({self.default_iface})")

                    self.current_iface = best_vpn

                time.sleep(CHECK_INTERVAL)

            except Exception as e:
                print(f"❌ Ошибка: {e}")
                time.sleep(CHECK_INTERVAL)


# ============== ЗАПУСК ==============
if __name__ == "__main__":
    if os.geteuid() != 0:
        print("❌ Требуется root! Запустите с sudo")
        sys.exit(1)

    FailoverDaemon().loop()
