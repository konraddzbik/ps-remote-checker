"""Minimal STUN (RFC 5389) client used to detect NAT mapping behaviour and UDP latency.

PS Remote Play over the internet is brokered by PSN and relies on UDP hole punching,
which is exactly what STUN measures: whether the router keeps the same public
ip:port for one local socket regardless of destination (endpoint-independent
mapping, "cone" NAT) or allocates a new one per destination ("symmetric" NAT).
"""
from __future__ import annotations

import os
import socket
import statistics
import struct
import time

MAGIC_COOKIE = 0x2112A442
BINDING_REQUEST = 0x0001
BINDING_SUCCESS = 0x0101
ATTR_MAPPED_ADDRESS = 0x0001
ATTR_XOR_MAPPED_ADDRESS = 0x0020
ATTR_XOR_MAPPED_ADDRESS_OLD = 0x8020

# Servers on distinct operators so they resolve to distinct IPs.
DEFAULT_SERVERS = [
    ("stun.l.google.com", 19302),
    ("stun.cloudflare.com", 3478),
    ("global.stun.twilio.com", 3478),
    ("stun.nextcloud.com", 3478),
    ("stun1.l.google.com", 19302),
]


def build_request(txid: bytes) -> bytes:
    return struct.pack("!HHI", BINDING_REQUEST, 0, MAGIC_COOKIE) + txid


def parse_response(data: bytes, txid: bytes) -> tuple[str, int] | None:
    """Return (ip, port) from a STUN Binding Success response, or None."""
    if len(data) < 20:
        return None
    msg_type, msg_len, cookie = struct.unpack("!HHI", data[:8])
    if msg_type != BINDING_SUCCESS or cookie != MAGIC_COOKIE or data[8:20] != txid:
        return None
    pos, end = 20, min(len(data), 20 + msg_len)
    fallback = None
    while pos + 4 <= end:
        attr_type, attr_len = struct.unpack("!HH", data[pos:pos + 4])
        value = data[pos + 4:pos + 4 + attr_len]
        pos += 4 + attr_len + ((4 - attr_len % 4) % 4)
        if len(value) < 8 or value[1] != 0x01:  # IPv4 only
            continue
        port = struct.unpack("!H", value[2:4])[0]
        raw_ip = value[4:8]
        if attr_type in (ATTR_XOR_MAPPED_ADDRESS, ATTR_XOR_MAPPED_ADDRESS_OLD):
            port ^= MAGIC_COOKIE >> 16
            ip_int = struct.unpack("!I", raw_ip)[0] ^ MAGIC_COOKIE
            return socket.inet_ntoa(struct.pack("!I", ip_int)), port
        if attr_type == ATTR_MAPPED_ADDRESS:
            fallback = (socket.inet_ntoa(raw_ip), port)
    return fallback


def binding(sock: socket.socket, addr: tuple[str, int], timeout: float = 1.0,
            retries: int = 3) -> tuple[str, int, float] | None:
    """Send a Binding Request from `sock` to `addr`. Return (ip, port, rtt_ms) or None."""
    for _ in range(retries):
        txid = os.urandom(12)
        sock.settimeout(timeout)
        start = time.perf_counter()
        try:
            sock.sendto(build_request(txid), addr)
            deadline = start + timeout
            while True:
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    break
                sock.settimeout(remaining)
                data, src = sock.recvfrom(2048)
                result = parse_response(data, txid)
                if result:
                    return result[0], result[1], (time.perf_counter() - start) * 1000
        except (socket.timeout, OSError):
            continue
    return None


def resolve_servers(servers=DEFAULT_SERVERS) -> list[tuple[str, str, int]]:
    """Resolve to (hostname, ipv4, port), de-duplicated by IP."""
    out, seen = [], set()
    for host, port in servers:
        try:
            ip = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_DGRAM)[0][4][0]
        except OSError:
            continue
        if ip not in seen:
            seen.add(ip)
            out.append((host, ip, port))
    return out


def detect_nat(local_ip: str | None, servers=DEFAULT_SERVERS) -> dict:
    """Classify NAT mapping behaviour using one UDP socket against several servers."""
    resolved = resolve_servers(servers)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 0))
    local_port = sock.getsockname()[1]
    mappings = []
    try:
        for host, ip, port in resolved:
            res = binding(sock, (ip, port))
            if res:
                mappings.append({"server": f"{host}:{port}", "ip": res[0], "port": res[1]})
            if len(mappings) >= 3:
                break
    finally:
        sock.close()

    result = {
        "type": "udp_blocked",
        "public_ip": None,
        "local_port": local_port,
        "mappings": mappings,
        "port_preserved": None,
        "multiple_public_ips": False,
        "servers_tried": len(resolved),
    }
    if not resolved:
        result["type"] = "dns_failed"
        return result
    if not mappings:
        return result

    endpoints = {(m["ip"], m["port"]) for m in mappings}
    ips = {m["ip"] for m in mappings}
    result["public_ip"] = mappings[0]["ip"]
    result["multiple_public_ips"] = len(ips) > 1
    result["port_preserved"] = all(m["port"] == local_port for m in mappings)
    if local_ip and mappings[0]["ip"] == local_ip:
        result["type"] = "open"
    elif len(mappings) < 2:
        result["type"] = "unknown"  # only one server answered, can't compare
    elif len(endpoints) == 1:
        result["type"] = "eim"
    else:
        result["type"] = "symmetric"
    return result


def measure_latency(samples: int = 20, interval: float = 0.05,
                    server=("stun.cloudflare.com", 3478)) -> dict:
    """UDP round-trip latency / jitter / loss using STUN pings (mimics the stream's transport)."""
    resolved = resolve_servers([server]) or resolve_servers()
    if not resolved:
        return {"server": None, "sent": 0, "received": 0, "loss_pct": 100.0}
    host, ip, port = resolved[0]
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rtts = []
    try:
        for _ in range(samples):
            res = binding(sock, (ip, port), timeout=1.0, retries=1)
            if res:
                rtts.append(res[2])
            time.sleep(interval)
    finally:
        sock.close()
    out = {
        "server": f"{host}:{port}",
        "sent": samples,
        "received": len(rtts),
        "loss_pct": round(100.0 * (samples - len(rtts)) / samples, 1),
    }
    if rtts:
        diffs = [abs(a - b) for a, b in zip(rtts, rtts[1:])]
        out.update({
            "avg_ms": round(statistics.mean(rtts), 1),
            "min_ms": round(min(rtts), 1),
            "max_ms": round(max(rtts), 1),
            "jitter_ms": round(statistics.mean(diffs), 1) if diffs else 0.0,
        })
    return out
