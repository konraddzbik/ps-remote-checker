import socket
import struct
import unittest

from ps_remote_checker import cli, discovery, netinfo, stun, verdict


def stun_response(txid, ip, port, xor=True):
    if xor:
        p = port ^ (stun.MAGIC_COOKIE >> 16)
        a = struct.unpack("!I", socket.inet_aton(ip))[0] ^ stun.MAGIC_COOKIE
        attr_type = stun.ATTR_XOR_MAPPED_ADDRESS
    else:
        p, a = port, struct.unpack("!I", socket.inet_aton(ip))[0]
        attr_type = stun.ATTR_MAPPED_ADDRESS
    value = struct.pack("!BBHI", 0, 1, p, a)
    attr = struct.pack("!HH", attr_type, len(value)) + value
    return struct.pack("!HHI", stun.BINDING_SUCCESS, len(attr), stun.MAGIC_COOKIE) + txid + attr


class StunTests(unittest.TestCase):
    def test_xor_mapped(self):
        txid = b"123456789012"
        self.assertEqual(stun.parse_response(stun_response(txid, "203.0.113.7", 54321), txid),
                         ("203.0.113.7", 54321))

    def test_plain_mapped(self):
        txid = b"abcdefghijkl"
        self.assertEqual(stun.parse_response(stun_response(txid, "198.51.100.1", 1000, xor=False), txid),
                         ("198.51.100.1", 1000))

    def test_wrong_txid_rejected(self):
        self.assertIsNone(stun.parse_response(stun_response(b"x" * 12, "1.2.3.4", 1), b"y" * 12))

    def test_request_format(self):
        req = stun.build_request(b"z" * 12)
        self.assertEqual(len(req), 20)
        self.assertEqual(struct.unpack("!HHI", req[:8]), (1, 0, stun.MAGIC_COOKIE))


class DiscoveryTests(unittest.TestCase):
    def test_parse_on(self):
        r = discovery.parse_reply(b"HTTP/1.1 200 Ok\nhost-id:ABC\nhost-type:PS5\nhost-name:PS5-123\n"
                                  b"host-request-port:997\nsystem-version:09000000\n")
        self.assertEqual(r["status"], "on")
        self.assertEqual(r["name"], "PS5-123")
        self.assertEqual(r["host_type"], "PS5")

    def test_parse_standby(self):
        self.assertEqual(discovery.parse_reply(b"HTTP/1.1 620 Server Standby\nhost-type:PS5\n")["status"], "standby")

    def test_garbage(self):
        self.assertIsNone(discovery.parse_reply(b"hello"))


class NetinfoTests(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(netinfo.classify_ip("100.70.1.1"), "cgnat")
        self.assertEqual(netinfo.classify_ip("192.168.1.1"), "private")
        self.assertEqual(netinfo.classify_ip("8.8.8.8"), "public")
        self.assertEqual(netinfo.classify_ip(None), "unknown")


def home(nat="eim", ip="1.1.1.1", upnp=None, ps5=True):
    return {"kind": "home", "nat": {"type": nat, "public_ip": ip},
            "ps5": {"found": ps5, "ip": "192.168.1.50", "status": "on", "name": "PS5"},
            "upnp": upnp or {"found": False}, "latency": None, "speed": {"up_mbps": 30, "down_mbps": 100}}


def remote(nat="eim", ip="2.2.2.2", captive=False):
    return {"kind": "remote", "nat": {"type": nat, "public_ip": ip},
            "internet": {"internet": True, "captive_portal": captive},
            "psn": {"reachable": True}, "latency": None, "speed": {"down_mbps": 50, "up_mbps": 10}}


class VerdictTests(unittest.TestCase):
    def conn(self, h, r):
        ev = verdict.evaluate_pair(h, r)
        return ev["overall"], [f for f in ev["findings"] if f["area"] == "Connection"][0]["level"]

    def test_both_cone_ok(self):
        self.assertEqual(self.conn(home(), remote()), ("ok", "ok"))

    def test_both_symmetric_fail(self):
        self.assertEqual(self.conn(home("symmetric"), remote("symmetric"))[1], "fail")

    def test_symmetric_but_ps5_upnp_ok(self):
        up = {"found": True, "external_ip": "1.1.1.1", "cgnat": False, "double_nat": False,
              "ps5_mappings": [{"protocol": "UDP", "external_port": 9296}]}
        self.assertEqual(self.conn(home("symmetric", upnp=up), remote("symmetric"))[1], "ok")

    def test_upnp_behind_cgnat_does_not_count(self):
        up = {"found": True, "external_ip": "100.64.0.5", "cgnat": True, "double_nat": False,
              "ps5_mappings": [{"protocol": "UDP", "external_port": 9296}]}
        self.assertEqual(self.conn(home("symmetric", upnp=up), remote("symmetric"))[1], "fail")

    def test_mixed_warn(self):
        self.assertEqual(self.conn(home("eim"), remote("symmetric"))[1], "warn")

    def test_udp_blocked_fail(self):
        self.assertEqual(self.conn(home(), remote("udp_blocked")), ("fail", "fail"))

    def test_captive_portal_fails_overall(self):
        self.assertEqual(self.conn(home(), remote(captive=True))[0], "fail")

    def test_low_upload_fails(self):
        h = home()
        h["speed"]["up_mbps"] = 2
        self.assertEqual(self.conn(h, remote())[0], "fail")

    def test_same_ip_warns(self):
        ev = verdict.evaluate_pair(home(ip="9.9.9.9"), remote(ip="9.9.9.9"))
        self.assertTrue(any(f["area"] == "Setup" for f in ev["findings"]))


class ShareCodeTests(unittest.TestCase):
    def test_roundtrip(self):
        h = home(upnp={"found": True, "external_ip": "1.1.1.1", "cgnat": False, "double_nat": False,
                       "ps5_mappings": [], "mappings": [{"x": 1}] * 50})
        code = cli.encode_report(h)
        self.assertTrue(code.startswith("PSRC1."))
        back = cli.decode_report(code)
        self.assertEqual(back["nat"], h["nat"])
        self.assertNotIn("mappings", back["upnp"])


if __name__ == "__main__":
    unittest.main()


class AddonSyncTests(unittest.TestCase):
    def test_addon_has_current_checker_copy(self):
        """homeassistant/sync.sh must be run after changing ps_remote_checker/."""
        import filecmp
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        src, dst = root / "ps_remote_checker", root / "homeassistant" / "ps_remote_helper" / "ps_remote_checker"
        for f in src.glob("*.py"):
            self.assertTrue(filecmp.cmp(f, dst / f.name, shallow=False), f"{f.name} differs - run homeassistant/sync.sh")
