import logging
import os
import glob
import subprocess
from datetime import datetime
import time
import threading
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ParseMode

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

MENU_BUTTONS = [
    ["📊 Статус WireGuard", "👥 Список клиентов"],
    ["🗑 Удалить клиента"]
]

class WireGuardBot:
    def __init__(self, bot_token, chat_id):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.delete_client_mode = False
        self.application = Application.builder().token(self.bot_token).build()
        threading.Thread(target=self.monitoring_loop, args=(self.application.bot,), daemon=True).start()

    def get_wg_configs(self):
        try:
            result = subprocess.run(["wg", "show"], capture_output=True, text=True)
            output = result.stdout
            configs = []
            current_peer = None
            for line in output.split('\n'):
                if line.startswith('peer:'):
                    if current_peer:
                        configs.append(current_peer)
                    current_peer = {'peer': line.split(':')[1].strip()}
                elif current_peer and line.strip():
                    if ':' in line:
                        key, value = line.split(':', 1)
                        current_peer[key.strip()] = value.strip()
            if current_peer:
                configs.append(current_peer)
            return configs
        except Exception as e:
            logger.error(f"Ошибка получения конфигов wg: {e}")
            return []

    def get_wg_interface_status(self):
        try:
            result = subprocess.run(["wg", "show"], capture_output=True, text=True)
            return result.stdout
        except Exception as e:
            logger.error(f"Ошибка получения статуса wg: {e}")
            return None

    def read_file(self, path):
        try:
            with open(path, 'r') as f:
                return f.readlines()
        except Exception as e:
            logger.error(f"Ошибка чтения файла {path}: {e}")
            return None

    def restart_wireguard(self):
        """Перезапускает WireGuard интерфейс"""
        try:
            # Останавливаем интерфейс
            result = subprocess.run(["wg-quick", "down", "wg0"], capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"Ошибка остановки wg0: {result.stderr}")
                return False
            
            # Запускаем интерфейс
            result = subprocess.run(["wg-quick", "up", "wg0"], capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"Ошибка запуска wg0: {result.stderr}")
                return False
            
            logger.info("WireGuard интерфейс успешно перезапущен")
            return True
        except Exception as e:
            logger.error(f"Ошибка перезапуска WireGuard: {e}")
            return False

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if str(update.effective_chat.id) != str(self.chat_id):
            await update.message.reply_text("У вас нет доступа к этому боту.")
            return
        reply_markup = ReplyKeyboardMarkup(MENU_BUTTONS, resize_keyboard=True)
        await update.message.reply_text(
            "🔐 WireGuard Manager Bot (Локальный)\n\nВыберите действие:",
            reply_markup=reply_markup
        )

    async def menu_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if str(update.effective_chat.id) != str(self.chat_id):
            await update.message.reply_text("У вас нет доступа к этому боту.")
            return
        text = update.message.text
        if self.delete_client_mode:
            await self.handle_delete_client_name(update, context)
            return
        if text == "📊 Статус WireGuard":
            await self.show_status_menu(update, context)
        elif text == "👥 Список клиентов":
            await self.show_clients_menu(update, context)
        elif text == "🗑 Удалить клиента":
            self.delete_client_mode = True
            await update.message.reply_text("Введите имя клиента (без .conf), которого нужно удалить:")
        else:
            await update.message.reply_text("Неизвестная команда. Используйте меню.")

    async def show_status_menu(self, update, context):
        try:
            status = self.get_wg_interface_status()
            if status:
                await update.message.reply_text(
                    f"📊 Статус WireGuard:\n\n<pre>{status}</pre>",
                    parse_mode=ParseMode.HTML
                )
            else:
                await update.message.reply_text("❌ Не удалось получить статус WireGuard")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")

    async def show_clients_menu(self, update, context):
        try:
            configs = self.get_wg_configs()
            if configs:
                message = "👥 <b>Список клиентов WireGuard:</b>\n\n"
                for i, config in enumerate(configs, 1):
                    peer = config.get('peer', 'Неизвестно')
                    latest_handshake = config.get('latest handshake', 'Нет данных')
                    transfer = config.get('transfer', 'Нет данных')
                    message += f"<b>{i}. Peer:</b> <code>{peer[:20]}...</code>\n"
                    message += f"   📡 Последний handshake: {latest_handshake}\n"
                    message += f"   📊 Трафик: {transfer}\n\n"
                await update.message.reply_text(message, parse_mode=ParseMode.HTML)
            else:
                await update.message.reply_text("📭 Нет активных клиентов")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")

    async def handle_delete_client_name(self, update, context):
        name = update.message.text.strip()
        self.delete_client_mode = False
        if not name:
            await update.message.reply_text("Имя не может быть пустым. Операция отменена.")
            return
        # Удаляем .conf файл локально
        conf_path = f"/etc/wireguard/clients/{name}.conf"
        if os.path.exists(conf_path):
            os.remove(conf_path)
        else:
            await update.message.reply_text(f"Клиент с именем {name} не найден (файл не удалён).")
            return
        # Удаляем блок из wg0.conf
        await self.delete_client_block_from_wg0(update, context, name)

    async def delete_client_block_from_wg0(self, update, context, name):
        lines = self.read_file('/etc/wireguard/wg0.conf')
        if not lines:
            await update.message.reply_text("Не удалось прочитать wg0.conf")
            return
        new_lines = []
        skip = 0
        found = False
        for i, line in enumerate(lines):
            if skip > 0:
                skip -= 1
                continue
            if line.strip().lower().startswith(f"# client: {name.lower()}"):
                found = True
                skip = 3
                continue
            new_lines.append(line.rstrip('\n'))
        if not found:
            await update.message.reply_text(f"Блок клиента с именем {name} не найден в wg0.conf.")
            return
        # Перезаписываем wg0.conf
        with open('/etc/wireguard/wg0.conf', 'w') as f:
            f.write('\n'.join(new_lines) + '\n')
        
        # Перезапускаем WireGuard для применения изменений
        await update.message.reply_text("🔄 Перезапуск WireGuard интерфейса...")
        if self.restart_wireguard():
            await update.message.reply_text(f"✅ Клиент {name} успешно удалён и WireGuard перезапущен")
        else:
            await update.message.reply_text(f"⚠️ Клиент {name} удалён, но произошла ошибка при перезапуске WireGuard")

    def find_client_comment_in_wg0(self, peer_pubkey):
        lines = self.read_file('/etc/wireguard/wg0.conf')
        if not lines:
            return None
        try:
            for i, line in enumerate(lines):
                line_stripped = line.strip()
                if line_stripped.startswith('PublicKey'):
                    key_value = line_stripped.split('=', 1)[-1].strip()
                    if key_value == peer_pubkey:
                        for j in range(i-1, -1, -1):
                            comment = lines[j].strip()
                            if comment.lstrip().startswith('#'):
                                comment_text = comment.lstrip('#').strip()
                                if comment_text.lower().startswith('client:'):
                                    comment_text = comment_text[7:].strip()
                                return comment_text
                            if comment == '':
                                continue
        except Exception:
            pass
        return None

    async def send_new_client_notification(self, context, config, bot=None):
        message = "🆕 <b>Новый клиент WireGuard!</b>\n\n"
        client_comment = None
        if config.get('peer'):
            client_comment = self.find_client_comment_in_wg0(config['peer'])
        if client_comment:
            message += f"📝 <b>Имя клиента:</b> {client_comment}\n"
        if config.get('peer'):
            message += f"🔑 <b>Публичный ключ:</b> <code>{config['peer'][:20]}...</code>\n"
        if config.get('client_name'):
            message += f"👤 <b>Клиент:</b> {config['client_name']}\n"
        if config.get('public_key') and not config.get('peer'):
            message += f"🔑 <b>Публичный ключ:</b> <code>{config['public_key'][:20]}...</code>\n"
        if config.get('allowed_ips'):
            message += f"🌐 <b>Разрешенные IP:</b> {config['allowed_ips']}\n"
        if config.get('created_time'):
            message += f"🕐 <b>Создан:</b> {config['created_time']}\n"
        tg_bot = None
        if context and hasattr(context, 'bot'):
            tg_bot = context.bot
        elif bot:
            tg_bot = bot
        if tg_bot:
            await tg_bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode=ParseMode.HTML
            )

    def get_current_peers(self):
        configs = self.get_wg_configs()
        return {c.get('peer') for c in configs if c.get('peer')}

    def get_peer_info(self, peer_pubkey):
        configs = self.get_wg_configs()
        for c in configs:
            if c.get('peer') == peer_pubkey:
                return c
        return None

    def get_wg_config_files(self):
        """Получает список файлов конфигураций клиентов"""
        try:
            result = subprocess.run(["ls", "/etc/wireguard/clients/"], capture_output=True, text=True)
            if result.returncode == 0:
                files = [f.strip() for f in result.stdout.split('\n') if f.strip()]
                return files
            return []
        except Exception as e:
            logger.error(f"Ошибка получения файлов конфигураций: {e}")
            return []

    def parse_config_file_info(self, config_path):
        """Парсит информацию из файла конфигурации клиента"""
        try:
            lines = self.read_file(config_path)
            if not lines:
                return None
                
            config_info = {
                'filename': os.path.basename(config_path),
                'path': config_path,
                'client_name': None,
                'public_key': None,
                'allowed_ips': None,
                'endpoint': None
            }
            
            # Получаем время создания файла
            try:
                result = subprocess.run(["stat", "-c", "%y", config_path], capture_output=True, text=True)
                if result.returncode == 0:
                    config_info['created_time'] = result.stdout.strip()
            except:
                pass
            
            # Парсим содержимое конфигурации
            for line in lines:
                line = line.strip()
                if line.startswith('#') and 'name' in line.lower():
                    config_info['client_name'] = line.split('#')[1].strip()
                elif line.startswith('PublicKey ='):
                    config_info['public_key'] = line.split('=')[1].strip()
                elif line.startswith('AllowedIPs ='):
                    config_info['allowed_ips'] = line.split('=')[1].strip()
                elif line.startswith('Endpoint ='):
                    config_info['endpoint'] = line.split('=')[1].strip()
                    
            return config_info
        except Exception as e:
            logger.error(f"Ошибка парсинга файла {config_path}: {e}")
            return None

    def monitoring_loop(self, bot):
        prev_peers = set()
        prev_config_files = set()
        while True:
            try:
                # Мониторинг активных peer'ов
                current_peers = self.get_current_peers()
                new_peers = current_peers - prev_peers
                if new_peers:
                    for peer in new_peers:
                        config = self.get_peer_info(peer)
                        if config:
                            import asyncio
                            asyncio.run_coroutine_threadsafe(
                                self.send_new_client_notification(None, config, bot=bot),
                                self.application.loop
                            )
                    prev_peers = current_peers
                else:
                    prev_peers = current_peers
                
                # Мониторинг новых файлов конфигураций
                current_config_files = set(self.get_wg_config_files())
                new_config_files = current_config_files - prev_config_files
                if new_config_files:
                    for config_file in new_config_files:
                        if config_file.endswith('.conf'):
                            # Получаем информацию о новом клиенте
                            config_info = self.parse_config_file_info(f"/etc/wireguard/clients/{config_file}")
                            if config_info:
                                import asyncio
                                asyncio.run_coroutine_threadsafe(
                                    self.send_new_client_notification(None, config_info, bot=bot),
                                    self.application.loop
                                )
                    prev_config_files = current_config_files
                else:
                    prev_config_files = current_config_files
                
                time.sleep(30)  # Проверяем каждые 30 секунд
            except Exception as e:
                logger.error(f"Ошибка в цикле мониторинга: {e}")
                time.sleep(60)

    def run(self):
        application = self.application
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), self.menu_handler))
        application.add_handler(CallbackQueryHandler(self.menu_handler))
        print("🤖 WireGuard Bot (Локальный) запущен...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    # Загружаем конфигурацию
    from config import load_config
    config = load_config()
    if not config:
        print("❌ Не удалось загрузить конфигурацию из api_token.txt")
        exit(1)
    
    bot_token = config["BOT_TOKEN"]
    chat_id = config["CHAT_ID"]
    bot = WireGuardBot(bot_token, chat_id)
    bot.run() 