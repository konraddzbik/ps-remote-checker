import queue
import time
import threading
import unittest
from unittest import mock

from ps_remote_checker import pairtest, relay, verdict


class CodeAndCryptoTests(unittest.TestCase):
    def test_code_format_roundtrip(self):
        code = relay.new_code()
        self.assertRegex(code, r"^[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}$")
        self.assertEqual(relay.normalize_code(code.lower().replace("-", " ")), code.replace("-", ""))

    def test_bad_code(self):
        with self.assertRaises(ValueError):
            relay.normalize_code("ABC")
        with self.assertRaises(ValueError):
            relay.normalize_code("ABCD-EFGH-IJK0")  # I and 0 are not in the alphabet

    def test_seal_open_and_tamper(self):
        ch = relay.Channel("ABCD-EFGH-JKMN")
        blob = ch.seal({"t": "join", "cand": ["1.2.3.4", 5]})
        self.assertEqual(ch.open(blob), {"t": "join", "cand": ["1.2.3.4", 5]})
        self.assertNotIn("1.2.3.4", blob)
        other = relay.Channel("ABCD-EFGH-JKMP")
        self.assertIsNone(other.open(blob))
        self.assertNotEqual(ch.topic, other.topic)
        raw = bytearray(relay.base64.urlsafe_b64decode(blob))
        raw[20] ^= 1
        self.assertIsNone(ch.open(relay.base64.urlsafe_b64encode(bytes(raw)).decode()))

    def test_packets(self):
        a = pairtest.Packets("ABCD-EFGH-JKMN", b"12345678")
        pkt = a.make(pairtest.PING, 7, b"hi")
        self.assertEqual(a.parse(pkt)[:2], (pairtest.PING, 7))
        self.assertIsNone(pairtest.Packets("ABCD-EFGH-JKMP", b"12345678").parse(pkt))  # wrong key
        self.assertIsNone(pairtest.Packets("ABCD-EFGH-JKMN", b"87654321").parse(pkt))  # wrong session
        self.assertEqual(len(a.make(pairtest.DATA, 1)), pairtest.DATA_SIZE)


# --- in-memory relay so the whole protocol can run over loopback --------------------------

class FakeListener:
    def __init__(self):
        self.queue = queue.Queue()
        self.connected = threading.Event()
        self.connected.set()
        self.error = None

    def get(self, timeout):
        try:
            return self.queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self):
        pass


class FakeChannel:
    listeners: list = []

    def __init__(self, code, relay_url=None):
        self.relay = "memory"

    def listen(self, since=None):
        lst = FakeListener()
        FakeChannel.listeners.append(lst)
        return lst

    def publish(self, obj):
        for lst in list(FakeChannel.listeners):
            lst.queue.put(dict(obj))


class LoopbackLiveTest(unittest.TestCase):
    def test_full_protocol_over_loopback(self):
        FakeChannel.listeners = []
        code = relay.new_code()
        events = []
        with mock.patch.object(pairtest.relay, "Channel", FakeChannel), \
                mock.patch.object(pairtest, "_public_endpoint", lambda s: ("127.0.0.1", s.getsockname()[1])):
            stop = threading.Event()
            t = threading.Thread(target=pairtest.run_helper, args=(code, None, events.append, None),
                                 kwargs={"stop": stop}, daemon=True)
            t.start()
            res, home = pairtest.run_client(code, rate_mbps=8, seconds=1.5)
            time.sleep(2.5)  # let the helper pick up the published result
            stop.set()
        self.assertTrue(res["helper_found"], res)
        self.assertTrue(res["connected"], res)
        self.assertEqual(res["path"], "internet")
        self.assertGreater(res["rtt"]["received"], 30)
        self.assertGreater(res["stream"]["packets_received"], 500)
        self.assertLess(res["stream"]["loss_pct"], 5)
        self.assertTrue(any(e["event"] == "session_start" for e in events))
        results = [e for e in events if e["event"] == "session_result"]
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["connected"])
        self.assertGreater(results[0]["stream_mbps"], 4)


