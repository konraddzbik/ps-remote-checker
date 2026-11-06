"""UPnP IGD probing: is UPnP on, what does the router think its WAN IP is, which ports are mapped.

The PS5 uses UPnP to open its Remote Play ports automatically. The router's WAN IP
(as reported via UPnP) compared with the real public IP (from STUN) reveals
double NAT or carrier-grade NAT, both common causes of Remote Play failures.
"""
from __future__ import annotations

import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from xml.etree import ElementTree

SSDP_ADDR = ("239.255.255.250", 1900)
SEARCH_TARGETS = [
    "urn:schemas-upnp-org:device:InternetGatewayDevice:1",
    "urn:schemas-upnp-org:device:InternetGatewayDevice:2",
    "urn:schemas-upnp-org:service:WANIPConnection:1",
]
WAN_SERVICES = ("WANIPConnection", "WANPPPConnection")


def ssdp_discover(timeout: float = 3.0) -> list[str]:
    """Return LOCATION URLs of responding Internet Gateway Devices."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(0.5)
    locations: list[str] = []
    try:
        for st in SEARCH_TARGETS:
            msg = ("M-SEARCH * HTTP/1.1\r\n"
                   f"HOST: {SSDP_ADDR[0]}:{SSDP_ADDR[1]}\r\n"
                   'MAN: "ssdp:discover"\r\n'
                   "MX: 2\r\n"
                   f"ST: {st}\r\n\r\n").encode()
            sock.sendto(msg, SSDP_ADDR)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data, _ = sock.recvfrom(4096)
            except socket.timeout:
                continue
            m = re.search(rb"(?im)^location:\s*(\S+)", data)
            if m:
                loc = m.group(1).decode(errors="ignore")
                if loc not in locations:
                    locations.append(loc)
    except OSError:
        pass
    finally:
        sock.close()
    return locations


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1]


def find_wan_service(location: str) -> dict | None:
    """Fetch the device description and return the WAN*Connection control URL."""
    try:
        with urllib.request.urlopen(location, timeout=4) as resp:
            xml = resp.read()
        root = ElementTree.fromstring(xml)
    except (urllib.error.URLError, OSError, ElementTree.ParseError, ValueError):
        return None
    base = location
    friendly = None
    for el in root.iter():
        name = _strip_ns(el.tag)
        if name == "URLBase" and el.text:
            base = el.text.strip()
        elif name == "friendlyName" and friendly is None and el.text:
            friendly = el.text.strip()
    for svc in root.iter():
        if _strip_ns(svc.tag) != "service":
            continue
        fields = {_strip_ns(c.tag): (c.text or "").strip() for c in svc}
        stype = fields.get("serviceType", "")
        if any(s in stype for s in WAN_SERVICES) and fields.get("controlURL"):
            return {
                "device": friendly,
                "service_type": stype,
                "control_url": urllib.parse.urljoin(base, fields["controlURL"]),
                "location": location,
            }
    return None


def soap_call(control_url: str, service_type: str, action: str, args: dict | None = None) -> dict | None:
    args_xml = "".join(f"<{k}>{v}</{k}>" for k, v in (args or {}).items())
    body = ('<?xml version="1.0"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
            f'<u:{action} xmlns:u="{service_type}">{args_xml}</u:{action}>'
            "</s:Body></s:Envelope>").encode()
    req = urllib.request.Request(control_url, data=body, method="POST", headers={
        "Content-Type": 'text/xml; charset="utf-8"',
        "SOAPAction": f'"{service_type}#{action}"',
    })
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            xml = resp.read()
        root = ElementTree.fromstring(xml)
    except (urllib.error.URLError, OSError, ElementTree.ParseError, ValueError):
        return None
    out = {}
    for el in root.iter():
        name = _strip_ns(el.tag)
        if name.startswith("New"):
            out[name] = (el.text or "").strip()
    return out


def probe(max_mappings: int = 64) -> dict:
    result = {"found": False, "device": None, "external_ip": None, "mappings": []}
    for loc in ssdp_discover():
        svc = find_wan_service(loc)
        if not svc:
            continue
        result.update(found=True, device=svc["device"], control_url=svc["control_url"])
        ext = soap_call(svc["control_url"], svc["service_type"], "GetExternalIPAddress")
        if ext:
            result["external_ip"] = ext.get("NewExternalIPAddress") or None
        for i in range(max_mappings):
            entry = soap_call(svc["control_url"], svc["service_type"],
                              "GetGenericPortMappingEntry", {"NewPortMappingIndex": i})
            if not entry or "NewExternalPort" not in entry:
                break
            result["mappings"].append({
                "protocol": entry.get("NewProtocol"),
                "external_port": int(entry.get("NewExternalPort") or 0),
                "internal_client": entry.get("NewInternalClient"),
                "internal_port": int(entry.get("NewInternalPort") or 0),
                "description": entry.get("NewPortMappingDescription"),
                "enabled": entry.get("NewEnabled") in ("1", "true"),
            })
        break
    return result
