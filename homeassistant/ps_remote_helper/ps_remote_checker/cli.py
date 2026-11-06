"""Command line entry point.

  ps-remote-check home    # run on the PS5's home network
  ps-remote-check remote  # run on the network the PS Portal will use away from home
  ps-remote-check compare home.json remote.json
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import zlib
from datetime import datetime, timezone

from . import __version__, discovery, netinfo, pairtest, relay, speed, stun, upnp, verdict

COLORS = {"ok": "\033[32m", "warn": "\033[33m", "fail": "\033[31m", "dim": "\033[2m",
          "bold": "\033[1m", "reset": "\033[0m"}
ICONS = {"ok": "✔", "warn": "!", "fail": "✘"}
HEADLINE = {
    "ok": "Remote Play should work",
    "warn": "Remote Play may work, with issues (see below)",
    "fail": "Remote Play is unlikely to work",
}


def _c(key: str, text: str) -> str:
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return text
    return f"{COLORS[key]}{text}{COLORS['reset']}"


JSON_MODE = False


def step(msg: str) -> None:
    if JSON_MODE:  # machine-readable progress for the macOS app, on stderr
        print(f"STEP\t{msg}", file=sys.stderr, flush=True)
    else:
        print(_c("dim", f"  … {msg}"), flush=True)


def emit_json(payload: dict) -> None:
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")
    sys.stdout.flush()


# ----------------------------------------------------------------------------- collection

def _base_report(kind: str) -> dict:
    return {"kind": kind, "tool_version": __version__,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "local_ip": netinfo.local_ip(), "gateway": netinfo.default_gateway()}


def collect_home(args) -> dict:
    rep = _base_report("home")
    step("looking for a PS5 on the local network (UDP 9302)")
    consoles = [c for c in discovery.discover(rep["local_ip"], args.ps5_ip) if c.get("host_type", "PS5") == "PS5"]
    ps5 = {"found": False}
    if consoles:
        ps5 = {"found": True, **consoles[0]}
        if len(consoles) > 1:
            ps5["others"] = [c["ip"] for c in consoles[1:]]
        ps5["port_9295_open"] = netinfo.tcp_port_open(ps5["ip"], discovery.REMOTE_PLAY_TCP_PORT)
    elif args.ps5_ip:
        ps5["ip"] = args.ps5_ip
    rep["ps5"] = ps5

    step("detecting NAT type with STUN")
    rep["nat"] = stun.detect_nat(rep["local_ip"])
    step("checking router UPnP / port mappings")
    up = upnp.probe()
    ext_kind = netinfo.classify_ip(up.get("external_ip"))
    up["cgnat"] = ext_kind == "cgnat"
    up["double_nat"] = ext_kind == "private"
    ps5_ip = ps5.get("ip")
    up["ps5_mappings"] = [m for m in up["mappings"] if ps5_ip and m.get("internal_client") == ps5_ip]
    rep["upnp"] = up
    step("measuring UDP latency / jitter")
    rep["latency"] = stun.measure_latency()
    rep["speed"] = None
    if not args.no_speed:
        step("measuring speed (download + upload, ~15 s)")
        rep["speed"] = speed.run(args.speed_seconds)
    return rep


def collect_remote(args) -> tuple[dict, str | None]:
    """Returns (report, home code delivered by the home helper or None)."""
    rep = _base_report("remote")
    step("checking internet / captive portal")
    rep["internet"] = netinfo.captive_portal_check()
    step("checking PlayStation Network reachability")
    rep["psn"] = netinfo.psn_reachability()
    step("detecting NAT type with STUN")
    rep["nat"] = stun.detect_nat(rep["local_ip"])
    step("measuring UDP latency / jitter")
    rep["latency"] = stun.measure_latency()
    rep["speed"] = None
    if not args.no_speed:
        step("measuring speed (download + upload, ~15 s)")
        rep["speed"] = speed.run(args.speed_seconds)
    helper_home = None
    if getattr(args, "pair", None):
        step("live test: looking for the home helper")
        rep["live"], helper_home = pairtest.run_client(args.pair, args.relay, args.live_mbps, args.live_seconds, step)
    return rep, helper_home


# ----------------------------------------------------------------------------- share code

def encode_report(rep: dict) -> str:
    slim = {k: v for k, v in rep.items() if k != "upnp"}
    if rep.get("upnp"):  # mapping list can be long; keep only what the verdict needs
        slim["upnp"] = {k: rep["upnp"].get(k) for k in ("found", "device", "external_ip", "cgnat", "double_nat", "ps5_mappings")}
    raw = json.dumps(slim, separators=(",", ":")).encode()
    return "PSRC1." + base64.urlsafe_b64encode(zlib.compress(raw, 9)).decode().rstrip("=")


def decode_report(code: str) -> dict:
    code = code.strip()
    if not code.startswith("PSRC1."):
        raise ValueError("not a ps-remote-check code (should start with PSRC1.)")
    body = code[6:]
    body += "=" * (-len(body) % 4)
    try:
        return json.loads(zlib.decompress(base64.urlsafe_b64decode(body)))
    except (zlib.error, ValueError) as e:
        raise ValueError(f"home code is damaged or incomplete ({e})") from None


def load_report(value: str) -> dict:
    if value.strip().startswith("PSRC1."):
        return decode_report(value)
    with open(value, encoding="utf-8") as fh:
        return json.load(fh)


# ----------------------------------------------------------------------------- output

def print_findings(title: str, ev: dict) -> None:
    print()
    print(_c("bold", title) + "  " + _c(ev["overall"], f"[{ev['overall'].upper()}]"))
    for f in ev["findings"]:
        icon = _c(f["level"], ICONS[f["level"]])
        print(f"  {icon} {f['area']:<10} {f['message']}")
        if f.get("fix") and f["level"] != "ok":
            print(_c("dim", f"    {'':<10} → {f['fix']}"))


def print_headline(level: str, text: str | None = None) -> None:
    line = f" {ICONS[level]} {text or HEADLINE[level]} "
    print()
    print(_c("bold", _c(level, "=" * len(line))))
    print(_c("bold", _c(level, line)))
    print(_c("bold", _c(level, "=" * len(line))))


def save(rep: dict, path: str | None) -> None:
    if not path:
        return
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=2)
    if not JSON_MODE:
        print(_c("dim", f"\nSaved report to {path}"))


# ----------------------------------------------------------------------------- commands

def cmd_home(args) -> int:
    if not JSON_MODE:
        print(_c("bold", "PS Remote Play checker: HOME network (PS5 side)"))
    rep = collect_home(args)
    ev = verdict.evaluate_home(rep)
    if JSON_MODE:
        save(rep, args.output)
        emit_json({"kind": "home", "report": rep, "evaluation": ev, "code": encode_report(rep)})
        return 0
    print_findings("Home network", ev)
    save(rep, args.output)
    print("\nNext: take the PS Portal's network (or run this on a laptop/phone hotspot away from home) and run:")
    print(_c("bold", f"  ps-remote-check remote --home {args.output or '<home code below>'}"))
    if not args.output:
        print("\nHome code (paste it after --home):")
        print(encode_report(rep))
    return 0 if ev["overall"] != "fail" else 1


def cmd_remote(args) -> int:
    if not JSON_MODE:
        print(_c("bold", "PS Remote Play checker: REMOTE network (PS Portal side)"))
    if args.pair:
        relay.normalize_code(args.pair)  # fail fast on a mistyped code
    home = load_report(args.home) if args.home else None
    rep, helper_home = collect_remote(args)
    used_helper_home = False
    if helper_home:  # the helper's self-check is fresher and made on the real home network
        try:
            home = decode_report(helper_home)
            used_helper_home = True
        except ValueError:
            pass
    save(rep, args.output)
    if JSON_MODE:
        emit_json({"kind": "remote", "report": rep, "evaluation": verdict.evaluate_remote(rep),
                   "pair": verdict.evaluate_pair(home, rep) if home else None,
                   "home_report": home, "home_from_helper": used_helper_home})
        return 0
    if home:
        return _print_pair(home, rep)
    ev = verdict.evaluate_remote(rep)
    print_findings("Remote network", ev)
    print("\nTip: pass --home <home.json or code> to get the combined verdict.")
    return 0 if ev["overall"] != "fail" else 1


def cmd_helper(args) -> int:
    code = args.code or relay.new_code()
    relay.normalize_code(code)

    def log(evt: dict) -> None:
        if JSON_MODE:
            emit_json({"kind": "helper", **evt})
            return
        e = evt.get("event")
        stamp = datetime.now().strftime("%H:%M:%S")
        if e == "ready":
            print(_c("bold", "PS Remote Play checker: HOME HELPER"))
            print("Keep this running at home (same router as the PS5). On the away network run:")
            print(_c("bold", f"  ps-remote-check remote --pair {evt['code']}"))
            print(_c("dim", f"Relay: {evt['relay']}  ·  Ctrl+C to stop\n"))
        elif e == "home_check_done":
            print(f"[{stamp}] home self-check finished: {evt['overall'].upper()}")
        elif e == "session_start":
            print(f"[{stamp}] live test requested from {evt.get('from')}")
        elif e == "session_connected":
            print(f"[{stamp}]   connected to {evt.get('peer')}")
        elif e == "session_end":
            ok = evt.get("connected")
            print(f"[{stamp}]   finished: " + (_c("ok", "connected") if ok else _c("fail", "no direct connection"))
                  + (f" ({evt['error']})" if evt.get("error") else ""))
        elif e in ("relay_error", "home_check_failed"):
            print(_c("warn", f"[{stamp}] {e.replace('_', ' ')}: {evt.get('error')}"))

    def home_check():
        rep = collect_home(args)
        return encode_report(rep), verdict.evaluate_home(rep)["overall"]

    pairtest.run_helper(code, args.relay, log, None if args.no_home_check else home_check)
    return 0


def cmd_compare(args) -> int:
    home, remote = load_report(args.home), load_report(args.remote)
    if home.get("kind") != "home" or remote.get("kind") != "remote":
        print("error: expected a 'home' report first and a 'remote' report second", file=sys.stderr)
        return 2
    if JSON_MODE:
        emit_json({"kind": "pair", "pair": verdict.evaluate_pair(home, remote)})
        return 0
    return _print_pair(home, remote)


def _print_pair(home: dict, remote: dict) -> int:
    ev = verdict.evaluate_pair(home, remote)
    print_findings("Home network (PS5)", ev["home"])
    print_findings("Remote network (PS Portal)", ev["remote"])
    print_findings("PS5 ⇄ PS Portal connection", {"overall": ev["overall"], "findings": ev["findings"]})
    print_headline(ev["overall"])
    return 0 if ev["overall"] != "fail" else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ps-remote-check",
                                description="Check whether PS5 Remote Play / PS Portal can connect from outside the home network.")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--json", action="store_true", help="machine-readable output (progress on stderr)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def speed_opts(sp):
        sp.add_argument("--no-speed", action="store_true", help="skip the bandwidth test")
        sp.add_argument("--speed-seconds", type=float, default=6.0, help="seconds per direction (default 6)")
        sp.add_argument("-o", "--output", help="save the JSON report to this file")

    h = sub.add_parser("home", help="run on the PS5's home network")
    h.add_argument("--ps5-ip", help="PS5 IP address if broadcast discovery fails")
    speed_opts(h)
    h.set_defaults(func=cmd_home)

    r = sub.add_parser("remote", help="run on the network the PS Portal will use")
    r.add_argument("--home", help="home report (.json file or PSRC1 code) for the combined verdict")
    r.add_argument("--pair", metavar="CODE", help="pairing code of a running home helper: runs the live connection test")
    r.add_argument("--relay", help=f"signalling relay (ntfy server, default {relay.DEFAULT_RELAY})")
    r.add_argument("--live-mbps", type=float, default=15.0, help="stream rate for the live test (default 15)")
    r.add_argument("--live-seconds", type=float, default=6.0, help="stream duration for the live test (default 6)")
    speed_opts(r)
    r.set_defaults(func=cmd_remote)

    hp = sub.add_parser("helper", help="run at home (always-on device): answers live tests from the away network")
    hp.add_argument("--code", help="pairing code to use (default: generate a new one)")
    hp.add_argument("--relay", help=f"signalling relay (ntfy server, default {relay.DEFAULT_RELAY})")
    hp.add_argument("--ps5-ip", help="PS5 IP address for the home self-check")
    hp.add_argument("--no-home-check", action="store_true", help="don't run the hourly home self-check")
    speed_opts(hp)
    hp.set_defaults(func=cmd_helper)

    c = sub.add_parser("compare", help="combine a saved home and remote report")
    c.add_argument("home", help="home report (.json or code)")
    c.add_argument("remote", help="remote report (.json or code)")
    c.set_defaults(func=cmd_compare)
    return p


def main(argv=None) -> int:
    global JSON_MODE
    args = build_parser().parse_args(argv)
    JSON_MODE = args.json
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError) as e:  # bad report file / code
        if JSON_MODE:
            emit_json({"kind": "error", "error": str(e)})
        else:
            print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
