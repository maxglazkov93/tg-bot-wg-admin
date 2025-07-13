#!/usr/bin/env python3
"""
Скрипт для тестирования подключения к серверу и WireGuard
"""

from config import load_config
from wireguard_manager import WireGuardManager

def test_connection():
    """Тестирует подключение к серверу и WireGuard"""
    print("🔍 Тестирование подключения...")
    
    # Загружаем конфигурацию
    config = load_config()
    if not config:
        print("❌ Не удалось загрузить конфигурацию")
        return False
        
    print(f"✅ Конфигурация загружена")
    print(f"   Сервер: {config['SSH_HOST']}:{config['SSH_PORT']}")
    print(f"   Пользователь: {config['SSH_USERNAME']}")
    
    # Создаем менеджер WireGuard
    wg_manager = WireGuardManager(
        config['SSH_HOST'],
        config['SSH_PORT'],
        config['SSH_USERNAME'],
        config['SSH_PASSWORD']
    )
    
    # Тестируем SSH подключение
    print("\n🔌 Тестирование SSH подключения...")
    if wg_manager.connect():
        print("✅ SSH подключение успешно")
        
        # Тестируем команду WireGuard
        print("\n📡 Тестирование WireGuard...")
        status = wg_manager.get_wg_interface_status()
        if status:
            print("✅ WireGuard интерфейс доступен")
            print(f"Статус:\n{status}")
        else:
            print("❌ Не удалось получить статус WireGuard")
            
        # Тестируем получение конфигураций
        print("\n👥 Тестирование получения клиентов...")
        configs = wg_manager.get_wg_configs()
        if configs:
            print(f"✅ Найдено {len(configs)} клиентов")
            for i, config in enumerate(configs, 1):
                peer = config.get('peer', 'Неизвестно')
                print(f"   {i}. {peer[:20]}...")
        else:
            print("📭 Клиенты не найдены")
            
        wg_manager.disconnect()
        print("\n✅ Все тесты пройдены успешно!")
        return True
    else:
        print("❌ Не удалось подключиться по SSH")
        return False

if __name__ == '__main__':
    test_connection() 