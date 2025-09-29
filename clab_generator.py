import pynetbox
import requests
import subprocess
import urllib3
import yaml
import os
import re
import time
import threading
import queue
from getpass import getpass
import argparse
from napalm import get_network_driver
from jinja2 import Environment, FileSystemLoader
from typing import List, Dict, Optional, Set
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import partial

# --- Configuration ---
class Config:
    NETBOX_URL = os.getenv('NETBOX_URL', 'http://your-netbox-url')
    NETBOX_TOKEN = os.getenv('NETBOX_TOKEN', 'your-netbox-api-token')
    DEVICE_USERNAME = os.getenv('DEVICE_USERNAME')
    DEVICE_PASSWORD = os.getenv('DEVICE_PASSWORD')
    VALID_ROLES = {
        'core', 'core-switch', 'clubhouse', 'dmz-switch', 'edge-router-switch',
        'firewall', 'l2-switch', 'idf-switch', 'l2-switch-enduser', 'l2-switch-wifi',
        'l2-switch-wired', 'lan-switch', 'leaf-router-switch', 'mpls-router',
        'oob-switch', 'oob-vpn-router', 'service-leaf-router-switch',
        'spine-router-switch', 'stringer', 'tapagg-switch', 'transit-router-switch',
        'vpn-router'
    }
    MAX_WORKERS = 10  # Maximum number of concurrent device connections

# Global set to track unreachable devices
unreachable_devices = set()

def get_devices_from_site(nb_api: pynetbox.api, site_name: str) -> Optional[List]:
    """Fetches all devices from a specific site in NetBox."""
    try:
        site = nb_api.dcim.sites.get(name__ie=site_name)
        if not site:
            print(f"   -> ❌ Error: Site '{site_name}' not found in NetBox")
            return None

        devices = list(nb_api.dcim.devices.filter(
            site_id=site.id,
            status='active',
            manufacturer='arista',
            role=list(Config.VALID_ROLES)
        ))

        if not devices:
            print(f"   -> 🟡 Warning: No active Arista devices with specified roles found in site '{site_name}'")
            return []

        print(f"   -> ✅ Found {len(devices)} devices in site '{site_name}'")
        for device in devices:
            print(f"        -> {device.name}")

        return devices

    except Exception as e:
        print(f"   -> ❌ Error connecting to NetBox or fetching devices: {e}")
        return None

def test_device_connectivity(device, username: str, password: str) -> bool:
    """Test if a device is reachable and mark it as unreachable if not."""
    if not device.primary_ip:
        print(f"   -> 🟡 {device.name}: No primary IP - marking as unreachable")
        unreachable_devices.add(device.name)
        return False

    device_ip = device.primary_ip.address.split('/')[0]
    print(f"   -> Testing connectivity to {device.name} ({device_ip})...")
    
    driver = get_network_driver('eos')
    eos_device = driver(hostname=device_ip, username=username, password=password, timeout=10)
    
    try:
        eos_device.open()
        eos_device.close()
        print(f"   -> ✅ {device.name}: Connection successful")
        return True
    except Exception as e:
        print(f"   -> ❌ {device.name}: Connection failed - {str(e)[:100]}...")
        unreachable_devices.add(device.name)
        return False

def get_device_config(device, username: str, password: str, configs_dir: str) -> None:
    """Retrieve and save device running configuration."""
    if device.name in unreachable_devices: return
    device_ip = device.primary_ip.address.split('/')[0]
    print(f"   -> Getting config for {device.name}...")
    driver = get_network_driver('eos')
    eos_device = driver(hostname=device_ip, username=username, password=password)
    try:
        eos_device.open()
        config_data = eos_device.get_config(retrieve='running')['running']
        config_filename = os.path.join(configs_dir, f"{device.name}.cfg")
        with open(config_filename, 'w') as f:
            f.write(config_data)
        print(f"   -> ✅ Saved config for {device.name}")
    except Exception as e:
        print(f"   -> ❌ Failed to get config for {device.name}: {str(e)[:100]}...")
        unreachable_devices.add(device.name)
    finally:
        if eos_device.is_alive(): eos_device.close()

def get_device_info(device, username: str, password: str, sn_dir: str) -> None:
    """Retrieve and save device serial number and MAC address."""
    if device.name in unreachable_devices: return
    device_ip = device.primary_ip.address.split('/')[0]
    print(f"   -> Getting info for {device.name}...")
    driver = get_network_driver('eos')
    eos_device = driver(hostname=device_ip, username=username, password=password)
    try:
        eos_device.open()
        version_output = eos_device.cli(['show version'])['show version']
        serial_number, system_mac = "UNKNOWN", "UNKNOWN"
        for line in version_output.splitlines():
            if re.search(r'serial number', line, re.IGNORECASE): serial_number = line.split(':')[1].strip()
            if re.search(r'system mac address', line, re.IGNORECASE): system_mac = line.split(':')[1].strip()
        sn_content = f"SERIALNUMBER={serial_number}\nSYSTEMMACADDR={system_mac}\n"
        sn_filename = os.path.join(sn_dir, f"{device.name}.txt")
        with open(sn_filename, 'w') as f:
            f.write(sn_content)
        print(f"   -> ✅ Saved serial/MAC for {device.name}")
    except Exception as e:
        print(f"   -> ❌ Failed to get info for {device.name}: {str(e)[:100]}...")
        unreachable_devices.add(device.name)
    finally:
        if eos_device.is_alive(): eos_device.close()

