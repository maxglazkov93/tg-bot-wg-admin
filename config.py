import os
import re

def load_config():
    """Загружает конфигурацию из файла api_token.txt"""
    config = {}
    
    try:
        with open('api_token.txt', 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Извлекаем токен бота
        token_match = re.search(r'token\s*=\s*([^\n]+)', content)
        if token_match:
            config['BOT_TOKEN'] = token_match.group(1).strip()
            
        # Извлекаем chat_id
        chat_id_match = re.search(r'chat_id\s*=\s*(\d+)', content)
        if chat_id_match:
            config['CHAT_ID'] = int(chat_id_match.group(1))
            
        # Извлекаем настройки WireGuard
        wg_ip_match = re.search(r'WG_SERVER_IP=([^\n]+)', content)
        if wg_ip_match:
            config['WG_SERVER_IP'] = wg_ip_match.group(1).strip()
            
        wg_port_match = re.search(r'WG_SERVER_PORT=(\d+)', content)
        if wg_port_match:
            config['WG_SERVER_PORT'] = int(wg_port_match.group(1))
            
        # Извлекаем SSH настройки
        ssh_host_match = re.search(r'SSH_HOST=([^\n]+)', content)
        if ssh_host_match:
            config['SSH_HOST'] = ssh_host_match.group(1).strip()
            
        ssh_port_match = re.search(r'SSH_PORT=(\d+)', content)
        if ssh_port_match:
            config['SSH_PORT'] = int(ssh_port_match.group(1))
            
        ssh_user_match = re.search(r'SSH_USERNAME=([^\n]+)', content)
        if ssh_user_match:
            config['SSH_USERNAME'] = ssh_user_match.group(1).strip()
            
        ssh_pass_match = re.search(r'SSH_PASSWORD=([^\n]+)', content)
        if ssh_pass_match:
            config['SSH_PASSWORD'] = ssh_pass_match.group(1).strip()
            
    except FileNotFoundError:
        print("Ошибка: Файл api_token.txt не найден!")
        return None
    except Exception as e:
        print(f"Ошибка при загрузке конфигурации: {e}")
        return None
        
    return config 