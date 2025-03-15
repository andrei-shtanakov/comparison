#!/usr/bin/env python3
"""
Скрипт для сравнения модулей EasyBuild на двух Linux-серверах.
Определяет отсутствующие, лишние и более новые модули.
"""

import paramiko
import argparse
import re
import datetime
from dataclasses import dataclass
from typing import Dict, List, Set, Tuple, Optional

@dataclass
class ModuleInfo:
    """Информация о модуле EasyBuild"""
    name: str                # Имя модуля
    version: str             # Версия модуля
    build_time: datetime.datetime  # Время сборки
    full_name: str           # Полное имя модуля с версией

def parse_arguments():
    """Парсинг аргументов командной строки"""
    parser = argparse.ArgumentParser(description="Сравнение модулей EasyBuild на двух серверах")
    parser.add_argument('-s1', '--server1', required=True, help="Первый сервер (user@hostname)")
    parser.add_argument('-s2', '--server2', required=True, help="Второй сервер (user@hostname)")
    parser.add_argument('-k', '--key', help="Путь к приватному SSH ключу")
    parser.add_argument('-p', '--password', help="Пароль для SSH подключения")
    
    return parser.parse_args()

def connect_to_server(server: str, key_path: Optional[str] = None, password: Optional[str] = None) -> paramiko.SSHClient:
    """Подключение к серверу по SSH"""
    user, host = server.split('@')
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        if key_path:
            key = paramiko.RSAKey.from_private_key_file(key_path)
            client.connect(hostname=host, username=user, pkey=key)
        else:
            client.connect(hostname=host, username=user, password=password)
        print(f"Успешное подключение к {server}")
        return client
    except Exception as e:
        print(f"Ошибка подключения к {server}: {e}")
        raise

def get_modules_list(ssh_client: paramiko.SSHClient) -> List[ModuleInfo]:
    """Получение списка модулей с сервера"""
    modules = []
    
    # Получение списка модулей
    stdin, stdout, stderr = ssh_client.exec_command("module avail -t 2>&1 | grep -v '^-\\|^$\\|: '")
    module_names = [line.strip() for line in stdout.readlines()]
    
    for full_name in module_names:
        # Для каждого модуля запрашиваем информацию о времени сборки
        # Предполагаем, что время сборки можно найти в метаданных модуля или в файловой системе
        cmd = f"stat -c '%y' $(module show {full_name} 2>&1 | grep -o '/.*\\.lua' | head -1) 2>/dev/null || echo 'Unknown'"
        stdin, stdout, stderr = ssh_client.exec_command(cmd)
        build_time_str = stdout.read().decode().strip()
        
        try:
            if build_time_str != 'Unknown':
                build_time = datetime.datetime.strptime(build_time_str.split('.')[0], '%Y-%m-%d %H:%M:%S')
            else:
                build_time = datetime.datetime(1970, 1, 1)  # Если время сборки неизвестно
        except ValueError:
            build_time = datetime.datetime(1970, 1, 1)
        
        # Разбиваем полное имя модуля на имя и версию
        parts = full_name.split('/')
        if len(parts) >= 2:
            name = parts[0]
            version = parts[1]
        else:
            name = full_name
            version = "unknown"
        
        modules.append(ModuleInfo(name=name, version=version, build_time=build_time, full_name=full_name))
    
    return modules

def compare_modules(modules1: List[ModuleInfo], modules2: List[ModuleInfo]) -> Tuple[List[ModuleInfo], List[ModuleInfo], List[Tuple[ModuleInfo, ModuleInfo]]]:
    """
    Сравнение модулей на двух серверах
    
    Возвращает кортеж из трех элементов:
    1. Список модулей, присутствующих только на первом сервере
    2. Список модулей, присутствующих только на втором сервере
    3. Список пар модулей (модуль1, модуль2), где модуль1 старше модуля2
    """
    # Создаем словари для быстрого доступа
    modules_dict1 = {module.full_name: module for module in modules1}
    modules_dict2 = {module.full_name: module for module in modules2}
    
    # Находим уникальные модули
    unique_modules1 = [module for name, module in modules_dict1.items() if name not in modules_dict2]
    unique_modules2 = [module for name, module in modules_dict2.items() if name not in modules_dict1]
    
    # Находим модули с разным временем сборки
    newer_modules = []
    
    # Сначала сгруппируем модули по базовому имени (без версии)
    modules_by_name1 = {}
    modules_by_name2 = {}
    
    for module in modules1:
        if module.name not in modules_by_name1:
            modules_by_name1[module.name] = []
        modules_by_name1[module.name].append(module)
    
    for module in modules2:
        if module.name not in modules_by_name2:
            modules_by_name2[module.name] = []
        modules_by_name2[module.name].append(module)
    
    # Теперь сравним версии для каждого базового имени
    for name in set(modules_by_name1.keys()) & set(modules_by_name2.keys()):
        for mod1 in modules_by_name1[name]:
            for mod2 in modules_by_name2[name]:
                if mod1.version == mod2.version and mod1.build_time != mod2.build_time:
                    if mod1.build_time < mod2.build_time:
                        newer_modules.append((mod1, mod2))
                    else:
                        newer_modules.append((mod2, mod1))
    
    return unique_modules1, unique_modules2, newer_modules

def main():
    args = parse_arguments()
    
    try:
        # Подключение к серверам
        ssh1 = connect_to_server(args.server1, args.key, args.password)
        ssh2 = connect_to_server(args.server2, args.key, args.password)
        
        # Получение списков модулей
        print(f"Получение списка модулей с сервера {args.server1}...")
        modules1 = get_modules_list(ssh1)
        print(f"Найдено {len(modules1)} модулей")
        
        print(f"Получение списка модулей с сервера {args.server2}...")
        modules2 = get_modules_list(ssh2)
        print(f"Найдено {len(modules2)} модулей")
        
        # Сравнение модулей
        unique_modules1, unique_modules2, newer_modules = compare_modules(modules1, modules2)
        
        # Вывод результатов
        print("\n" + "="*80)
        print(f"Модули, присутствующие только на {args.server1} ({len(unique_modules1)}):")
        print("="*80)
        for module in sorted(unique_modules1, key=lambda m: m.full_name):
            print(f"{module.full_name} (сборка: {module.build_time})")
        
        print("\n" + "="*80)
        print(f"Модули, присутствующие только на {args.server2} ({len(unique_modules2)}):")
        print("="*80)
        for module in sorted(unique_modules2, key=lambda m: m.full_name):
            print(f"{module.full_name} (сборка: {module.build_time})")
        
        print("\n" + "="*80)
        print(f"Модули с разным временем сборки ({len(newer_modules)}):")
        print("="*80)
        for older, newer in sorted(newer_modules, key=lambda pair: pair[0].full_name):
            server_older = args.server1 if older in modules1 else args.server2
            server_newer = args.server1 if newer in modules1 else args.server2
            print(f"Модуль: {older.full_name}")
            print(f"  На {server_older}: {older.build_time}")
            print(f"  На {server_newer}: {newer.build_time}")
            print(f"  Более новая версия на {server_newer}")
            print()
        
        # Закрытие подключений
        ssh1.close()
        ssh2.close()
        
    except Exception as e:
        print(f"Произошла ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