def test_device_connectivity_batch(devices: List, username: str, password: str) -> None:
    """Test connectivity to all devices in parallel."""
    print(f"\n{'='*50}")
    print(f"🔍 Testing Device Connectivity")
    print(f"{'='*50}")
    with ThreadPoolExecutor(max_workers=Config.MAX_WORKERS) as executor:
        list(executor.map(partial(test_device_connectivity, username=username, password=password), devices))
    
    reachable_count = len(devices) - len(unreachable_devices)
    print(f"\n   -> 📊 Connectivity Summary: ✅ {reachable_count} Reachable, ❌ {len(unreachable_devices)} Unreachable")

def provision_node_files(devices: List, username: str, password: str, lab_dir: str) -> None:
    """Creates directories and fetches configs and device information in parallel."""
    print(f"\n{'='*50}")
    print(f"📂 Provisioning Node Files into '{lab_dir}'")
    print(f"{'='*50}")
    
    configs_dir = os.path.join(lab_dir, 'nodes', 'configs')
    sn_dir = os.path.join(lab_dir, 'nodes', 'sn')
    os.makedirs(configs_dir, exist_ok=True)
    os.makedirs(sn_dir, exist_ok=True)
    
    reachable_devices = [d for d in devices if d.name not in unreachable_devices]
    with ThreadPoolExecutor(max_workers=Config.MAX_WORKERS) as executor:
        executor.map(partial(get_device_config, username=username, password=password, configs_dir=configs_dir), reachable_devices)
        executor.map(partial(get_device_info, username=username, password=password, sn_dir=sn_dir), reachable_devices)

def get_lldp_neighbors_napalm(device_name: str, device_ip: str, username: str, password: str) -> Optional[Dict]:
    """Connects to a device using NAPALM and gets LLDP neighbors."""
    if device_name in unreachable_devices: return None
    print(f"   -> Connecting to {device_name} for LLDP...")
    driver = get_network_driver('eos')
    device = driver(hostname=device_ip, username=username, password=password, timeout=10)
    try:
        device.open()
        lldp_neighbors = device.get_lldp_neighbors()
        print(f"   -> ✅ Fetched LLDP data from {device_name}.")
        return lldp_neighbors
    except Exception as e:
        print(f"   -> ❌ Failed to get LLDP from {device_name}: {str(e)[:100]}...")
        unreachable_devices.add(device_name)
        return None
    finally:
        if device.is_alive(): device.close()

def map_interface(node_template: str, interface_name: str) -> str:
    """Maps interface names based on the node template, handling slashes."""
    if 'ceos' in node_template and interface_name.startswith('Ethernet'):
        return interface_name.replace('Ethernet', 'eth').replace('/', '_')
    return interface_name

def generate_topology_file(devices: List, links_data: Dict, site_name: str, lab_dir: str) -> str:
    """Generates the Containerlab YAML topology file from a Jinja2 template."""
    print(f"\n{'='*50}")
    print(f"🔧 Generating Topology File")
    print(f"{'='*50}")
    
    reachable_devices = [device for device in devices if device.name not in unreachable_devices]
    print(f"   -> Including {len(reachable_devices)} reachable devices in topology")
    
    node_template_name = 'ceos-template'
    netbox_device_names = {device.name for device in reachable_devices}
    processed_links: Set = set()
    final_links = []

    for local_device, neighbors_dict in links_data.items():
        if local_device in unreachable_devices: continue
        for local_interface, neighbor_list in neighbors_dict.items():
            for neighbor_info in neighbor_list:
                neighbor_name_from_lldp = neighbor_info['hostname']
                neighbor_interface = neighbor_info['port']
                canonical_neighbor_name = next((name for name in netbox_device_names if neighbor_name_from_lldp.lower().startswith(name.lower()) or name.lower().startswith(neighbor_name_from_lldp.lower())), None)
                if not canonical_neighbor_name or canonical_neighbor_name in unreachable_devices: continue
                mapped_local_int = map_interface(node_template_name, local_interface)
                mapped_neighbor_int = map_interface(node_template_name, neighbor_interface)
                if "eth" not in mapped_local_int or "eth" not in mapped_neighbor_int: continue
                link_tuple = tuple(sorted((f"{local_device}:{mapped_local_int}", f"{canonical_neighbor_name}:{mapped_neighbor_int}")))
                if link_tuple not in processed_links:
                    final_links.append({'endpoints': [f"{local_device}:{mapped_local_int}", f"{canonical_neighbor_name}:{mapped_neighbor_int}"]})
                    processed_links.add(link_tuple)

    env = Environment(loader=FileSystemLoader('.'))
    template = env.get_template('topology.j2')
    topology_yaml = template.render(topology_name=site_name, devices=reachable_devices, node_template=node_template_name, links=final_links)

    topology_filename = f"{site_name.lower()}.clab.yml"
    topology_filepath = os.path.join(lab_dir, topology_filename)

    with open(topology_filepath, 'w') as f:
        f.write(topology_yaml)
    
    print(f"   -> ✅ Successfully generated {topology_filepath}")
    return topology_filepath

