# PS Remote Helper

Runs the **PS Remote Checker home helper** on your Home Assistant box, behind the same router as your PS5.
From away (hotel, friend's Wi-Fi, phone hotspot) the PS Remote Checker Mac app or CLI opens a real direct UDP
connection to it, the same way PSN connects the PS5 and the PS Portal, and streams 15 Mbps of test traffic to measure
what actually arrives.

The **PS Remote** panel in the sidebar shows the pairing code, an hourly home self-check (PS5, NAT type, UPnP,
upload speed) and the results of every live test.

## Options

| Option | Description |
|---|---|
| `pairing_code` | Leave empty to auto-generate one (rotate it from the panel). Set it to use a fixed code. |
| `relay` | ntfy server used to exchange addresses. Default `https://ntfy.sh`; can be self-hosted. |
| `ps5_ip` | PS5 address, only needed if the self-check can't find it by broadcast. |
| `self_check_speed_test` | Include a ~15 s upload/download test in the hourly self-check. |

## Testing from away

Turn **Tailscale off** on the testing laptop (or at least don't use an exit node), so the test uses the same internet
path the PS Portal will. Then run the Away check with the pairing code:

```
python3 -m ps_remote_checker remote --pair ABCD-EFGH-JKMN
```

## Security

* The panel is only reachable through Home Assistant Ingress. The add-on refuses all other clients, even though it
  uses the host network.
* The process drops root and runs as an unprivileged user. It has no Home Assistant or Supervisor API access.
* No port forwarding is needed. A UDP path is opened only during a test, and only with matching
  HMAC-authenticated packets.
* The test stream only goes to an address that proved it can receive there (return-routability cookie), and is capped
  at 30 Mbps for 15 s.
* The relay only sees encrypted, authenticated blobs on a topic derived from the code.
