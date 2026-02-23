# Сохранить в /usr/local/bin/manage.py
# Панель управления Net Failover
import os, time, subprocess, socket, sys

CONF_DIR = "/etc/net_manager"
CHAIN_FILE = f"{CONF_DIR}/chain.conf"
ROUTES_FILE = f"{CONF_DIR}/routes.txt"

def run_res(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()

def check_status(iface):
    """Проверка статуса интерфейса"""
    if not os.path.exists(f"/sys/class/net/{iface}"): return "🔴 OFF"
    # Проверка WireGuard
    wg = run_res(f"wg show {iface} latest-handshake | awk '{{print $2}}'")
    if wg and wg != "0": return "🟢 WG-OK"
    # Проверка ping
    res = subprocess.call(["ping", "-c", "1", "-W", "1", "-I", iface, "1.1.1.1"], 
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return "🟢 ACTIVE" if res == 0 else "🔴 DOWN"

def get_default_interface():
    """Получение дефолтного интерфейса автоматически"""
    def_line = run_res("ip route show default")
    if def_line and "dev" in def_line:
        parts = def_line.split()
        if 'dev' in parts:
            dev_idx = parts.index('dev')
            if dev_idx + 1 < len(parts):
                return parts[dev_idx + 1]
    return "UNKNOWN"

def draw_dashboard():
    """Отображение дашборда"""
    def_iface = get_default_interface()

    print("=" * 65)
    print("🚀 NET FAILOVER DASHBOARD")
    print("=" * 65)
    print(f"🏠 DEFAULT:     {def_iface} | {check_status(def_iface)}")
    print(f"🌍 EXTERNAL IP: {run_res('curl -s https://api.ipify.org --max-time 2') or 'Timeout'}")

    # Читаем цепочку VPN
    if os.path.exists(CHAIN_FILE):
        with open(CHAIN_FILE) as f:
            vpn_chain = [l.strip() for l in f if l.strip() and not l.startswith('#')]
    else:
        vpn_chain = []

    print("-" * 65)
    print("🔐 VPN ИНТЕРФЕЙСЫ (для маршрутизации специфических IP):")
    if vpn_chain:
        for idx, iface in enumerate(vpn_chain, 1):
            status = check_status(iface)
            print(f"   {idx}. {iface:<15} {status}")
    else:
        print("   (не настроены)")

    print("-" * 65)
    print(f"{'ВСЕ ИНТЕРФЕЙСЫ':<15} | {'STATUS':<15}")
    for i in sorted([iface for iface in os.listdir('/sys/class/net/') if iface != 'lo']):
        print(f"{i:<15} | {check_status(i)}")
    print("=" * 65)

def menu():
    """Главное меню"""
    while True:
        os.system('clear')
        draw_dashboard()

        print("\n📋 МЕНЮ:")
        print("1. Редактировать routes.txt (IP для маршрутизации)")
        print("2. Редактировать chain.conf (VPN интерфейсы)")
        print("3. Проверить активные маршруты")
        print("4. Перезапустить службу")
        print("5. Просмотр логов")
        print("6. Статус службы")
        print("0. Выход")

        c = input("\n> ")

        if c == '1':
            os.system(f"nano {ROUTES_FILE}")
        elif c == '2':
            os.system(f"nano {CHAIN_FILE}")
        elif c == '3':
            os.system('clear')
            print("🚦 АКТИВНЫЕ МАРШРУТЫ:\n")
            if os.path.exists(ROUTES_FILE):
                with open(ROUTES_FILE) as f:
                    targets = [l.strip() for l in f if l.strip() and not l.startswith('#')]
                    if targets:
                        for t in targets:
                            result = run_res(f"ip route show {t}")
                            if result:
                                print(f"{t} -> {result}")
                            else:
                                print(f"{t} -> (маршрут не задан)")
                    else:
                        print("routes.txt пуст")
            input("\nНажмите Enter...")
        elif c == '4':
            print("⏳ Перезапуск службы...")
            os.system("systemctl restart net-failover")
            time.sleep(2)
            print("✅ Готово!")
            time.sleep(1)
        elif c == '5':
            os.system("journalctl -u net-failover -n 30 -f")
        elif c == '6':
            os.system("systemctl status net-failover")
            input("\nНажмите Enter...")
        elif c == '0':
            break

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("❌ Требуется root! Используйте: sudo python3 manage.py")
        sys.exit(1)
    menu()
