"""Turn home / remote reports into findings and a final "can these connect?" verdict.

Model of PS Remote Play over the internet (PS5 <-> PS Portal):
  * Both devices sign in to PSN, which brokers the session.
  * The video stream flows directly peer-to-peer over UDP (no Sony relay), so the
    two NATs must allow UDP hole punching, or the home side must have ports open
    (UPnP / manual forwarding / public IP).
  * Hole punching works when both NATs use endpoint-independent mapping ("cone",
    PlayStation NAT Type 2). If one side is symmetric (NAT Type 3) it *may* work;
    if both are symmetric it fails.
  * Sony recommends >= 15 Mbps (minimum 5 Mbps): home *upload*, remote *download*.
"""
from __future__ import annotations

from .netinfo import classify_ip

OK, WARN, FAIL = "ok", "warn", "fail"
MIN_MBPS, GOOD_MBPS = 5.0, 15.0

NAT_LABELS = {
    "open": "Open / no NAT  (≈ PlayStation NAT Type 1)",
    "eim": "Cone NAT, endpoint-independent  (≈ PlayStation NAT Type 2)",
    "symmetric": "Symmetric NAT  (≈ PlayStation NAT Type 3)",
    "unknown": "Unknown (only one STUN server answered)",
    "udp_blocked": "UDP blocked - no STUN reply",
    "dns_failed": "DNS failed - no internet?",
}


def _f(level, area, msg, fix=None):
    return {"level": level, "area": area, "message": msg, "fix": fix}


def _overall(findings):
    levels = {f["level"] for f in findings}
    return FAIL if FAIL in levels else WARN if WARN in levels else OK


def home_ports_open(home: dict) -> bool:
    """True if the PS5 is reachable from outside without hole punching."""
    nat = home.get("nat", {})
    if nat.get("type") == "open":
        return True
    upnp = home.get("upnp") or {}
    return bool(upnp.get("ps5_mappings")) and not upnp.get("cgnat") and not upnp.get("double_nat")


def _common_findings(rep: dict, side: str) -> list:
    out = []
    nat = rep.get("nat") or {}
    ntype = nat.get("type", "unknown")
    label = NAT_LABELS.get(ntype, ntype)
    if ntype in ("udp_blocked", "dns_failed"):
        out.append(_f(FAIL, "NAT", f"{label}.",
                      "This network blocks UDP (common on corporate/hotel Wi-Fi). Remote Play cannot "
                      "stream here. Try another network or a phone hotspot." if side == "remote" else
                      "Check the router/firewall: outbound UDP must be allowed for Remote Play."))
    elif ntype == "symmetric":
        out.append(_f(WARN, "NAT", f"{label}. Hole punching from this side is unreliable.",
                      "Enable UPnP or forward ports on the home router; on the remote side a phone hotspot "
                      "often helps." if side == "home" else
                      "Ensure the home side has UPnP/port forwarding, or use a different remote network."))
    elif ntype == "unknown":
        out.append(_f(WARN, "NAT", f"{label}."))
    else:
        out.append(_f(OK, "NAT", f"{label}. Public IP {nat.get('public_ip')}."))
    if nat.get("multiple_public_ips"):
        out.append(_f(WARN, "NAT", "Different public IPs seen for different servers (load-balanced / carrier NAT).",
                      "This behaves like symmetric NAT; port forwarding at home is strongly recommended."))

    lat = rep.get("latency") or {}
    if lat.get("received"):
        avg, jit, loss = lat.get("avg_ms", 0), lat.get("jitter_ms", 0), lat.get("loss_pct", 0)
        msg = f"UDP latency {avg} ms, jitter {jit} ms, loss {loss}%."
        if loss > 5 or avg > 150 or jit > 40:
            out.append(_f(FAIL, "Latency", msg, "Expect stutter/disconnects. Prefer wired or 5 GHz Wi-Fi, avoid busy networks."))
        elif loss > 1 or avg > 80 or jit > 20:
            out.append(_f(WARN, "Latency", msg, "Playable but may stutter. Prefer wired or 5 GHz Wi-Fi."))
        else:
            out.append(_f(OK, "Latency", msg))

    sp = rep.get("speed")
    if sp:
        key, what = ("up_mbps", "upload (PS5 sends the video)") if side == "home" else \
                    ("down_mbps", "download (Portal receives the video)")
        val = sp.get(key)
        if val is None:
            out.append(_f(WARN, "Speed", f"Could not measure {what}: {sp.get('error') or 'no data'}."))
        elif val < MIN_MBPS:
            out.append(_f(FAIL, "Speed", f"{val} Mbps {what}; minimum is {MIN_MBPS:g} Mbps."))
        elif val < GOOD_MBPS:
            out.append(_f(WARN, "Speed", f"{val} Mbps {what}; Sony recommends {GOOD_MBPS:g} Mbps.",
                          "Lower the Remote Play resolution / video quality in PS5 settings."))
        else:
            out.append(_f(OK, "Speed", f"{val} Mbps {what}."))
    return out


