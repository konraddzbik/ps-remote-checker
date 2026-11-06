"""Home Assistant add-on entry point: runs the PS Remote Checker home helper + an Ingress control panel.

Security model
  * The panel is only reachable through Home Assistant Ingress (HA login, works over Tailscale).
    Requests from any address other than the Supervisor's ingress proxy are refused, even though
    the add-on uses the host network (needed to find the PS5 and the router on the LAN).
  * State-changing requests need a custom header, which cross-site forms cannot send (CSRF).
  * After startup the process drops root and runs as the unprivileged `psrc` user.
  * All dynamic data is rendered with textContent in the panel (no HTML injection).
"""
from __future__ import annotations

import argparse
import json
import os
import pwd
import socket
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ps_remote_checker import __version__, cli, pairtest, relay, verdict  # noqa: E402

DATA = Path(os.environ.get("PSRC_DATA_DIR", "/data"))
APP = Path(__file__).resolve().parent
PORT = int(os.environ.get("PSRC_PORT", "8099"))
INGRESS_PROXY = {"172.30.32.2"}
ALLOWED = INGRESS_PROXY | ({"127.0.0.1", "::1"} if os.environ.get("PSRC_ALLOW_LOCAL") else set())


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


class Helper:
    def __init__(self):
        self.options = self._read_json(DATA / "options.json")
        self.state_file = DATA / "state.json"
        self.state = self._read_json(self.state_file)
        self.lock = threading.Lock()
        self.events: deque = deque(maxlen=200)
        self.sessions: dict[str, dict] = {}
        self.home: dict | None = self.state.get("home")
        self.home_running = False
        self.started = time.time()
        self.recheck = threading.Event()
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None
        self.relay_error: str | None = None
        for s in self.state.get("sessions", []):
            self.sessions[s["sid"]] = s

    @staticmethod
    def _read_json(path: Path) -> dict:
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            return {}

    # ---------------------------------------------------------------- config
    @property
    def code_from_options(self) -> str | None:
        code = (self.options.get("pairing_code") or "").strip()
        return code or None

    @property
    def code(self) -> str:
        return self.code_from_options or self.state.get("code") or ""

    @property
    def relay_url(self) -> str:
        return (self.options.get("relay") or relay.DEFAULT_RELAY).strip()

    def save(self) -> None:
        with self.lock:
            self.state["home"] = self.home
            self.state["sessions"] = sorted(self.sessions.values(), key=lambda s: s.get("ts", 0))[-50:]
            data = json.dumps(self.state)
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(data)
        tmp.replace(self.state_file)

    def ensure_code(self) -> None:
        if self.code_from_options:
            relay.normalize_code(self.code_from_options)  # fail loudly on a bad configured code
            return
        if not self.state.get("code"):
            self.state["code"] = relay.new_code()
            self.save()

    # ---------------------------------------------------------------- helper thread
    def start(self) -> None:
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def restart(self) -> None:
        self.stop.set()
        if self.thread:
            self.thread.join(60)
        self.start()

    def _run(self) -> None:
        while not self.stop.is_set():
            try:
                pairtest.run_helper(self.code, self.relay_url, self.on_event, self.home_check, self.recheck, self.stop)
            except Exception as e:  # noqa: BLE001 - never let the helper die silently
                self.on_event({"event": "helper_crashed", "error": str(e)})
                time.sleep(10)

    def home_check(self):
        self.home_running = True
        try:
            args = argparse.Namespace(ps5_ip=(self.options.get("ps5_ip") or "").strip() or None,
                                      no_speed=not self.options.get("self_check_speed_test", True),
                                      speed_seconds=6.0, output=None)
            rep = cli.collect_home(args)
            ev = verdict.evaluate_home(rep)
            self.home = {"at": time.time(), "report": rep, "evaluation": ev}
            self.save()
            return cli.encode_report(rep), ev["overall"]
        finally:
            self.home_running = False

    def on_event(self, evt: dict) -> None:
        evt = {**evt, "ts": time.time()}
        name = evt.get("event")
        with self.lock:
            self.events.append(evt)
            sid = evt.get("sid")
            if name == "session_start" and sid:
                self.sessions[sid] = {"sid": sid, "ts": evt["ts"], "from": evt.get("from"), "status": "running"}
            elif name in ("session_end", "session_result") and sid in self.sessions:
                s = self.sessions[sid]
                s.update({k: v for k, v in evt.items() if k not in ("event", "ts", "sid")})
                s["status"] = "done"
            if name == "relay_error":
                self.relay_error = evt.get("error")
            elif name in ("ready", "session_start"):
                self.relay_error = None
        if name in ("session_end", "session_result"):
            self.save()
        log(" ".join(f"{k}={v}" for k, v in evt.items() if k not in ("ts", "code")))  # never log the code

    # ---------------------------------------------------------------- panel data
    def status(self) -> dict:
        with self.lock:
            home = self.home
            summary = None
            if home:
                r = home["report"]
                upnp = r.get("upnp") or {}
                summary = {
                    "at": home["at"], "overall": home["evaluation"]["overall"],
                    "findings": home["evaluation"]["findings"],
                    "ps5": r.get("ps5"), "nat": r.get("nat"), "latency": r.get("latency"), "speed": r.get("speed"),
                    "upnp": {k: upnp.get(k) for k in ("found", "device", "external_ip", "cgnat", "double_nat", "ps5_mappings")},
                }
            return {
                "version": __version__,
                "code": self.code,
                "code_locked": bool(self.code_from_options),
                "relay": self.relay_url,
                "relay_error": self.relay_error,
                "uptime_s": int(time.time() - self.started),
                "home": summary,
                "home_running": self.home_running or self.recheck.is_set(),
                "sessions": sorted(self.sessions.values(), key=lambda s: s.get("ts", 0), reverse=True)[:20],
                "events": list(self.events)[-40:],
            }

    def new_code(self) -> bool:
        if self.code_from_options:
            return False
        self.state["code"] = relay.new_code()
        self.save()
        threading.Thread(target=self.restart, daemon=True).start()
        return True


