import logging
import os
import glob
import subprocess
from datetime import datetime
import time
import threading
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters, JobQueue
from telegram.constants import ParseMode
import paramiko
import tempfile

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
    def __init__(self, bot_token, chat_id, ssh_host, ssh_port, ssh_username, ssh_password):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.delete_client_mode = False
        self.application = Application.builder().token(self.bot_token).build()
        self.ssh_host = ssh_host
        self.ssh_port = ssh_port
        self.ssh_username = ssh_username
        self.ssh_password = ssh_password
        self.ssh_client = None
        self.debug_log_path = '/tmp/wg_bot_debug.log'
        threading.Thread(target=self.monitoring_loop, args=(self.application.bot,), daemon=True).start()

    def debug_log(self, msg):
        print(f"{datetime.now()} | {msg}")

    def ssh_connect(self):
        if self.ssh_client is not None:
            return self.ssh_client
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                hostname=self.ssh_host,
                port=self.ssh_port,
                username=self.ssh_username,
                password=self.ssh_password,
                timeout=10
            )
            self.ssh_client = client
            return client
        except Exception as e:
            print(f"[DEBUG] Ошибка подключения к SSH: {e}")
            self.ssh_client = None
            return None

    def ssh_exec(self, command):
        client = self.ssh_connect()
        if not client:
            return None
        try:
            stdin, stdout, stderr = client.exec_command(command)
            output = stdout.read().decode('utf-8')
            error = stderr.read().decode('utf-8')
            if error:
                print(f"[DEBUG] Ошибка выполнения команды по SSH: {error}")
            return output
        except Exception as e:
            print(f"[DEBUG] Ошибка выполнения команды по SSH: {e}")
            return None

    def get_wg_configs(self):
        output = self.ssh_exec("wg show")
        print(f"[DEBUG] wg show output: {output}")
        if not output:
            return []
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

    def get_wg_interface_status(self):
        try:
            result = subprocess.run(["wg", "show"], capture_output=True, text=True)
            return result.stdout
        except Exception as e:
            logger.error(f"Ошибка получения статуса wg: {e}")
            return None

    def read_file(self, path):
        output = self.ssh_exec(f"cat {path}")
        if output is None:
            return None
        return output.splitlines(keepends=True)

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
            "🔐 WireGuard Manager Bot\n\nВыберите действие:",
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
            status = self.ssh_exec("wg show")
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
                wg0_lines = self.read_file('/etc/wireguard/wg0.conf')
                message = "👥 <b>Список клиентов WireGuard:</b>\n\n"
                for i, config in enumerate(configs, 1):
                    peer = config.get('peer', 'Неизвестно')
                    latest_handshake = config.get('latest handshake', 'Нет данных')
                    transfer = config.get('transfer', 'Нет данных')
                    # Поиск имени клиента по публичному ключу (аналогично find_client_name_by_pubkey)
                    client_name = None
                    if peer and wg0_lines:
                        for idx, line in enumerate(wg0_lines):
                            if line.strip().startswith('PublicKey') and peer in line:
                                for j in range(idx-1, idx-3, -1):
                                    if j >= 0 and wg0_lines[j].strip().lower().startswith('# client:'):
                                        client_name = wg0_lines[j].strip()[9:].strip()
                                        # print(f"[DEBUG] Найден client_name для peer {peer}: {client_name}")
                                        break
                                break
                    message += f"<b>{i}. Peer:</b> <code>{peer[:20]}...</code>"
                    if client_name:
                        message += f"\n   📝 Имя конфига: <b>{client_name}</b>"
                    message += f"\n   📡 Последний handshake: {latest_handshake}"
                    message += f"\n   📊 Трафик: {transfer}\n\n"
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
        # Удаляем .conf файл по SSH
        conf_path = f"/etc/wireguard/clients/{name}.conf"
        rm_result = self.ssh_exec(f"rm -f {conf_path}")
        # Проверяем, был ли файл
        ls_result = self.ssh_exec(f"ls {conf_path}")
        if ls_result:
            await update.message.reply_text(f"Клиент с именем {name} не найден (файл не удалён).")
            return
        # Удаляем блок из wg0.conf по SSH
        await self.delete_client_block_from_wg0(update, context, name)

    async def delete_client_block_from_wg0(self, update, context, name):
        try:
            # Проверяем, есть ли такой клиент в wg0.conf
            lines = self.read_file('/etc/wireguard/wg0.conf')
            found = False
            if lines:
                for line in lines:
                    if line.strip().lower() == f"# client: {name.lower()}":
                        found = True
                        break
            if not found:
                await update.message.reply_text(f"Клиент с именем {name} не найден в wg0.conf.")
                return
            # Удаляем блок клиента по имени через awk по SSH (ваш вариант)
            awk_cmd = (
                f"awk 'BEGIN {{ del=0 }} /^# *[Cc]lient: *{name}$/ {{ del=1; next }} /^# *[Cc]lient:/ {{ if (del) {{ del=0 }} }} /^# *[Cc]lient:/ && del==0 {{ print; next }} !del' /etc/wireguard/wg0.conf > /etc/wireguard/wg0.conf.tmp && mv /etc/wireguard/wg0.conf.tmp /etc/wireguard/wg0.conf"
            )
            self.ssh_exec(awk_cmd)
            # Перезапускаем WireGuard для применения изменений по SSH
            await update.message.reply_text("🔄 Перезапуск WireGuard интерфейса...")
            restart_result = self.ssh_exec("wg-quick down wg0 && wg-quick up wg0")
            if restart_result is not None:
                await update.message.reply_text(f"✅ Клиент {name} успешно удалён и WireGuard перезапущен")
            else:
                await update.message.reply_text(f"⚠️ Клиент {name} удалён, но произошла ошибка при перезапуске WireGuard")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка при удалении клиента: {e}")

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

    def find_client_name_by_pubkey(self, pubkey):
        """Ищет имя клиента по публичному ключу в wg0.conf (# Client: ... за 2 строки выше PublicKey)"""
        lines = self.read_file('/etc/wireguard/wg0.conf')
        if not lines:
            return None
        for i, line in enumerate(lines):
            if line.strip().startswith('PublicKey') and pubkey in line:
                # Ищем # Client: ... максимум за 2 строки выше
                for j in range(i-1, i-3, -1):
                    if j >= 0 and lines[j].strip().lower().startswith('# client:'):
                        return lines[j].strip()[9:].strip()  # Обрезаем '# Client:'
        return None

    def get_pubkey_to_name_map(self):
        """Возвращает словарь pubkey -> client_name для всех клиентов из wg0.conf по SSH"""
        lines = self.read_file('/etc/wireguard/wg0.conf')
        pubkey_to_name = {}
        if not lines:
            return pubkey_to_name
        current_name = None
        for line in lines:
            l = line.strip()
            if l.lower().startswith('# client:'):
                current_name = l[9:].strip()
            elif l.startswith('PublicKey'):
                pubkey = l.split('=', 1)[-1].strip()
                if current_name:
                    pubkey_to_name[pubkey] = current_name
                current_name = None
            elif l.startswith('[Peer]'):
                current_name = None
        return pubkey_to_name

    async def send_new_client_notification(self, context, config, bot=None):
        print(f"[DEBUG] Вызвана send_new_client_notification с config: {config}")
        pubkey = config.get('peer')
        client_name = self.find_client_name_by_pubkey(pubkey) if pubkey else None
        message = "🆕 <b>Новый клиент WireGuard!</b>\n\n"
        if client_name:
            message += f"📝 <b>Имя клиента:</b> {client_name}\n"
        if pubkey:
            message += f"🔑 <b>Публичный ключ:</b> <code>{pubkey[:20]}...</code>\n"
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
        # print(f"[DEBUG] tg_bot: {tg_bot}")
        if tg_bot:
            try:
                await tg_bot.send_message(
                    chat_id=self.chat_id,
                    text=message,
                    parse_mode=ParseMode.HTML
                )
                # print(f"[DEBUG] Сообщение отправлено: {message}")
            except Exception as e:
                # print(f"[DEBUG] Ошибка при отправке сообщения: {e}")
                pass
        else:
            # print("[DEBUG] tg_bot не определён, сообщение не отправлено")
            pass

    def get_current_peers(self):
        configs = self.get_wg_configs()
        return {c.get('peer') for c in configs if c.get('peer')}

    def get_peer_info(self, peer_pubkey):
        configs = self.get_wg_configs()
        for c in configs:
            if c.get('peer') == peer_pubkey:
                return c
        return None

    def monitoring_loop(self, bot):
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        prev_peers = set()
        while True:
            try:
                current_peers = self.get_current_peers()
                new_peers = current_peers - prev_peers
                # self.debug_log(f"monitoring_loop: current_peers={current_peers}, prev_peers={prev_peers}, new_peers={new_peers}")
                if new_peers:
                    for peer in new_peers:
                        config = self.get_peer_info(peer)
                        if config:
                            loop.run_until_complete(self.send_new_client_notification(None, config, bot=bot))
                    prev_peers = current_peers
                else:
                    prev_peers = current_peers
                time.sleep(60)
            except Exception as e:
                # self.debug_log(f"Ошибка в monitoring_loop: {e}")
                time.sleep(60)

    def run(self):
        application = self.application
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), self.menu_handler))
        application.add_handler(CallbackQueryHandler(self.menu_handler))
        print("🤖 WireGuard Bot запущен...")
        # self.debug_log("WireGuard Bot запущен...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    # Загрузите токен и chat_id из вашего файла конфигурации или переменных окружения
    # Пример:
    # bot_token = os.environ["BOT_TOKEN"]
    # chat_id = os.environ["CHAT_ID"]
    # Или загрузите из файла, как раньше
    from config import load_config
    config = load_config()
    bot_token = config["BOT_TOKEN"]
    chat_id = config["CHAT_ID"]
    ssh_host = config["SSH_HOST"]
    ssh_port = config["SSH_PORT"]
    ssh_username = config["SSH_USERNAME"]
    ssh_password = config["SSH_PASSWORD"]
    bot = WireGuardBot(bot_token, chat_id, ssh_host, ssh_port, ssh_username, ssh_password)
    bot.run() 