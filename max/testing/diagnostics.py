import socket
import subprocess
import platform
import logging
import configparser
import time
from typing import Dict, Any, List, Tuple


def check_network_interfaces() -> List[Dict[str, Any]]:
    """Get information about network interfaces"""
    interfaces = []

    try:
        # Get all interfaces with their IP addresses
        hostname = socket.gethostname()
        ip_addresses = socket.getaddrinfo(hostname, None)

        # Filter to just get IPv4 addresses
        for ip in ip_addresses:
            if ip[0] == socket.AF_INET:  # IPv4
                interfaces.append({"address": ip[4][0], "family": "IPv4"})
    except Exception as e:
        logging.error(f"Error checking network interfaces: {e}")

    return interfaces


def ping_host(host: str, count: int = 4) -> Tuple[bool, str]:
    """Ping a host and return success status and output"""
    param = "-n" if platform.system().lower() == "windows" else "-c"
    command = ["ping", param, str(count), host]

    try:
        output = subprocess.check_output(command, universal_newlines=True)
        return True, output
    except subprocess.CalledProcessError as e:
        return False, e.output
    except Exception as e:
        return False, str(e)


def check_port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    """Check if a TCP port is open on a host"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)

    try:
        result = sock.connect_ex((host, port))
        return result == 0  # 0 means port is open
    except Exception as e:
        logging.error(f"Error checking port {port} on {host}: {e}")
        return False
    finally:
        sock.close()


def run_network_diagnostics(config_path: str = "config.ini") -> Dict[str, Any]:
    """Run comprehensive network diagnostics and return results"""
    results = {
        "local_interfaces": [],
        "remote_ping": {"success": False, "output": ""},
        "remote_port_check": False,
        "config": {},
        "timestamp": time.time(),
    }

    # Get local network interfaces
    results["local_interfaces"] = check_network_interfaces()

    # Load configuration
    config = configparser.ConfigParser()
    config.read(config_path)

    try:
        remote_ip = config["REMOTE"]["ip"]
        remote_port = int(config["REMOTE"]["port"])
        local_port = int(config["LOCAL"]["port"])

        results["config"] = {
            "remote_ip": remote_ip,
            "remote_port": remote_port,
            "local_port": local_port,
        }

        # Check if we can ping the remote host
        ping_success, ping_output = ping_host(remote_ip)
        results["remote_ping"] = {"success": ping_success, "output": ping_output}

        # Check if the remote port is open
        port_open = check_port_open(remote_ip, remote_port)
        results["remote_port_check"] = port_open

    except Exception as e:
        logging.error(f"Error in network diagnostics: {e}")
        results["error"] = str(e)

    return results


def print_diagnostic_results(results: Dict[str, Any]) -> None:
    """Print diagnostic results in a readable format"""
    print("\n===== NETWORK DIAGNOSTICS =====")

    # Print local interfaces
    print("\nLocal Network Interfaces:")
    for interface in results["local_interfaces"]:
        print(f"  {interface['family']}: {interface['address']}")

    # Print configuration
    if "config" in results:
        config = results["config"]
        print("\nConfiguration:")
        print(f"  Local Port: {config.get('local_port', 'Not found')}")
        print(f"  Remote IP: {config.get('remote_ip', 'Not found')}")
        print(f"  Remote Port: {config.get('remote_port', 'Not found')}")

    # Print ping results
    ping = results["remote_ping"]
    print("\nPing to Remote Host:")
    print(f"  Success: {ping['success']}")
    if not ping["success"]:
        print(f"  Output: {ping['output']}")

    # Print port check
    print("\nRemote Port Check:")
    print(f"  Port Open: {results['remote_port_check']}")

    # Print recommendations
    print("\nRecommendations:")
    if not ping["success"]:
        print("  - Check network connectivity between devices")
        print("  - Verify the remote IP address is correct")
        print("  - Ensure both devices are on the same network")

    if not results["remote_port_check"]:
        print("  - Check if the remote device is running the application")
        print("  - Verify the port configuration is correct")
        print("  - Check for firewalls blocking the connection")

    if ping["success"] and results["remote_port_check"]:
        print("  - Network connectivity looks good!")

    print("\n===============================\n")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = run_network_diagnostics()
    print_diagnostic_results(results)