HELPER: Helper


class Handler(BaseHTTPRequestHandler):
    server_version = "psrc"
    sys_version = ""

    def log_message(self, fmt, *args):  # quiet access log
        pass

    def _allowed(self) -> bool:
        if self.client_address[0] in ALLOWED:
            return True
        self.send_error(403)
        return False

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                         "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode(), "application/json")

    def do_GET(self):
        if not self._allowed():
            return
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._send(200, (APP / "panel.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/panel.js":
            self._send(200, (APP / "panel.js").read_bytes(), "text/javascript; charset=utf-8")
        elif path == "/api/status":
            self._json(HELPER.status())
        else:
            self.send_error(404)

    def do_POST(self):
        if not self._allowed():
            return
        if self.headers.get("X-PSRC") != "1":
            self.send_error(403, "missing X-PSRC header")
            return
        path = self.path.split("?", 1)[0]
        if path == "/api/selfcheck":
            HELPER.recheck.set()
            self._json({"ok": True})
        elif path == "/api/newcode":
            self._json({"ok": HELPER.new_code()})
        else:
            self.send_error(404)


def drop_privileges(user: str = "psrc") -> None:
    if os.geteuid() != 0:
        return
    try:
        pw = pwd.getpwnam(user)
    except KeyError:
        log(f"user {user} not found, staying root")
        return
    for f in (DATA / "state.json",):
        if f.exists():
            os.chown(f, pw.pw_uid, pw.pw_gid)
    os.chown(DATA, pw.pw_uid, pw.pw_gid)
    os.setgroups([])
    os.setgid(pw.pw_gid)
    os.setuid(pw.pw_uid)
    log(f"running as {user}")


def make_server() -> ThreadingHTTPServer:
    # With host networking, listen only on the Supervisor network if possible; never rely on that alone.
    for host in (os.environ.get("PSRC_BIND"), "172.30.32.1", "0.0.0.0"):
        if not host:
            continue
        try:
            srv = ThreadingHTTPServer((host, PORT), Handler)
            log(f"panel listening on {host}:{PORT} (ingress only)")
            return srv
        except OSError:
            continue
    raise SystemExit(f"cannot bind panel port {PORT}")


def main() -> None:
    global HELPER
    DATA.mkdir(parents=True, exist_ok=True)
    HELPER = Helper()
    HELPER.ensure_code()
    server = make_server()
    drop_privileges()
    log(f"PS Remote Helper {__version__} · pairing code set (see the panel) · relay {HELPER.relay_url}")
    HELPER.start()
    server.serve_forever()


if __name__ == "__main__":
    socket.setdefaulttimeout(None)
    main()