def evaluate_home(home: dict) -> dict:
    findings = []
    ps5 = home.get("ps5") or {}
    if ps5.get("found"):
        st = "on" if ps5.get("status") == "on" else "in rest mode"
        findings.append(_f(OK, "PS5", f"Found {ps5.get('name') or 'PS5'} at {ps5.get('ip')} ({st})."))
        if ps5.get("status") == "standby":
            findings.append(_f(OK, "PS5", "Rest mode is fine if 'Stay connected to the internet' and "
                                          "'Enable turning on PS5 from network' are on (Settings > System > Power Saving)."))
    else:
        findings.append(_f(WARN, "PS5", "No PS5 answered on this network.",
                           "Make sure the PS5 is on or in rest mode, Remote Play is enabled "
                           "(Settings > System > Remote Play), and this computer is on the same LAN/subnet."))

    findings += _common_findings(home, "home")

    upnp = home.get("upnp") or {}
    public_ip = (home.get("nat") or {}).get("public_ip")
    if upnp.get("found"):
        ext = upnp.get("external_ip")
        kind = classify_ip(ext)
        if upnp.get("cgnat"):
            findings.append(_f(FAIL if (home.get("nat") or {}).get("type") == "symmetric" else WARN, "ISP",
                               f"Carrier-grade NAT: router WAN IP {ext} is in 100.64.0.0/10.",
                               "Port forwarding can't work behind CGNAT. Ask your ISP for a public IPv4 address."))
        elif upnp.get("double_nat"):
            findings.append(_f(WARN, "Router", f"Double NAT: router WAN IP {ext} is private ({kind}).",
                               "Put the ISP modem in bridge mode, or forward ports on BOTH routers / use DMZ."))
        elif ext and public_ip and ext != public_ip:
            findings.append(_f(WARN, "Router", f"Router WAN IP {ext} differs from public IP {public_ip}.",
                               "There may be another NAT layer upstream."))
        else:
            findings.append(_f(OK, "Router", f"UPnP enabled on '{upnp.get('device') or 'router'}', WAN IP matches public IP."))
        if upnp.get("ps5_mappings"):
            ports = ", ".join(f"{m['protocol']} {m['external_port']}" for m in upnp["ps5_mappings"][:8])
            findings.append(_f(OK, "Router", f"PS5 has opened ports via UPnP: {ports}."))
        elif ps5.get("found"):
            findings.append(_f(WARN, "Router", "UPnP is on but no port mappings point at the PS5.",
                               "Run 'Test Internet Connection' on the PS5 so it opens its ports, or forward "
                               "TCP 9295, UDP 9296-9297 and UDP 9302-9304 to the PS5 manually."))
    else:
        findings.append(_f(WARN, "Router", "UPnP not found on this network.",
                           "Enable UPnP on the router, or forward TCP 9295 and UDP 9296-9297, 9302-9304 to the PS5 "
                           "(give it a fixed IP). Without either, Remote Play relies purely on hole punching."))
    return {"overall": _overall(findings), "findings": findings}


