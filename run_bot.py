#!/usr/bin/env python3
"""
Скрипт для запуска WireGuard Telegram бота
"""

import sys
import traceback
from bot import WireGuardBot

def main():
    """Основная функция запуска бота"""
    try:
        print("🚀 Запуск WireGuard Telegram Bot...")
        bot = WireGuardBot()
        bot.run()
    except KeyboardInterrupt:
        print("\n⏹ Бот остановлен пользователем")
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        print("Подробности:")
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main() 