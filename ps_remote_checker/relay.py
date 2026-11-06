"""Signalling between the home helper and the away check, through a public ntfy relay.

Both sides only need to exchange their public UDP endpoints ("candidates") to try a
direct connection, the same thing PSN does for the PS5 and the PS Portal. The relay
just carries a few small messages:

  * the topic name is derived from the pairing code (the code itself is never sent);
  * every message is encrypted and authenticated with a key derived from the code
    (SHA-256 keystream + HMAC-SHA256), so the relay only ever sees opaque blobs.

Any ntfy server works (https://ntfy.sh by default, or a self-hosted one via --relay).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import queue
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .netinfo import USER_AGENT

DEFAULT_RELAY = "https://ntfy.sh"
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L
CODE_LEN = 12  # ~59 bits


def new_code() -> str:
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))
    return "-".join(raw[i:i + 4] for i in range(0, CODE_LEN, 4))


def normalize_code(code: str) -> str:
    raw = "".join(ch for ch in code.upper() if ch.isalnum())
    if len(raw) != CODE_LEN or any(ch not in CODE_ALPHABET for ch in raw):
        raise ValueError("pairing code should look like ABCD-EFGH-JKMN (12 letters/digits)")
    return raw


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        out += hashlib.sha256(key + nonce + counter.to_bytes(8, "big")).digest()
        counter += 1
    return bytes(out[:length])


class Channel:
    def __init__(self, code: str, relay: str | None = None):
        norm = normalize_code(code).encode()
        self.key = hashlib.sha256(b"psrc-key:" + norm).digest()
        self.mac_key = hashlib.sha256(b"psrc-mac:" + norm).digest()
        self.topic = "psrc_" + hashlib.sha256(b"psrc-topic:" + norm).hexdigest()[:32]
        self.relay = (relay or DEFAULT_RELAY).rstrip("/")

    # -- crypto ---------------------------------------------------------------
    def seal(self, obj: dict) -> str:
        pt = json.dumps(obj, separators=(",", ":")).encode()
        nonce = os.urandom(16)
        ct = bytes(a ^ b for a, b in zip(pt, _keystream(self.key, nonce, len(pt))))
        tag = hmac.new(self.mac_key, nonce + ct, hashlib.sha256).digest()[:16]
        return base64.urlsafe_b64encode(nonce + ct + tag).decode()

    def open(self, text: str) -> dict | None:
        try:
            blob = base64.urlsafe_b64decode(text.strip())
        except (ValueError, TypeError):
            return None
        if len(blob) < 33:
            return None
        nonce, ct, tag = blob[:16], blob[16:-16], blob[-16:]
        if not hmac.compare_digest(tag, hmac.new(self.mac_key, nonce + ct, hashlib.sha256).digest()[:16]):
            return None
        try:
            return json.loads(bytes(a ^ b for a, b in zip(ct, _keystream(self.key, nonce, len(ct)))))
        except ValueError:
            return None

    # -- transport ------------------------------------------------------------
    def publish(self, obj: dict) -> None:
        req = urllib.request.Request(f"{self.relay}/{self.topic}", data=self.seal(obj).encode(), method="POST",
                                     headers={"User-Agent": USER_AGENT, "Content-Type": "text/plain"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()

    def listen(self, since: str | None = None) -> "Listener":
        lst = Listener(self, since)
        lst.start()
        return lst


class Listener(threading.Thread):
    """Background subscription to the topic; decrypted messages land in `.queue`."""

    def __init__(self, channel: Channel, since: str | None):
        super().__init__(daemon=True)
        self.channel = channel
        self.since = since
        self.queue: "queue.Queue[dict]" = queue.Queue()
        self.connected = threading.Event()
        self.error: str | None = None
        self._halt = threading.Event()

    def stop(self) -> None:
        self._halt.set()

    def run(self) -> None:
        while not self._halt.is_set():
            params = {"since": self.since} if self.since else {}
            url = f"{self.channel.relay}/{self.channel.topic}/json"
            if params:
                url += "?" + urllib.parse.urlencode(params)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=75) as resp:  # server sends keepalives every ~45 s
                    self.connected.set()
                    self.error = None
                    while not self._halt.is_set():
                        line = resp.readline()
                        if not line:
                            break
                        try:
                            evt = json.loads(line)
                        except ValueError:
                            continue
                        if evt.get("id"):
                            self.since = evt["id"]
                        if evt.get("event") == "message":
                            obj = self.channel.open(evt.get("message", ""))
                            if obj is not None:
                                self.queue.put(obj)
            except (urllib.error.URLError, OSError, ValueError) as e:
                self.error = str(getattr(e, "reason", e))
            if not self._halt.is_set():
                time.sleep(2)

    def get(self, timeout: float) -> dict | None:
        try:
            return self.queue.get(timeout=timeout)
        except queue.Empty:
            return None
