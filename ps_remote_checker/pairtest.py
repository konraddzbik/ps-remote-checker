"""Live connection test between a home helper and the away network.

The helper runs on any always-on device behind the same home router as the PS5, so
its traffic gets the same NAT treatment as the console's. The away check then does
what PSN does for the PS5 and the PS Portal:

  1. both sides learn their public UDP endpoint via STUN and swap it through the relay;
  2. both fire UDP packets at each other (hole punching) until one gets through;
  3. over the opened path: round-trip pings, then the helper streams paced UDP at
     ~15 Mbps (like the PS5's video) and the away side measures what arrives.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import socket
import statistics
import struct
import threading
import time

from . import relay, stun
from .netinfo import local_ip

HDR = struct.Struct("!2sc8sId")  # magic, type, session id, seq, sender timestamp
MAGIC = b"PS"
MAC_LEN = 8
DATA_SIZE = 1200                  # bytes per stream packet (typical game-stream payload)
PUNCH_SECONDS = 12.0
ANSWER_TIMEOUT = 30.0
JOIN_MAX_AGE = 90.0
MAX_STREAM_KBPS = 30_000          # helper refuses to stream faster than this...
MAX_STREAM_MS = 15_000            # ...or longer than this
COOKIE_LEN = 8
MIN_SESSION_GAP = 20.0            # helper rate limit: at most one test every 20 s...
MAX_SESSIONS_PER_HOUR = 12        # ...and 12 per hour, so a leaked code can't keep it streaming

# packet types
PUNCH, ACK, PING, PONG, STREAM, DATA, END, BYE = (b"P", b"A", b"I", b"O", b"S", b"D", b"E", b"B")


class Packets:
    def __init__(self, code: str, sid: bytes):
        norm = relay.normalize_code(code).encode()
        self.key = hashlib.sha256(b"psrc-udp:" + norm).digest()
        self.sid = sid

    def make(self, typ: bytes, seq: int = 0, payload: bytes = b"", ts: float | None = None) -> bytes:
        body = HDR.pack(MAGIC, typ, self.sid, seq & 0xFFFFFFFF, time.time() if ts is None else ts) + payload
        if typ == DATA:  # bulk packets are padded, not signed (session id is still checked)
            return body + b"\0" * max(0, DATA_SIZE - len(body))
        return body + hmac.new(self.key, body, hashlib.sha256).digest()[:MAC_LEN]

    def parse(self, data: bytes):
        if len(data) < HDR.size or data[:2] != MAGIC:
            return None
        magic, typ, sid, seq, ts = HDR.unpack_from(data)
        if sid != self.sid:
            return None
        if typ == DATA:
            return typ, seq, ts, b""
        body, mac = data[:-MAC_LEN], data[-MAC_LEN:]
        if len(data) < HDR.size + MAC_LEN or not hmac.compare_digest(
                mac, hmac.new(self.key, body, hashlib.sha256).digest()[:MAC_LEN]):
            return None
        return typ, seq, ts, body[HDR.size:]


def _udp_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
    except OSError:
        pass
    sock.bind(("0.0.0.0", 0))
    return sock


def _public_endpoint(sock: socket.socket) -> tuple[str, int] | None:
    for host, ip, port in stun.resolve_servers()[:4]:
        res = stun.binding(sock, (ip, port), timeout=1.0, retries=2)
        if res:
            return res[0], res[1]
    return None


def _candidates(me_public: str, peer: dict) -> list[tuple[str, int]]:
    cands = [tuple(peer["cand"])]
    # Same public IP means both ends are behind the same router: also try the LAN address
    # (many routers don't support NAT hairpinning).
    if peer.get("local") and peer["cand"][0] == me_public and not os.environ.get("PSRC_NO_LAN"):
        cands.append(tuple(peer["local"]))
    return [(str(ip), int(port)) for ip, port in cands]


def _punch(sock, pk: Packets, cands, deadline, cookie_for=None) -> tuple[tuple[str, int] | None, float]:
    """Send punches to all candidates until any valid packet arrives. Returns (peer_addr, ms).

    `cookie_for(addr)` (helper side) attaches a per-address cookie to PUNCH/ACK packets."""
    start = time.perf_counter()
    next_send = 0.0
    while time.perf_counter() < deadline:
        now = time.perf_counter()
        if now >= next_send:
            for c in cands:
                try:
                    sock.sendto(pk.make(PUNCH, payload=cookie_for(c) if cookie_for else b""), c)
                except OSError:
                    pass
            next_send = now + 0.1
        sock.settimeout(0.05)
        try:
            data, addr = sock.recvfrom(4096)
        except (socket.timeout, OSError):
            continue
        p = pk.parse(data)
        if not p:
            continue
        if p[0] == PUNCH:
            sock.sendto(pk.make(ACK, payload=cookie_for(addr) if cookie_for else b""), addr)
        return addr, (time.perf_counter() - start) * 1000
    return None, (time.perf_counter() - start) * 1000


# ============================================================================ helper (home)

def _stream(sock, pk: Packets, addr, rate_kbps: int, dur_ms: int, stop: threading.Event):
    pps = max(1, int(rate_kbps * 1000 / 8 / DATA_SIZE))
    total = int(pps * dur_ms / 1000)
    start = time.perf_counter()
    sent = 0
    while sent < total and not stop.is_set():
        due = min(total, int((time.perf_counter() - start) * pps) + 1)
        while sent < due:
            try:
                sock.sendto(pk.make(DATA, sent), addr)
            except OSError:
                pass
            sent += 1
        time.sleep(0.001)
    for _ in range(5):
        try:
            sock.sendto(pk.make(END, sent, struct.pack("!I", sent)), addr)
        except OSError:
            return
        time.sleep(0.05)


def _serve_session(ch: relay.Channel, code: str, join: dict, home_code: str | None, log) -> dict:
    sid = bytes.fromhex(join["sid"])
    pk = Packets(code, sid)
    sock = _udp_socket()
    # Return-routability cookies: the stream is only sent to an address that proved it can receive
    # packets there, so a code holder can't spoof a STREAM request to flood someone else's address.
    cookies: dict = {}

    def cookie_for(addr):
        return cookies.setdefault(tuple(addr), os.urandom(COOKIE_LEN))

    try:
        pub = _public_endpoint(sock)
        if not pub:
            ch.publish({"v": 1, "t": "answer", "sid": join["sid"], "error": "home helper has no UDP internet access"})
            return {"connected": False, "error": "no STUN reply at home"}
        ch.publish({"v": 1, "t": "answer", "sid": join["sid"], "cand": list(pub),
                    "local": [local_ip(), sock.getsockname()[1]], "home": home_code, "ts": time.time()})
        peer, _ = _punch(sock, pk, _candidates(pub[0], join), time.perf_counter() + PUNCH_SECONDS + 5, cookie_for)
        if not peer:
            return {"connected": False}
        log({"event": "session_connected", "peer": peer[0]})
        stop = threading.Event()
        streamer = None
        idle_deadline = time.time() + 30
        while time.time() < idle_deadline:
            sock.settimeout(0.5)
            try:
                data, addr = sock.recvfrom(4096)
            except (socket.timeout, OSError):
                continue
            p = pk.parse(data)
            if not p:
                continue
            typ, seq, ts, payload = p
            peer = addr  # follow the peer if its NAT re-maps
            idle_deadline = time.time() + 30
            if typ == PUNCH:
                sock.sendto(pk.make(ACK, payload=cookie_for(addr)), addr)
            elif typ == PING:
                sock.sendto(pk.make(PONG, seq, ts=ts), addr)
            elif (typ == STREAM and streamer is None and len(payload) >= 8 + COOKIE_LEN
                  and tuple(addr) in cookies and hmac.compare_digest(payload[8:8 + COOKIE_LEN], cookies[tuple(addr)])):
                rate_kbps, dur_ms = struct.unpack("!II", payload[:8])
                rate_kbps, dur_ms = min(rate_kbps, MAX_STREAM_KBPS), min(dur_ms, MAX_STREAM_MS)
                streamer = threading.Thread(target=_stream, args=(sock, pk, addr, rate_kbps, dur_ms, stop), daemon=True)
                streamer.start()
            elif typ == BYE:
                break
        stop.set()
        if streamer:
            streamer.join(2)
        return {"connected": True, "peer": peer[0]}
    finally:
        sock.close()


def run_helper(code: str, relay_url: str | None, log, home_check=None, recheck: threading.Event | None = None,
               stop: threading.Event | None = None) -> None:
    """Serve live tests until `stop` is set. `log(dict)` receives events; `home_check()` returns
    (home code, overall). Setting `recheck` forces an immediate home self-check."""
    ch = relay.Channel(code, relay_url)
    listener = ch.listen()
    home_code = None
    home_at = 0.0
    seen: set[str] = set()
    recent: list[float] = []
    log({"event": "ready", "code": code, "relay": ch.relay})
    while not (stop and stop.is_set()):
        forced = recheck is not None and recheck.is_set()
        if home_check and (forced or time.time() - home_at > 3600):
            if recheck is not None:
                recheck.clear()
            log({"event": "home_check_started"})
            try:
                home_code, overall = home_check()
                log({"event": "home_check_done", "overall": overall})
            except Exception as e:  # noqa: BLE001 - keep serving even if the self-check breaks
                log({"event": "home_check_failed", "error": str(e)})
            home_at = time.time()
        if not listener.connected.is_set() and listener.error:
            log({"event": "relay_error", "error": listener.error})
        msg = listener.get(timeout=2)
        if msg and msg.get("t") == "result" and msg.get("sid") in seen:
            log({"event": "session_result", **{k: v for k, v in msg.items() if k not in ("v", "t")}})
            continue
        if not msg or msg.get("t") != "join" or msg.get("sid") in seen:
            continue
        if abs(time.time() - float(msg.get("ts", 0))) > JOIN_MAX_AGE:
            continue
        seen.add(msg["sid"])
        now = time.time()
        recent[:] = [t for t in recent if now - t < 3600]
        if (recent and now - recent[-1] < MIN_SESSION_GAP) or len(recent) >= MAX_SESSIONS_PER_HOUR:
            log({"event": "session_rate_limited", "sid": msg["sid"], "from": (msg.get("cand") or ["?"])[0]})
            continue
        recent.append(now)
        log({"event": "session_start", "sid": msg["sid"], "from": (msg.get("cand") or ["?"])[0]})
        try:
            res = _serve_session(ch, code, msg, home_code, log)
        except Exception as e:  # noqa: BLE001
            res = {"connected": False, "error": str(e)}
        log({"event": "session_end", "sid": msg["sid"], **res})
    listener.stop()


# ============================================================================ client (away)

def run_client(code: str, relay_url: str | None = None, rate_mbps: float = 15.0,
               seconds: float = 6.0, step=lambda m: None) -> tuple[dict, str | None]:
    """Run the live test. Returns (result, home_code_from_helper)."""
    res: dict = {"ran": True, "relay_ok": False, "helper_found": False, "connected": False,
                 "path": None, "error": None}
    ch = relay.Channel(code, relay_url)
    sock = _udp_socket()
    listener = ch.listen(since=str(int(time.time()) - 5))
    sid = pub = None
    try:
        pub = _public_endpoint(sock)
        if not pub:
            res["error"] = "UDP is blocked on this network (no STUN reply)"
            return res, None
        sid = os.urandom(8)
        join = {"v": 1, "t": "join", "sid": sid.hex(), "cand": list(pub),
                "local": [local_ip(), sock.getsockname()[1]], "ts": time.time()}
        step("contacting the home helper via the relay")
        try:
            ch.publish(join)
        except OSError as e:
            res["error"] = f"relay unreachable: {getattr(e, 'reason', e)}"
            return res, None
        res["relay_ok"] = True

        answer = None
        deadline = time.time() + ANSWER_TIMEOUT
        republished = False
        while time.time() < deadline:
            msg = listener.get(timeout=1)
            if msg and msg.get("t") == "answer" and msg.get("sid") == sid.hex():
                answer = msg
                break
            if not republished and time.time() > deadline - ANSWER_TIMEOUT / 2:
                join["ts"] = time.time()
                ch.publish(join)
                republished = True
        if not answer:
            res["error"] = "the home helper did not answer"
            return res, None
        res["helper_found"] = True
        if answer.get("error"):
            res["error"] = answer["error"]
            return res, answer.get("home")
        res["home_public_ip"] = answer["cand"][0]

        step("opening a direct connection to home (UDP hole punching)")
        pk = Packets(code, sid)
        peer, ms = _punch(sock, pk, _candidates(pub[0], answer), time.perf_counter() + PUNCH_SECONDS)
        res["punch_ms"] = round(ms)
        if not peer:
            return res, answer.get("home")
        res["connected"] = True
        res["path"] = "lan" if answer.get("local") and peer[0] == answer["local"][0] and peer[0] != answer["cand"][0] \
            else "internet"

        cookie = _fetch_cookie(sock, pk, peer)
        step("measuring round-trip time to home")
        res["rtt"] = _ping(sock, pk, peer)
        step(f"streaming test video traffic from home ({rate_mbps:g} Mbps for {seconds:g} s)")
        res["stream"] = _receive_stream(sock, pk, peer, rate_mbps, seconds, cookie)
        for _ in range(3):
            sock.sendto(pk.make(BYE), peer)
        return res, answer.get("home")
    finally:
        listener.stop()
        sock.close()
        if res.get("helper_found"):
            _publish_result(ch, res, sid, pub)


def _publish_result(ch, res: dict, sid: bytes | None, pub) -> None:
    """Best effort: tell the helper how the test went (shown in the Home Assistant panel)."""
    if not sid:
        return
    rtt, st = res.get("rtt") or {}, res.get("stream") or {}
    try:
        ch.publish({"v": 1, "t": "result", "sid": sid.hex(), "ts": time.time(),
                    "from": pub[0] if pub else None, "connected": res.get("connected"), "path": res.get("path"),
                    "punch_ms": res.get("punch_ms"), "rtt_ms": rtt.get("avg_ms"), "jitter_ms": rtt.get("jitter_ms"),
                    "stream_mbps": st.get("received_mbps"), "target_mbps": st.get("target_mbps"),
                    "loss_pct": st.get("loss_pct"), "error": res.get("error")})
    except OSError:
        pass


def _fetch_cookie(sock, pk: Packets, peer, tries: int = 6) -> bytes:
    """Ask the helper for the cookie bound to the address it actually sees for us."""
    for _ in range(tries):
        sock.sendto(pk.make(PUNCH), peer)
        end = time.perf_counter() + 0.5
        while time.perf_counter() < end:
            sock.settimeout(0.1)
            try:
                data, addr = sock.recvfrom(4096)
            except (socket.timeout, OSError):
                continue
            p = pk.parse(data)
            if p and p[0] == ACK and len(p[3]) >= COOKIE_LEN:
                return p[3][:COOKIE_LEN]
    return b""


def _ping(sock, pk: Packets, peer, count: int = 40, interval: float = 0.025) -> dict:
    rtts: dict[int, float] = {}
    sent_at: dict[int, float] = {}
    start = time.perf_counter()
    end = start + count * interval + 1.0
    nxt = 0
    while time.perf_counter() < end:
        now = time.perf_counter()
        if nxt < count and now >= start + nxt * interval:
            sent_at[nxt] = now
            sock.sendto(pk.make(PING, nxt), peer)
            nxt += 1
        sock.settimeout(0.005)
        try:
            data, _ = sock.recvfrom(4096)
        except (socket.timeout, OSError):
            continue
        p = pk.parse(data)
        if p and p[0] == PONG and p[1] in sent_at and p[1] not in rtts:
            rtts[p[1]] = (time.perf_counter() - sent_at[p[1]]) * 1000
    vals = [rtts[k] for k in sorted(rtts)]
    out = {"sent": count, "received": len(vals), "loss_pct": round(100 * (count - len(vals)) / count, 1)}
    if vals:
        out.update(avg_ms=round(statistics.mean(vals), 1), min_ms=round(min(vals), 1), max_ms=round(max(vals), 1),
                   jitter_ms=round(statistics.mean(abs(a - b) for a, b in zip(vals, vals[1:])), 1) if len(vals) > 1 else 0.0)
    return out


def _receive_stream(sock, pk: Packets, peer, rate_mbps: float, seconds: float, cookie: bytes = b"") -> dict:
    request = pk.make(STREAM, 0, struct.pack("!II", int(rate_mbps * 1000), int(seconds * 1000)) + cookie)
    seqs: set[int] = set()
    first = last = None
    sent_total = None
    jitter = 0.0
    prev_transit = None
    nbytes = 0
    asked = 0
    next_ask = 0.0
    deadline = time.perf_counter() + seconds + 5
    while time.perf_counter() < deadline:
        now = time.perf_counter()
        if first is None and asked < 4 and now >= next_ask:
            sock.sendto(request, peer)
            asked += 1
            next_ask = now + 0.5
        sock.settimeout(0.2)
        try:
            data, _ = sock.recvfrom(4096)
        except (socket.timeout, OSError):
            continue
        p = pk.parse(data)
        if not p:
            continue
        typ, seq, ts, payload = p
        if typ == DATA:
            arrival = time.perf_counter()
            if seq not in seqs:
                seqs.add(seq)
                nbytes += len(data)
            first = first if first is not None else arrival
            last = arrival
            transit = time.time() - ts  # clock offset cancels out in the differences below (RFC 3550)
            if prev_transit is not None:
                jitter += (abs(transit - prev_transit) - jitter) / 16
            prev_transit = transit
        elif typ == END and len(payload) >= 4:
            sent_total = struct.unpack("!I", payload[:4])[0]
            break
    out = {"target_mbps": rate_mbps, "seconds": seconds, "packets_received": len(seqs)}
    if not seqs:
        out.update(received_mbps=0.0, loss_pct=100.0, error="no stream packets arrived")
        return out
    sent_total = sent_total or (max(seqs) + 1)
    span = max(last - first, 0.001)
    out.update(packets_sent=sent_total,
               received_mbps=round(nbytes * 8 / span / 1_000_000, 1),
               loss_pct=round(100 * max(0, sent_total - len(seqs)) / sent_total, 1),
               jitter_ms=round(jitter * 1000, 1))
    return out
