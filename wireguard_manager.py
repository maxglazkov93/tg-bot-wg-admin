import paramiko
import re
import json
from datetime import datetime
import os

class WireGuardManager:
    def __init__(self, ssh_host, ssh_port, ssh_username, ssh_password):
        self.ssh_host = ssh_host
        self.ssh_port = ssh_port
        self.ssh_username = ssh_username
        self.ssh_password = ssh_password
        self.ssh_client = None
        
    def connect(self):
        """Устанавливает SSH соединение с сервером"""
        try:
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh_client.connect(
                hostname=self.ssh_host,
                port=self.ssh_port,
                username=self.ssh_username,
                password=self.ssh_password,
                timeout=10
            )
            return True
        except Exception as e:
            print(f"Ошибка подключения к SSH: {e}")
            return False
            
    def disconnect(self):
        """Закрывает SSH соединение"""
        if self.ssh_client:
            self.ssh_client.close()
            
    def execute_command(self, command):
        """Выполняет команду на сервере"""
        if not self.ssh_client:
            if not self.connect():
                return None, None
                
        try:
            if self.ssh_client:
                stdin, stdout, stderr = self.ssh_client.exec_command(command)
                output = stdout.read().decode('utf-8')
                error = stderr.read().decode('utf-8')
                return output, error
            else:
                return None, None
        except Exception as e:
            print(f"Ошибка выполнения команды: {e}")
            return None, None
            
    def get_wg_configs(self):
        """Получает список всех конфигураций WireGuard"""
        command = "wg show"
        output, error = self.execute_command(command)
        
        if error or not output:
            print(f"Ошибка получения конфигураций: {error}")
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
        """Получает статус интерфейса WireGuard"""
        command = "wg show"
        output, error = self.execute_command(command)
        
        if error:
            return None
            
        return output
        
    def get_new_configs(self, last_check_time=None):
        """Проверяет новые конфигурации с момента последней проверки"""
        # Получаем список файлов конфигураций
        command = "find /etc/wireguard/ -name '*.conf' -type f -newermt '{}' 2>/dev/null".format(
            last_check_time.strftime('%Y-%m-%d %H:%M:%S') if last_check_time else '1 hour ago'
        )
        
        output, error = self.execute_command(command)
        
        if error or not output:
            print(f"Ошибка поиска новых конфигураций: {error}")
            return []
            
        new_configs = []
        for config_file in output.strip().split('\n'):
            if config_file:
                config_info = self.parse_config_file(config_file)
                if config_info:
                    new_configs.append(config_info)
                    
        return new_configs
        
    def parse_config_file(self, config_path):
        """Парсит файл конфигурации WireGuard"""
        command = f"cat {config_path}"
        output, error = self.execute_command(command)
        
        if error or not output:
            return None
            
        config_info = {
            'filename': os.path.basename(config_path),
            'path': config_path,
            'created_time': None,
            'client_name': None,
            'public_key': None,
            'allowed_ips': None,
            'endpoint': None
        }
        
        # Получаем время создания файла
        time_command = f"stat -c %y {config_path}"
        time_output, _ = self.execute_command(time_command)
        if time_output:
            config_info['created_time'] = time_output.strip()
            
        # Парсим содержимое конфигурации
        for line in output.split('\n'):
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
        
    def get_client_stats(self, public_key):
        """Получает статистику клиента по публичному ключу"""
        command = f"wg show | grep -A 10 'peer: {public_key}'"
        output, error = self.execute_command(command)
        
        if error or not output:
            return None
            
        stats = {}
        for line in output.split('\n'):
            if ':' in line:
                key, value = line.split(':', 1)
                stats[key.strip()] = value.strip()
                
        return stats 

    def read_remote_file(self, path):
        """Читает файл на сервере по SSH и возвращает список строк"""
        output, error = self.execute_command(f'cat {path}')
        if error or not output:
            return None
        return output.splitlines() 

    def list_remote_files(self, pattern):
        """Возвращает список файлов по SSH по заданному шаблону (например, /etc/wireguard/clients/*.conf)"""
        output, error = self.execute_command(f'ls {pattern}')
        if error or not output:
            return []
        return output.splitlines() 