"""Basic network facts: local IP, gateway, address classification, internet/PSN reachability."""
from __future__ import annotations

import ipaddress
import platform
import re
import socket
import subprocess
import urllib.error
import urllib.request

USER_AGENT = "ps-remote-checker/1.0"

CGNAT_NET = ipaddress.ip_network("100.64.0.0/10")

# Hosts a PS5 / PS Portal must reach to sign in and broker a Remote Play session.
PSN_HOSTS = [
    "https://ca.account.sony.com/",
    "https://web.np.playstation.com/",
    "https://www.playstation.com/",
]


def local_ip() -> str | None:
    """IP of the interface used for the default route (no packets are actually sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("1.1.1.1", 80))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def default_gateway() -> str | None:
    system = platform.system()
    try:
        if system == "Darwin":
            out = subprocess.run(["route", "-n", "get", "default"], capture_output=True,
                                 text=True, timeout=3).stdout
            m = re.search(r"gateway:\s*(\S+)", out)
        elif system == "Linux":
            out = subprocess.run(["ip", "route", "show", "default"], capture_output=True,
                                 text=True, timeout=3).stdout
            m = re.search(r"default via (\S+)", out)
        elif system == "Windows":
            out = subprocess.run(["ipconfig"], capture_output=True, text=True, timeout=5).stdout
            m = re.search(r"Default Gateway[ .]*:\s*(\d+\.\d+\.\d+\.\d+)", out)
        else:
            return None
        return m.group(1) if m else None
    except (OSError, subprocess.SubprocessError):
        return None


def classify_ip(ip: str | None) -> str:
    """'public', 'private', 'cgnat', or 'unknown'."""
    if not ip:
        return "unknown"
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return "unknown"
    if addr.version == 4 and addr in CGNAT_NET:
        return "cgnat"
    if addr.is_private or addr.is_loopback or addr.is_link_local:
        return "private"
    return "public"


def _http_status(url: str, timeout: float = 5.0) -> tuple[int | None, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(512)
    except urllib.error.HTTPError as e:  # server answered -> reachable
        return e.code, b""
    except (urllib.error.URLError, OSError, ValueError):
        return None, b""


def captive_portal_check() -> dict:
    """Detect hotel/airport style captive portals that silently hijack HTTP."""
    status, body = _http_status("http://connectivitycheck.gstatic.com/generate_204")
    if status == 204:
        return {"internet": True, "captive_portal": False}
    status2, body2 = _http_status("http://captive.apple.com/hotspot-detect.html")
    if status2 == 200 and b"Success" in body2:
        return {"internet": True, "captive_portal": False}
    if status is None and status2 is None:
        return {"internet": False, "captive_portal": False}
    return {"internet": True, "captive_portal": True}


def psn_reachability() -> dict:
    hosts = {}
    for url in PSN_HOSTS:
        status, _ = _http_status(url)
        hosts[url] = status
    return {"reachable": any(v is not None for v in hosts.values()), "hosts": hosts}


def tcp_port_open(ip: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False
