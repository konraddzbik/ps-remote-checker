import SwiftUI

struct HomeView: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                PageHeader(symbol: "house.fill", title: "Home network · PS5",
                           subtitle: "Run this on a Mac connected to the same router as your PS5 (Wi-Fi or cable).",
                           tint: .blue)

                Card {
                    Text("Before you start").font(.headline)
                    ChecklistItem(text: "PS5 is turned on or in rest mode.")
                    ChecklistItem(text: "This Mac is on the same home network as the PS5.")
                    ChecklistItem(text: "Remote Play is enabled on the PS5: Settings › System › Remote Play.")
                    ChecklistItem(text: "If macOS asks to find devices on your local network, click Allow.")
                    HStack {
                        Text("PS5 IP address (optional)").foregroundStyle(.secondary)
                        TextField("auto-detect", text: $state.ps5IP)
                            .textFieldStyle(.roundedBorder).frame(maxWidth: 180)
                        Text("PS5: Settings › Network › Connection Status").font(.caption).foregroundStyle(.tertiary)
                    }
                    .padding(.top, 4)
                }

                RunPanel(section: .home, buttonTitle: state.home == nil ? "Run home check" : "Run again") {
                    state.runHome()
                }

                if let home = state.home {
                    HomeResults(output: home)
                }

                Card {
                    HStack(spacing: 14) {
                        Image(systemName: "antenna.radiowaves.left.and.right").font(.title).foregroundStyle(.teal)
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Want proof instead of a prediction?").font(.headline)
                            Text("Leave a helper running at home (this Mac or a Raspberry Pi) and the Away check will test a real connection to it.")
                                .foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                        }
                        Spacer()
                        Button { state.section = .helper } label: { Label("Set up home helper", systemImage: "arrow.right") }
                    }
                }
            }
            .padding(28)
            .frame(maxWidth: 980, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
    }
}

struct HomeResults: View {
    @EnvironmentObject var state: AppState
    let output: HomeOutput
    @State private var copied = false

    var r: Report { output.report }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            VerdictBanner(level: output.evaluation.overall, title: headline, detail: detailLine)

            LazyVGrid(columns: [GridItem(.adaptive(minimum: 200), spacing: 12)], spacing: 12) {
                MetricTile(symbol: "playstation.logo", title: "PS5", value: ps5Value, detail: ps5Detail,
                           level: r.ps5?.found == true ? .ok : .warn)
                MetricTile(symbol: "network", title: "NAT type", value: r.nat?.playStationType ?? "—",
                           detail: r.nat?.description, level: r.nat?.level)
                MetricTile(symbol: "globe", title: "Public IP", value: r.nat?.publicIp ?? "—",
                           detail: "This Mac: \(r.localIp ?? "?")")
                MetricTile(symbol: "wifi.router.fill", title: "Router / UPnP", value: routerValue,
                           detail: routerDetail, level: routerLevel)
                MetricTile(symbol: "waveform.path.ecg", title: "Latency", value: r.latency?.avgMs.map { "\(Int($0)) ms" } ?? "—",
                           detail: r.latency.map { "jitter \(fmt($0.jitterMs)) ms · loss \(fmt($0.lossPct))%" },
                           level: latencyLevel(r.latency))
                MetricTile(symbol: "arrow.up.circle.fill", title: "Upload (stream)", value: formatMbps(r.speed?.upMbps),
                           detail: r.speed == nil ? "speed test skipped" : "download \(formatMbps(r.speed?.downMbps)) · need ≥ 15",
                           level: speedLevel(r.speed?.upMbps))
            }

            FindingsCard(title: "Details & what to do", findings: output.evaluation.findings)

            Card {
                HStack(alignment: .top, spacing: 14) {
                    Image(systemName: "arrow.right.circle.fill").font(.title).foregroundStyle(.purple)
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Next step").font(.headline)
                        Text("The home result is saved. Take this Mac to the place where you will use the PS Portal, connect to the same Wi-Fi the Portal will use (or your phone hotspot), and open **2 · Away**.")
                            .fixedSize(horizontal: false, vertical: true)
                        Text("Running the away check on a different computer? Copy the home code and paste it there.")
                            .font(.callout).foregroundStyle(.secondary)
                        HStack {
                            Button { state.section = .away } label: { Label("Go to Away check", systemImage: "airplane") }
                            Button {
                                state.copyHomeCode(); copied = true
                            } label: { Label(copied ? "Copied" : "Copy home code", systemImage: copied ? "checkmark" : "doc.on.doc") }
                        }
                        .padding(.top, 4)
                    }
                }
            }
            if let date = r.date {
                Text("Checked \(relativeFormatter.localizedString(for: date, relativeTo: Date()))")
                    .font(.caption).foregroundStyle(.tertiary)
            }
        }
    }

    private var headline: String {
        switch output.evaluation.overall {
        case .ok: return "Home network is ready"
        case .warn: return "Home network needs attention"
        case .fail: return "Home network has a blocking problem"
        }
    }

    private var detailLine: String {
        let n = output.evaluation.findings.filter { $0.level != .ok }.count
        return n == 0 ? "Everything checked out. Now run the Away check." : "\(n) item\(n == 1 ? "" : "s") below with suggested fixes."
    }

    private var ps5Value: String {
        guard r.ps5?.found == true else { return "Not found" }
        return r.ps5?.name ?? "PS5"
    }

    private var ps5Detail: String {
        guard let p = r.ps5, p.found == true else { return "Check it's on and on this network" }
        let st = p.status == "on" ? "On" : p.status == "standby" ? "Rest mode" : (p.status ?? "")
        return "\(st) · \(p.ip ?? "")"
    }

    private var routerValue: String {
        guard let u = r.upnp, u.found == true else { return "UPnP off" }
        if u.cgnat == true { return "CGNAT" }
        if u.doubleNat == true { return "Double NAT" }
        let n = u.ps5Mappings?.count ?? 0
        return n > 0 ? "PS5 ports open" : "UPnP on"
    }

    private var routerDetail: String {
        guard let u = r.upnp, u.found == true else { return "No UPnP router answered" }
        var parts = [String]()
        if let d = u.device { parts.append(d) }
        if let ip = u.externalIp { parts.append("WAN \(ip)") }
        return parts.joined(separator: " · ")
    }

    private var routerLevel: Level {
        guard let u = r.upnp, u.found == true else { return .warn }
        if u.cgnat == true || u.doubleNat == true { return .warn }
        return (u.ps5Mappings?.isEmpty == false) ? .ok : .warn
    }

    private func fmt(_ v: Double?) -> String {
        guard let v else { return "—" }
        return v == v.rounded() ? String(Int(v)) : String(format: "%.1f", v)
    }
}
