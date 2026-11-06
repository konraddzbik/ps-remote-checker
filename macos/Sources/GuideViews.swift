import SwiftUI

struct StartView: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                PageHeader(symbol: "gamecontroller.fill", title: "PS Remote Checker",
                           subtitle: "Find out if your PS Portal can play on your PS5 when you're away from home.",
                           tint: .indigo)

                Card {
                    Text("How it works").font(.headline)
                    Text("When you play away from home, the PS Portal and the PS5 sign in to PlayStation Network, which introduces them to each other. The video then streams **directly** between the two over the internet (UDP). Both networks therefore need to let that direct connection through, and both need enough speed.")
                        .fixedSize(horizontal: false, vertical: true)
                    ConnectionDiagram(home: .ok, remote: .ok, link: .ok)
                }

                HStack(alignment: .top, spacing: 14) {
                    stepCard(1, "house.fill", .blue, "Home check",
                             "At home, on the same router as the PS5. Finds the PS5 and checks the router, NAT type and upload speed. Optionally leave the home helper running for a live test.",
                             button: "Open Home check", target: .home)
                    stepCard(2, "airplane", .purple, "Away check",
                             "On the Wi-Fi the Portal will use. Checks for login pages, blocked traffic, NAT type and download speed. With the helper's pairing code it also tests a real connection home.",
                             button: "Open Away check", target: .away)
                }

                Card {
                    Text("Good to know").font(.headline)
                    ChecklistItem(text: "The PS Portal can't run apps, so run the Away check on this Mac connected to the same Wi-Fi the Portal will use.", symbol: "info.circle")
                    ChecklistItem(text: "A laptop is easiest: run Home, carry it with you, run Away. On a different computer, use \"Copy home code\" and \"Paste home code\".", symbol: "laptopcomputer")
                    ChecklistItem(text: "Results are approximate. Sony doesn't publish the exact rules, but NAT type, speed and latency are what make or break Remote Play.", symbol: "chart.bar.xaxis")
                    ChecklistItem(text: "The check sends small test packets to public STUN servers and downloads/uploads a few MB from Cloudflare for the speed test.", symbol: "lock.shield")
                }
            }
            .padding(28)
            .frame(maxWidth: 980, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
    }

    private func stepCard(_ n: Int, _ symbol: String, _ tint: Color, _ title: String, _ text: String,
                          button: String, target: Section) -> some View {
        Card {
            HStack(spacing: 10) {
                Text("\(n)").font(.system(size: 15, weight: .bold, design: .rounded)).foregroundStyle(.white)
                    .frame(width: 28, height: 28).background(Circle().fill(tint))
                Image(systemName: symbol).foregroundStyle(tint)
                Text(title).font(.headline)
                Spacer()
                if let level = state.status(for: target) {
                    Image(systemName: level.symbol).foregroundStyle(level.color)
                }
            }
            Text(text).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
            Button(button) { state.section = target }
        }
    }
}

struct HelpView: View {
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                PageHeader(symbol: "wrench.and.screwdriver.fill", title: "Fixes & ports",
                           subtitle: "What the results mean and how to fix common problems.", tint: .teal)

                Card {
                    Text("NAT types").font(.headline)
                    natRow("Type 1", "Open, no NAT", "Best. The PS5 is directly on the internet.", .ok)
                    natRow("Type 2", "Cone NAT", "Normal home router. Works with almost everything.", .ok)
                    natRow("Type 3", "Symmetric / strict NAT", "Direct connections are unreliable. Works only if the other side is open or Type 2, and not always even then.", .warn)
                    natRow("Blocked", "UDP blocked", "Typical on corporate or hotel networks. Remote Play can't stream.", .fail)
                    Divider()
                    Text("Home Type 2 + Away Type 2 → should work.   Type 2 + Type 3 → may work.   Type 3 + Type 3 → won't connect unless the PS5's ports are open.")
                        .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }

                Card {
                    Text("Open the PS5's ports").font(.headline)
                    ChecklistItem(text: "Easiest: enable **UPnP** in your router's settings, then on the PS5 run Settings › Network › Connection Status › Test Internet Connection.", symbol: "1.circle.fill")
                    ChecklistItem(text: "Or give the PS5 a fixed IP (DHCP reservation) and forward these ports to it:", symbol: "2.circle.fill")
                    HStack(spacing: 10) {
                        portChip("TCP", "9295")
                        portChip("UDP", "9296–9297")
                        portChip("UDP", "9302–9304")
                    }
                    .padding(.leading, 28)
                }

                Card {
                    Text("Problems your internet provider can cause").font(.headline)
                    ChecklistItem(text: "**CGNAT** (router's WAN IP starts with 100.64–100.127): you share a public IP with other customers, so port forwarding can't work. Ask your ISP for a public IPv4 address.", symbol: "building.2.fill")
                    ChecklistItem(text: "**Double NAT** (router's WAN IP is 192.168.x / 10.x / 172.16–31.x): there are two routers. Put the ISP modem in bridge mode, or forward the ports on both.", symbol: "square.stack.3d.down.right.fill")
                }

                Card {
                    Text("PS5 & PS Portal settings").font(.headline)
                    ChecklistItem(text: "PS5 › Settings › System › Remote Play › **Enable Remote Play**.")
                    ChecklistItem(text: "PS5 › Settings › System › Power Saving › Features Available in Rest Mode › **Stay Connected to the Internet** and **Enable Turning On PS5 from Network**.")
                    ChecklistItem(text: "Link the PS Portal to the PS5 once at home before travelling.")
                    ChecklistItem(text: "On hotel Wi-Fi, open the login page from the Portal's Wi-Fi settings first.")
                }

                Card {
                    Text("Speed & quality").font(.headline)
                    ChecklistItem(text: "Sony recommends **15 Mbps** (minimum 5 Mbps). Home **upload** matters: the PS5 sends the video. Away **download** matters: the Portal receives it.", symbol: "speedometer")
                    ChecklistItem(text: "Connect the PS5 with an Ethernet cable if you can. Away from home, use 5 GHz Wi-Fi.", symbol: "cable.connector")
                    ChecklistItem(text: "Stuttering? Lower the video quality in PS5 › Settings › System › Remote Play.", symbol: "slider.horizontal.3")
                    ChecklistItem(text: "A phone hotspot is a good fallback when hotel or office Wi-Fi blocks Remote Play.", symbol: "iphone.radiowaves.left.and.right")
                }
            }
            .padding(28)
            .frame(maxWidth: 980, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
    }

    private func natRow(_ type: String, _ name: String, _ text: String, _ level: Level) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Text(type).font(.callout.weight(.bold)).foregroundStyle(level.color)
                .frame(width: 70, alignment: .leading)
            VStack(alignment: .leading, spacing: 2) {
                Text(name).font(.callout.weight(.semibold))
                Text(text).font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private func portChip(_ proto: String, _ ports: String) -> some View {
        HStack(spacing: 6) {
            Text(proto).font(.caption.weight(.bold)).foregroundStyle(.white)
                .padding(.horizontal, 6).padding(.vertical, 2)
                .background(Capsule().fill(proto == "TCP" ? Color.blue : Color.purple))
            Text(ports).font(.system(.callout, design: .monospaced).weight(.semibold))
        }
        .padding(.horizontal, 10).padding(.vertical, 6)
        .background(RoundedRectangle(cornerRadius: 8).fill(Color.primary.opacity(0.05)))
        .textSelection(.enabled)
    }
}