LIVE_FIX = ("Open the PS5's ports at home (UPnP or forward TCP 9295, UDP 9296-9297, 9302-9304), "
            "use a phone hotspot, or use a travel router with a VPN back home (WireGuard/Tailscale).")


def evaluate_live(live: dict | None) -> list:
    """Findings for the live home-helper test (area 'Live test')."""
    if not live or not live.get("ran"):
        return []
    A = "Live test"
    if not live.get("relay_ok"):
        return [_f(FAIL if "UDP" in (live.get("error") or "") else WARN, A,
                   f"Live test could not start: {live.get('error')}.",
                   "Check the internet connection; a custom relay can be set with --relay.")]
    if not live.get("helper_found"):
        return [_f(WARN, A, "The home helper did not answer.",
                   "Make sure the helper is running at home with the same pairing code, and its device isn't asleep.")]
    if live.get("error"):
        return [_f(FAIL, A, f"Live test failed: {live['error']}.")]
    if not live.get("connected"):
        return [_f(FAIL, A, "Home and this network could NOT open a direct UDP connection "
                            f"(tried for {live.get('punch_ms', 0) / 1000:.0f} s). Remote Play will most likely fail the same way.",
                   LIVE_FIX)]
    out = []
    if live.get("path") == "lan":
        out.append(_f(WARN, A, "Connected, but over the local network: this test ran at home, not away.",
                      "Run the away check from the network the PS Portal will use (e.g. a phone hotspot)."))
    else:
        out.append(_f(OK, A, f"Verified: a direct UDP connection between home and here works "
                             f"(opened in {live.get('punch_ms')} ms)."))
    rtt = live.get("rtt") or {}
    if rtt.get("received"):
        msg = f"Round trip to home {rtt['avg_ms']} ms, jitter {rtt.get('jitter_ms', 0)} ms, loss {rtt['loss_pct']}%."
        avg, jit, loss = rtt["avg_ms"], rtt.get("jitter_ms", 0), rtt["loss_pct"]
        if avg > 150 or jit > 40 or loss > 5:
            out.append(_f(FAIL, A, msg, "Expect heavy lag. Try wired at home and 5 GHz Wi-Fi here."))
        elif avg > 80 or jit > 20 or loss > 1:
            out.append(_f(WARN, A, msg, "Playable, with noticeable input lag."))
        else:
            out.append(_f(OK, A, msg))
    st = live.get("stream") or {}
    if st:
        got, target, loss = st.get("received_mbps", 0), st.get("target_mbps", 15), st.get("loss_pct", 100)
        msg = f"Test stream home → here: {got} Mbps received of {target:g} Mbps sent, {loss}% packets lost."
        if st.get("error") or got < MIN_MBPS or loss > 5:
            out.append(_f(FAIL, A, msg, "Home upload or this network's download can't carry the stream. "
                                        "Lower Remote Play video quality, or check home upload."))
        elif got < target * 0.8 or loss > 1:
            out.append(_f(WARN, A, msg, "Lower the Remote Play video quality to avoid stutter."))
        else:
            out.append(_f(OK, A, msg))
    return out


def live_verified(remote: dict) -> bool | None:
    """True/False when the live test reached a conclusion about connectivity, None otherwise."""
    live = remote.get("live") or {}
    if not live.get("helper_found") or live.get("error"):
        return None
    if live.get("connected"):
        return True if live.get("path") == "internet" else None
    return False


def evaluate_remote(remote: dict) -> dict:
    findings = []
    inet = remote.get("internet") or {}
    if not inet.get("internet", True):
        findings.append(_f(FAIL, "Internet", "No internet connection."))
    elif inet.get("captive_portal"):
        findings.append(_f(FAIL, "Internet", "Captive portal detected (login page intercepts traffic).",
                           "Log in to the Wi-Fi in a browser first. The PS Portal can do this via its Wi-Fi settings."))
    else:
        findings.append(_f(OK, "Internet", "Internet works, no captive portal."))
    psn = remote.get("psn") or {}
    if psn:
        if psn.get("reachable"):
            findings.append(_f(OK, "PSN", "PlayStation Network servers reachable."))
        else:
            findings.append(_f(FAIL, "PSN", "PlayStation Network servers not reachable.",
                               "This network may block Sony domains; try another network."))
    findings += _common_findings(remote, "remote")
    findings += evaluate_live(remote.get("live"))
    return {"overall": _overall(findings), "findings": findings}


