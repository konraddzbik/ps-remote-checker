# PS Remote Play checker (PS5 ⇄ PS Portal)

A small command-line app that tells you whether your **PS Portal** (or the PS Remote Play app)
will be able to connect to your **PS5** when you are **away from home**.

It checks the two networks separately:

1. **Home check** (PS5 side): run on a computer connected to the same router as the PS5.
2. **Remote check** (PS Portal side): run on a computer or phone hotspot on the network the Portal will use (hotel, friend's Wi-Fi, office, mobile hotspot).

It then combines both into one verdict.

The checker is plain Python 3.9+ with no dependencies, and it runs on macOS, Linux and Windows.

## Quick start

```bash
# 1) At home, on the PS5's network (PS5 on or in rest mode)
python3 -m ps_remote_checker home -o home.json

# 2) On the remote network (copy home.json along, or use the printed code)
python3 -m ps_remote_checker remote --home home.json

# or compare two saved reports later
python3 -m ps_remote_checker compare home.json remote.json
```

If you run `home` without `-o`, it prints a **home code** (`PSRC1.…`). You can paste the code
instead of a file: `remote --home PSRC1.xxxx`. This is handy when you only have a chat or
notes app to carry it between the two networks.

To install it as a command, run `pip install .`, then use `ps-remote-check home`, `ps-remote-check remote` and so on.

Options: `--no-speed` skips the bandwidth test, `--speed-seconds N` sets its length,
and `--ps5-ip 192.168.1.50` is for when broadcast discovery can't find the console.

The exit code is `0` for OK or warnings and `1` when something blocks Remote Play.

## macOS app

There is also a native macOS app (SwiftUI) with the same checks. It has four pages: **Start here**, **1 · Home (PS5)**,
**2 · Away (PS Portal)** and **Fixes & ports**. Each result comes with tiles, a colour-coded verdict and suggested fixes.

```bash
macos/build.sh                       # builds macos/build/PS Remote Checker.app (Apple silicon + Intel)
open "macos/build/PS Remote Checker.app"
```

- To build it you need the Xcode Command Line Tools. To run it you need any Python 3.9+: Homebrew, python.org, or the
  `/usr/bin/python3` that comes with the Command Line Tools. The checker engine is bundled inside the app.
- When macOS asks whether the app can find devices on your local network, click **Allow**. Without it the app can't
  find the PS5 or the router.
- Results are saved in `~/Library/Application Support/PS Remote Checker/`, so you can run Home, travel with the
  laptop, and run Away later. On another computer, use **Copy home code** / **Paste home code…**.
- The app is ad-hoc signed. If you copy it to another Mac, right-click it and choose Open the first time.

## Live test (home helper)

The checks above *predict* whether the two networks can connect. The live test *proves* it.
Leave a helper running on any always-on device behind the home router: the Mac app, a Raspberry Pi, a NAS
or a Linux box. Then the away check opens a real direct UDP connection to it, the same way PSN connects the
PS5 and the Portal (STUN + hole punching). Over that connection it measures the round-trip time and receives
a paced **15 Mbps test stream from home**, like the PS5's video.

```bash
# at home (keeps running; prints a pairing code like 8V4C-7FXW-DJMJ)
python3 -m ps_remote_checker helper
python3 -m ps_remote_checker helper --code 8V4C-7FXW-DJMJ     # reuse a fixed code

# away, on the Portal's network
python3 -m ps_remote_checker remote --pair 8V4C-7FXW-DJMJ
```

- The helper also runs the home check every hour and sends the result along, so `--home` isn't needed with `--pair`.
- **Signalling** uses the public [ntfy](https://ntfy.sh) relay. The topic name is derived from the code, and messages are
  encrypted and authenticated with a key from the code, so the relay sees neither your IPs nor the code. To use your
  own ntfy server, pass `--relay https://ntfy.example.com`.
- The UDP test packets are authenticated with the code as well. The helper caps streams at 50 Mbps for 15 s.
- The helper stands in for the PS5: it sits behind the same router, so it gets the same NAT treatment. If the PS5
  opened its own ports via UPnP, Remote Play can work even when the helper's test fails, and the verdict accounts for that.
- Running both ends on the same network only connects over the LAN. The app flags that, so for a real result test
  away from home, for example from a phone hotspot.
- In the Mac app, open the **Home helper (live test)** page in the sidebar. **Option A** runs the helper on that Mac,
  which won't idle-sleep while it runs. **Option B** uses "Save Raspberry Pi kit…" to create a `ps-remote-helper` folder.
  The pairing code goes on the **Away** page.

### Raspberry Pi / Linux helper as a service

```bash
scp -r ps-remote-helper pi@raspberrypi.local:~              # kit from the app, or: ps_remote_checker/ + deploy/rpi/install.sh
ssh pi@raspberrypi.local 'sudo ~/ps-remote-helper/install.sh'   # reads pairing-code.txt, or pass the code as an argument
ssh pi@raspberrypi.local journalctl -u ps-remote-helper -f
```

The installer copies the checker to `/opt/ps-remote-checker` and runs it as the unprivileged `psrc` user through the
`ps-remote-helper` systemd service, which restarts automatically and starts on boot.

## Home Assistant add-on

`homeassistant/ps_remote_helper` runs the home helper on Home Assistant OS/Supervised, behind the same router as the
PS5. It adds a **PS Remote** sidebar panel (via Ingress, so it's reachable over Tailscale with your HA login) showing the
pairing code, an hourly home self-check and the results of every live test.

Install: in Home Assistant go to *Settings › Apps (Add-ons) › Store › ⋮ › Repositories* and add this repository's URL.
For a private repository, use a fine-grained read-only token:
`https://<token>@github.com/konraddzbik/ps-remote-checker`. Then install **PS Remote Helper** and start it.
After changing `ps_remote_checker/`, run `homeassistant/sync.sh` and bump `version` in
`homeassistant/ps_remote_helper/config.yaml` so Home Assistant offers the update.

## What is checked

| Check | Home (PS5) | Remote (Portal) | Why it matters |
|---|---|---|---|
| PS5 discovery (UDP 9302, Sony discovery protocol) | ✔ | | Confirms the PS5 is on the LAN and whether it is on or in rest mode |
| NAT type via STUN (mapping behaviour) | ✔ | ✔ | The stream is peer-to-peer UDP, brokered by PSN. NAT types decide whether hole punching works |
| UPnP, router WAN IP, CGNAT / double NAT | ✔ | | Whether the PS5 can open its ports, and whether port forwarding can work at all |
| UPnP port mappings that point at the PS5 | ✔ | | Shows that the PS5 really opened its Remote Play ports |
| UDP latency, jitter and loss | ✔ | ✔ | Stutter and disconnects |
| Bandwidth | upload | download | The PS5 sends the video and the Portal receives it. Sony recommends ≥ 15 Mbps (minimum 5) |
| Captive portal | | ✔ | Hotel Wi-Fi login pages block the Portal |
| PlayStation Network reachability | | ✔ | Sign-in and session brokering |

### How the verdict is reached

| Home side | Remote side | Result |
|---|---|---|
| Ports open (public IP, or UPnP mappings for the PS5 and no CGNAT or double NAT) | any NAT that allows UDP | ✔ should work |
| Cone NAT (≈ NAT Type 2) | Cone NAT | ✔ hole punching should work |
| Cone | Symmetric (≈ NAT Type 3), or the reverse | ! may work |
| Symmetric | Symmetric | ✘ won't connect |
| any | UDP blocked / captive portal / PSN unreachable | ✘ |

## Typical fixes

- **Enable UPnP** on the home router. Then on the PS5, go to *Settings › Network › Connection Status › Test Internet Connection*.
- Or **forward the ports to the PS5** after giving it a fixed IP: TCP 9295, and UDP 9296–9297 and 9302–9304.
- **CGNAT** (the router's WAN IP is in 100.64.0.0/10): port forwarding is impossible. Ask your ISP for a public IPv4 address.
- **Double NAT**: put the ISP modem in bridge mode, or forward the ports on both routers.
- PS5 settings: enable *Remote Play*, and in *Power Saving* turn on *Stay connected to the internet* and *Enable turning on PS5 from network*.
- Wire the PS5 with Ethernet if you can. On the remote side, prefer 5 GHz Wi-Fi.

## Limitations

- The PS Portal can't run apps, so the remote check runs on another device on the **same network** the Portal will use.
- STUN measures NAT *mapping* behaviour only. NAT *filtering* can't be tested with public servers, so "mixed" results are a "may work".
- The NAT result describes this computer's path through the router. It matches the PS5 when both are behind the same router.

## Tests

```bash
python3 -m unittest discover -s tests -v
```