class CookieTests(unittest.TestCase):
    def test_stream_requires_cookie_bound_to_address(self):
        FakeChannel.listeners = []
        code = relay.new_code()
        stop = threading.Event()
        with mock.patch.object(pairtest.relay, "Channel", FakeChannel), \
                mock.patch.object(pairtest, "_public_endpoint", lambda s: ("127.0.0.1", s.getsockname()[1])), \
                mock.patch.object(pairtest, "_fetch_cookie", lambda *a, **k: b"\0" * pairtest.COOKIE_LEN):
            t = threading.Thread(target=pairtest.run_helper, args=(code, None, lambda e: None),
                                 kwargs={"stop": stop}, daemon=True)
            t.start()
            res, _ = pairtest.run_client(code, rate_mbps=8, seconds=1.0)
        stop.set()
        self.assertTrue(res["connected"], res)
        self.assertEqual(res["stream"]["packets_received"], 0)  # helper refused: wrong cookie


class RateLimitTests(unittest.TestCase):
    def test_second_join_within_gap_is_refused(self):
        FakeChannel.listeners = []
        code, events, stop = relay.new_code(), [], threading.Event()
        with mock.patch.object(pairtest.relay, "Channel", FakeChannel), \
                mock.patch.object(pairtest, "_serve_session", lambda *a: {"connected": False}):
            t = threading.Thread(target=pairtest.run_helper, args=(code, None, events.append),
                                 kwargs={"stop": stop}, daemon=True)
            t.start()
            time.sleep(0.2)
            ch = FakeChannel(code)
            for sid in ("aa" * 8, "bb" * 8):
                ch.publish({"t": "join", "sid": sid, "cand": ["1.2.3.4", 1], "ts": time.time()})
            time.sleep(1.0)
            stop.set()
        names = [e["event"] for e in events]
        self.assertEqual(names.count("session_start"), 1)
        self.assertEqual(names.count("session_rate_limited"), 1)


class LiveVerdictTests(unittest.TestCase):
    def base(self, **live):
        rep = {"kind": "remote", "nat": {"type": "symmetric", "public_ip": "2.2.2.2"},
               "internet": {"internet": True, "captive_portal": False}, "psn": {"reachable": True},
               "latency": None, "speed": None,
               "live": {"ran": True, "relay_ok": True, "helper_found": True, "connected": True,
                        "path": "internet", "punch_ms": 300,
                        "rtt": {"received": 40, "avg_ms": 30, "jitter_ms": 2, "loss_pct": 0},
                        "stream": {"target_mbps": 15, "received_mbps": 15, "loss_pct": 0}}}
        rep["live"].update(live)
        return rep

    def home(self):
        return {"kind": "home", "nat": {"type": "symmetric", "public_ip": "1.1.1.1"},
                "ps5": {"found": True}, "upnp": {"found": False}, "latency": None, "speed": None}

    def conn(self, remote):
        ev = verdict.evaluate_pair(self.home(), remote)
        return [f["level"] for f in ev["findings"] if f["area"] == "Connection"], ev["overall"]

    def test_verified_overrides_symmetric_prediction(self):
        self.assertEqual(self.conn(self.base()), (["ok"], "ok"))

    def test_failed_punch_is_fail(self):
        levels, overall = self.conn(self.base(connected=False, path=None))
        self.assertEqual(levels, ["fail"])
        self.assertEqual(overall, "fail")

    def test_helper_missing_falls_back_to_prediction(self):
        levels, _ = self.conn(self.base(helper_found=False, connected=False))
        self.assertEqual(levels, ["fail"])  # symmetric + symmetric prediction

    def test_slow_stream_fails(self):
        f = verdict.evaluate_live(self.base(stream={"target_mbps": 15, "received_mbps": 3, "loss_pct": 40})["live"])
        self.assertEqual(f[-1]["level"], "fail")

    def test_lan_path_warns(self):
        f = verdict.evaluate_live(self.base(path="lan")["live"])
        self.assertEqual(f[0]["level"], "warn")


if __name__ == "__main__":
    unittest.main()
