"""Find a PS5 on the LAN using Sony's Remote Play device discovery protocol (UDP 9302).

The console answers a `SRCH` datagram with an HTTP-like status:
  HTTP/1.1 200 Ok              -> console is on
  HTTP/1.1 620 Server Standby  -> console is in rest mode (Remote Play can wake it)
"""
from __future__ import annotations

import ipaddress
import socket
import time

PS5_PORT = 9302
PS5_PROTOCOL_VERSION = "00030010"
REMOTE_PLAY_TCP_PORT = 9295


def build_search() -> bytes:
    return f"SRCH * HTTP/1.1\ndevice-discovery-protocol-version:{PS5_PROTOCOL_VERSION}\n".encode()


def parse_reply(data: bytes) -> dict | None:
    text = data.decode(errors="ignore")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines or not lines[0].startswith("HTTP/1.1"):
        return None
    parts = lines[0].split(" ", 2)
    code = parts[1] if len(parts) > 1 else ""
    fields = {}
    for ln in lines[1:]:
        if ":" in ln:
            k, v = ln.split(":", 1)
            fields[k.strip().lower()] = v.strip()
    status = {"200": "on", "620": "standby"}.get(code, f"code {code}")
    return {
        "status": status,
        "name": fields.get("host-name"),
        "host_type": fields.get("host-type"),
        "host_id": fields.get("host-id"),
        "system_version": fields.get("system-version"),
        "request_port": fields.get("host-request-port"),
    }


def _targets(local_ip: str | None, explicit_ip: str | None) -> list[str]:
    if explicit_ip:
        return [explicit_ip]
    targets = ["255.255.255.255"]
    if local_ip:
        try:
            net = ipaddress.ip_network(f"{local_ip}/24", strict=False)
            targets.append(str(net.broadcast_address))
        except ValueError:
            pass
    return targets


def discover(local_ip: str | None, explicit_ip: str | None = None, timeout: float = 3.0) -> list[dict]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(0.3)
    found: dict[str, dict] = {}
    try:
        sock.bind(("0.0.0.0", 0))
        deadline = time.time() + timeout
        next_send = 0.0
        while time.time() < deadline:
            if time.time() >= next_send:
                for t in _targets(local_ip, explicit_ip):
                    try:
                        sock.sendto(build_search(), (t, PS5_PORT))
                    except OSError:
                        pass
                next_send = time.time() + 1.0
            try:
                data, (ip, _) = sock.recvfrom(2048)
            except socket.timeout:
                continue
            info = parse_reply(data)
            if info and ip not in found:
                info["ip"] = ip
                found[ip] = info
    except OSError:
        pass
    finally:
        sock.close()
    return list(found.values())