def evaluate_pair(home: dict, remote: dict) -> dict:
    findings = []
    h_nat = (home.get("nat") or {}).get("type", "unknown")
    r_nat = (remote.get("nat") or {}).get("type", "unknown")
    h_ip = (home.get("nat") or {}).get("public_ip")
    r_ip = (remote.get("nat") or {}).get("public_ip")

    if h_ip and r_ip and h_ip == r_ip:
        findings.append(_f(WARN, "Setup", f"Both reports have the same public IP ({h_ip}).",
                           "The remote check must run on the network the PS Portal will use away from home "
                           "(e.g. phone hotspot, friend's Wi-Fi), not on the home network."))

    blocked = {"udp_blocked", "dns_failed"}
    open_home = home_ports_open(home)
    verified = live_verified(remote)
    if verified is True:
        findings.append(_f(OK, "Connection", "Verified by the live test: home and this network can connect directly, "
                                             "the same way the PS5 and PS Portal do."))
    elif verified is False and open_home:
        findings.append(_f(WARN, "Connection", "The live test could not connect, but the PS5 has its own ports open via UPnP, "
                                               "so Remote Play may still work.", LIVE_FIX))
    elif verified is False:
        findings.append(_f(FAIL, "Connection", "The live test could not open a direct connection between home and this network.",
                           LIVE_FIX))
    elif h_nat in blocked or r_nat in blocked:
        side = "home" if h_nat in blocked else "remote"
        findings.append(_f(FAIL, "Connection", f"UDP does not get through on the {side} network, so no stream is possible."))
    elif open_home or r_nat == "open":
        why = "the PS5's ports are open (UPnP/public IP)" if open_home else "the remote side has no NAT"
        findings.append(_f(OK, "Connection", f"Direct connection should work: {why}."))
    elif h_nat == "eim" and r_nat == "eim":
        findings.append(_f(OK, "Connection", "Both sides use cone NAT, so UDP hole punching via PSN should succeed."))
    elif "symmetric" in (h_nat, r_nat) and h_nat != r_nat and "unknown" not in (h_nat, r_nat):
        sym = "home" if h_nat == "symmetric" else "remote"
        findings.append(_f(WARN, "Connection",
                           f"The {sym} side is symmetric NAT and the other is cone. Hole punching may or may not work.",
                           "Make it reliable by enabling UPnP or forwarding ports to the PS5 on the home router."))
    elif h_nat == "symmetric" and r_nat == "symmetric":
        findings.append(_f(FAIL, "Connection", "Both sides use symmetric NAT (NAT Type 3), so the peer-to-peer stream cannot be established.",
                           "Forward TCP 9295, UDP 9296-9297, 9302-9304 to the PS5 at home (needs a public IP, not CGNAT), "
                           "or use a different remote network."))
    else:
        findings.append(_f(WARN, "Connection", "NAT behaviour could not be fully determined on one side.",
                           "Re-run the checks; if it persists, enable UPnP/port forwarding at home."))

    upnp = home.get("upnp") or {}
    if upnp.get("cgnat") and not open_home and r_nat == "symmetric" and verified is None:
        findings.append(_f(FAIL, "Connection", "Home is behind carrier-grade NAT and the remote side is symmetric.",
                           "Ask your ISP for a public IPv4, or play from a network with cone NAT."))

    home_ev = evaluate_home(home)
    remote_ev = evaluate_remote(remote)
    all_findings = findings + [f for f in home_ev["findings"] + remote_ev["findings"]
                               if f["level"] == FAIL and f["area"] in ("Internet", "PSN", "Speed", "Latency", "Live test")]
    return {
        "overall": _overall(all_findings),
        "findings": findings,
        "home": home_ev,
        "remote": remote_ev,
    }
