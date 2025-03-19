#!/usr/bin/env python3
"""
Script for comparing EasyBuild modules on two Linux servers.
Identifies missing, extra, and newer modules.
"""

import paramiko
import argparse
import re
import datetime
from dataclasses import dataclass
from typing import Dict, List, Set, Tuple, Optional

@dataclass
class ModuleInfo:
    """Information about an EasyBuild module"""
    name: str                # Module name
    version: str             # Module version
    build_time: datetime.datetime  # Build time
    full_name: str           # Full module name with version

def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description="Compare EasyBuild modules on two servers")
    parser.add_argument('-s1', '--server1', required=True, help="First server (user@hostname)")
    parser.add_argument('-s2', '--server2', required=True, help="Second server (user@hostname)")
    parser.add_argument('-k', '--key', help="Path to private SSH key")
    parser.add_argument('-p', '--password', help="Password for SSH connection")
    
    return parser.parse_args()

def connect_to_server(server: str, key_path: Optional[str] = None, password: Optional[str] = None) -> paramiko.SSHClient:
    """Connect to server via SSH"""
    user, host = server.split('@')
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        if key_path:
            key = paramiko.RSAKey.from_private_key_file(key_path)
            client.connect(hostname=host, username=user, pkey=key)
        else:
            client.connect(hostname=host, username=user, password=password)
        print(f"Successfully connected to {server}")
        return client
    except Exception as e:
        print(f"Connection error to {server}: {e}")
        raise

def get_modules_list(ssh_client: paramiko.SSHClient) -> List[ModuleInfo]:
    """Get list of modules from server"""
    modules = []
    
    # Get list of modules
    stdin, stdout, stderr = ssh_client.exec_command("ml --terse avail 2>&1 | grep -E '/[^/]+$' | grep -v ':$'")
    module_names = [line.strip() for line in stdout.readlines()]
    
    for full_name in module_names:
        # For each module, request information about build time
        # Assuming build time can be found in module metadata or in the filesystem
        cmd = f"stat -c '%z' $(module show {full_name} 2>&1 | grep -o '/.*\\.lua' | head -1) 2>/dev/null || echo 'Unknown'"
        stdin, stdout, stderr = ssh_client.exec_command(cmd)
        build_time_str = stdout.read().decode().strip()
        
        try:
            if build_time_str != 'Unknown':
                build_time = datetime.datetime.strptime(build_time_str.split('.')[0], '%Y-%m-%d %H:%M:%S')
            else:
                build_time = datetime.datetime(1970, 1, 1)  # If build time is unknown
        except ValueError:
            build_time = datetime.datetime(1970, 1, 1)
        
        # Split full module name into name and version
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
    Compare modules on two servers
    
    Returns a tuple of three elements:
    1. List of modules present only on the first server
    2. List of modules present only on the second server
    3. List of module pairs (module1, module2), where module1 is older than module2
    """
    # Create dictionaries for quick access
    modules_dict1 = {module.full_name: module for module in modules1}
    modules_dict2 = {module.full_name: module for module in modules2}
    
    # Find unique modules
    unique_modules1 = [module for name, module in modules_dict1.items() if name not in modules_dict2]
    unique_modules2 = [module for name, module in modules_dict2.items() if name not in modules_dict1]
    
    # Find modules with different build times
    newer_modules = []
    
    # First group modules by base name (without version)
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
    
    # Now compare versions for each base name
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
        # Connect to servers
        ssh1 = connect_to_server(args.server1, args.key, args.password)
        ssh2 = connect_to_server(args.server2, args.key, args.password)
        
        # Get module lists
        print(f"Getting module list from server {args.server1}...")
        modules1 = get_modules_list(ssh1)
        print(f"Found {len(modules1)} modules")
        
        print(f"Getting module list from server {args.server2}...")
        modules2 = get_modules_list(ssh2)
        print(f"Found {len(modules2)} modules")
        
        # Compare modules
        unique_modules1, unique_modules2, newer_modules = compare_modules(modules1, modules2)
        
        # Output results
        print("\n" + "="*80)
        print(f"Modules present only on {args.server1} ({len(unique_modules1)}):")
        print("="*80)
        for module in sorted(unique_modules1, key=lambda m: m.full_name):
            print(f"{module.full_name} (build: {module.build_time})")
        
        print("\n" + "="*80)
        print(f"Modules present only on {args.server2} ({len(unique_modules2)}):")
        print("="*80)
        for module in sorted(unique_modules2, key=lambda m: m.full_name):
            print(f"{module.full_name} (build: {module.build_time})")
        
        print("\n" + "="*80)
        print(f"Modules with different build times ({len(newer_modules)}):")
        print("="*80)
        for older, newer in sorted(newer_modules, key=lambda pair: pair[0].full_name):
            server_older = args.server1 if older in modules1 else args.server2
            server_newer = args.server1 if newer in modules1 else args.server2
            print(f"Module: {older.full_name}")
            print(f"  On {server_older}: {older.build_time}")
            print(f"  On {server_newer}: {newer.build_time}")
            print(f"  Newer version on {server_newer}")
            print()
        
        # Close connections
        ssh1.close()
        ssh2.close()
        
    except Exception as e:
        print(f"An error occurred: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