def deploy_containerlab(topology_file: str, site_name: str) -> None:
    """Executes the containerlab deploy command and fixes SSH config permissions."""
    print(f"\n{'='*50}")
    print(f"🚀 Deploying Containerlab Environment")
    print(f"{'='*50}")
    
    deploy_command = ["containerlab", "deploy", "-t", topology_file, "--timeout", "4m"]
    print(f"   -> Running command: {' '.join(deploy_command)}")
    print(f"   -> You will now see the live output from Containerlab:")
    print("-" * 50)

    try:
        subprocess.run(deploy_command, check=True)
        print("-" * 50)
        print("   -> ✅ Containerlab deployment completed successfully.")
        
        print("\n   -> 📋 Running lab inspection...")
        inspect_command = ["containerlab", "inspect", "-t", topology_file]
        subprocess.run(inspect_command, check=True)
        
    except FileNotFoundError:
        print("\n" + "-" * 50)
        print("   -> ❌ Error: 'containerlab' command not found. Is it installed and in your PATH?")
        raise
    except subprocess.CalledProcessError:
        print("\n" + "-" * 50)
        print("   -> ❌ Error: Containerlab exited with a non-zero status. See the output above for details.")
        raise
    except Exception as e:
        print(f"\n   -> ❌ An unexpected error occurred: {e}")
        raise

def print_final_summary(devices: List) -> None:
    """Print a final summary of the operation."""
    total_devices = len(devices)
    reachable_devices = total_devices - len(unreachable_devices)
    
    print(f"\n{'='*50}")
    print(f"📋 Final Summary")
    print(f"{'='*50}")
    print(f"   -> Total devices found in NetBox: {total_devices}")
    print(f"   -> Reachable devices: {reachable_devices}")
    print(f"   -> Unreachable devices: {len(unreachable_devices)}")
    
    if unreachable_devices:
        print(f"\n   -> ⚠️ The following devices were unreachable:")
        for device_name in sorted(unreachable_devices):
            print(f"        -> {device_name}")

def main() -> None:
    """Main function to run the script."""
    parser = argparse.ArgumentParser(description="Generate and deploy a Containerlab topology from a NetBox site.")
    parser.add_argument("--site", dest="site_name", help="The name of the site in NetBox.", required=True)
    parser.add_argument("--skip-connectivity-test", action="store_true", help="Skip the initial connectivity test.")
    args = parser.parse_args()

    try:
        username = Config.DEVICE_USERNAME or input("Enter device username: ")
        password = Config.DEVICE_PASSWORD or getpass("Enter device password: ")
        
        lab_dir = args.site_name.lower()
        os.makedirs(lab_dir, exist_ok=True)
        
        print(f"\n{'='*50}")
        print(f"🌐 Connecting to NetBox")
        print(f"{'='*50}")
        
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        session = requests.Session()
        session.verify = False
        nb = pynetbox.api(url=Config.NETBOX_URL, token=Config.NETBOX_TOKEN)
        nb.http_session = session
        
        devices = get_devices_from_site(nb, args.site_name)
        if not devices: return

        if not args.skip_connectivity_test:
            test_device_connectivity_batch(devices, username, password)

        provision_node_files(devices, username, password, lab_dir)

        print(f"\n{'='*50}")
        print(f"📡 Gathering LLDP Information")
        print(f"{'='*50}")
        all_links = {}
        with ThreadPoolExecutor(max_workers=Config.MAX_WORKERS) as executor:
            future_to_device = {
                executor.submit(
                    get_lldp_neighbors_napalm, device.name, device.primary_ip.address.split('/')[0], username, password
                ): device.name
                for device in devices if device.primary_ip and device.name not in unreachable_devices
            }
            for future in as_completed(future_to_device):
                device_name = future_to_device[future]
                try:
                    lldp_data = future.result()
                    if lldp_data: all_links[device_name] = lldp_data
                except Exception as e:
                    print(f"   -> ❌ Error processing LLDP for {device_name}: {str(e)[:100]}...")
                    
        topology_filepath = generate_topology_file(devices, all_links, args.site_name, lab_dir)
        deploy_containerlab(topology_filepath, args.site_name)
        
        print_final_summary(devices)

    except KeyboardInterrupt:
        print("\n   -> ⚠️ Operation cancelled by user")
        return
    except Exception:
        print(f"\n   -> ❌ A critical error occurred. Exiting.")
        if 'devices' in locals():
            print_final_summary(devices)
        raise

if __name__ == "__main__":
    main()