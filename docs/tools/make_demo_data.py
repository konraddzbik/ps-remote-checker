"""Generate fictional demo data for README screenshots / GIFs.

Uses only documentation IP ranges (RFC 5737: 192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24),
private LAN examples and a fake pairing code, so no real network details end up in the docs.

    python3 docs/tools/make_demo_data.py <out_dir>
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ps_remote_checker import cli, verdict  # noqa: E402

CODE = "ABCD-EFGH-JKMN"
NOW = time.time()
ISO = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(NOW - 120))

HOME = {
    "kind": "home", "tool_version": "1.1.2", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(NOW - 3600)),
    "local_ip": "192.168.1.20", "gateway": "192.168.1.1",
    "ps5": {"found": True, "status": "standby", "name": "PS5-123", "host_type": "PS5", "ip": "192.168.1.50",
            "system_version": "09060000", "port_9295_open": False},
    "nat": {"type": "eim", "public_ip": "203.0.113.24", "local_port": 51820, "port_preserved": True,
            "multiple_public_ips": False, "mappings": []},
    "upnp": {"found": True, "device": "Home Router", "external_ip": "203.0.113.24", "cgnat": False, "double_nat": False,
             "mappings": [], "ps5_mappings": [{"protocol": "UDP", "external_port": 9296, "internal_client": "192.168.1.50",
                                               "internal_port": 9296, "description": "PS5 Remote Play", "enabled": True}]},
    "latency": {"server": "stun.cloudflare.com:3478", "sent": 20, "received": 20, "loss_pct": 0.0,
                "avg_ms": 6.2, "min_ms": 5.1, "max_ms": 8.4, "jitter_ms": 0.6},
    "speed": {"down_mbps": 512.4, "up_mbps": 118.7, "error": None},
}

REMOTE = {
    "kind": "remote", "tool_version": "1.1.2", "timestamp": ISO, "local_ip": "172.20.10.4", "gateway": "172.20.10.1",
    "internet": {"internet": True, "captive_portal": False},
    "psn": {"reachable": True, "hosts": {}},
    "nat": {"type": "eim", "public_ip": "198.51.100.77", "local_port": 61002, "port_preserved": False,
            "multiple_public_ips": False, "mappings": []},
    "latency": {"server": "stun.cloudflare.com:3478", "sent": 20, "received": 20, "loss_pct": 0.0,
                "avg_ms": 21.4, "min_ms": 17.9, "max_ms": 29.3, "jitter_ms": 2.1},
    "speed": {"down_mbps": 86.3, "up_mbps": 21.8, "error": None},
    "live": {"ran": True, "relay_ok": True, "helper_found": True, "connected": True, "path": "internet",
             "error": None, "home_public_ip": "203.0.113.24", "punch_ms": 212,
             "rtt": {"sent": 40, "received": 40, "loss_pct": 0.0, "avg_ms": 24.6, "min_ms": 21.0, "max_ms": 31.2, "jitter_ms": 1.8},
             "stream": {"target_mbps": 15.0, "seconds": 6.0, "packets_received": 9361, "packets_sent": 9372,
                        "received_mbps": 15.0, "loss_pct": 0.1, "jitter_ms": 0.9}},
}


def main(out: Path) -> None:
    app, clidir, addon = out / "app", out / "cli", out / "addon" / "data"
    for d in (app, clidir, addon):
        d.mkdir(parents=True, exist_ok=True)

    home_ev = verdict.evaluate_home(HOME)
    remote_ev = verdict.evaluate_remote(REMOTE)
    pair = verdict.evaluate_pair(HOME, REMOTE)

    # macOS app state (PSRC_STATE_DIR)
    (app / "home-report.json").write_text(json.dumps(HOME))
    (app / "home-result.json").write_text(json.dumps({"kind": "home", "report": HOME, "evaluation": home_ev,
                                                       "code": cli.encode_report(HOME)}))
    (app / "remote-result.json").write_text(json.dumps({"kind": "remote", "report": REMOTE, "evaluation": remote_ev,
                                                         "pair": pair, "home_report": HOME, "home_from_helper": True}))
    # CLI compare
    (clidir / "home.json").write_text(json.dumps(HOME, indent=2))
    (clidir / "remote.json").write_text(json.dumps({k: v for k, v in REMOTE.items() if k != "live"}, indent=2))
    (clidir / "remote-live.json").write_text(json.dumps(REMOTE, indent=2))

    # Home Assistant add-on panel state
    sessions = []
    for i, (ago, frm, path, rtt, mbps, loss) in enumerate([
        (180, "198.51.100.77", "internet", 24.6, 15.0, 0.1),
        (3 * 3600, "192.0.2.140", "internet", 41.3, 14.6, 0.8),
        (26 * 3600, "203.0.113.24", "lan", 1.2, 15.0, 0.0),
    ]):
        sessions.append({"sid": f"{i:016x}", "ts": NOW - ago, "from": frm, "status": "done", "connected": True,
                         "path": path, "punch_ms": 212 if path == "internet" else 3, "rtt_ms": rtt, "jitter_ms": 1.8,
                         "stream_mbps": mbps, "target_mbps": 15.0, "loss_pct": loss, "error": None})
    sessions.insert(1, {"sid": "f" * 16, "ts": NOW - 2 * 3600, "from": "192.0.2.201", "status": "done",
                        "connected": False, "path": None, "punch_ms": 12040, "error": None})
    (addon / "state.json").write_text(json.dumps({
        "code": CODE,
        "home": {"at": NOW - 900, "report": HOME, "evaluation": home_ev},
        "sessions": sessions,
    }))
    (addon / "options.json").write_text(json.dumps({"pairing_code": "", "relay": "https://ntfy.sh", "ps5_ip": "",
                                                   "self_check_speed_test": True}))
    print(f"demo data written to {out} · pair verdict: {pair['overall']}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "build/demo"))
