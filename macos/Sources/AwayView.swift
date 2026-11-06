import SwiftUI

struct AwayView: View {
    @EnvironmentObject var state: AppState
    @State private var showPaste = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                PageHeader(symbol: "airplane", title: "Away network · PS Portal",
                           subtitle: "Run this on the Wi-Fi your PS Portal will use away from home: hotel, friend's place, office or phone hotspot.",
                           tint: .purple)

                homeSourceCard
                liveCard

                RunPanel(section: .away, buttonTitle: state.remote == nil ? "Run away check" : "Run again") {
                    state.runAway()
                }

                if let remote = state.remote {
                    AwayResults(output: remote)
                }
            }
            .padding(28)
            .frame(maxWidth: 980, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .sheet(isPresented: $showPaste) { PasteCodeSheet() }
    }

    @ViewBuilder private var homeSourceCard: some View {
        Card {
            HStack(alignment: .top, spacing: 14) {
                Image(systemName: state.homeReference == nil ? "house.slash.fill" : "house.circle.fill")
                    .font(.title).foregroundStyle(state.homeReference == nil ? .orange : .blue)
                VStack(alignment: .leading, spacing: 6) {
                    if state.pastedHomeCode?.isEmpty == false {
                        Text("Comparing with a pasted home code").font(.headline)
                        Text("The home check was made on another computer.").foregroundStyle(.secondary)
                    } else if let home = state.home {
                        Text("Comparing with your home check").font(.headline)
                        Text(homeSummary(home)).foregroundStyle(.secondary)
                    } else {
                        Text("No home check yet").font(.headline)
                        Text("You can still test this network on its own. For the full \"will it connect\" answer, run the Home check first, or paste a home code from another computer.")
                            .foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                    }
                    HStack {
                        Button { showPaste = true } label: { Label("Paste home code…", systemImage: "doc.on.clipboard") }
                        if state.pastedHomeCode?.isEmpty == false {
                            Button("Use this Mac's home check instead") { state.clearPastedCode() }
                                .disabled(state.home == nil)
                        }
                    }
                    .padding(.top, 2)
                }
            }
        }
    }

    @ViewBuilder private var liveCard: some View {
        Card {
            HStack(alignment: .top, spacing: 14) {
                Image(systemName: "antenna.radiowaves.left.and.right")
                    .font(.title).foregroundStyle(.teal)
                VStack(alignment: .leading, spacing: 8) {
                    Text("Live test with the home helper").font(.headline)
                    Text("Is the helper running at home? Enter its pairing code to test a real direct connection and a 15 Mbps stream from home to here. The helper also sends a fresh home check, so you don't need a home code.")
                        .foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                    HStack(spacing: 10) {
                        TextField("ABCD-EFGH-JKMN", text: $state.pairCode)
                            .font(.system(.body, design: .monospaced))
                            .textFieldStyle(.roundedBorder).frame(maxWidth: 220)
                        if state.pairCode.isEmpty {
                            Text("optional").font(.caption).foregroundStyle(.tertiary)
                        } else if AppState.isValidCode(state.pairCode) {
                            Label("Live test will run", systemImage: "checkmark.circle.fill")
                                .font(.callout).foregroundStyle(.green)
                        } else {
                            Label("Code should be 12 letters/digits", systemImage: "exclamationmark.triangle.fill")
                                .font(.callout).foregroundStyle(.orange)
                        }
                        Spacer()
                        if !state.pairCode.isEmpty {
                            Button("Clear") { state.pairCode = "" }
                        }
                        Button { state.section = .helper } label: { Label("How do I get a code?", systemImage: "questionmark.circle") }
                            .buttonStyle(.link)
                    }
                }
            }
        }
    }

    private func homeSummary(_ h: HomeOutput) -> String {
        var parts = [String]()
        if let d = h.report.date { parts.append("checked \(relativeFormatter.localizedString(for: d, relativeTo: Date()))") }
        if let ip = h.report.nat?.publicIp { parts.append("home public IP \(ip)") }
        if let nat = h.report.nat { parts.append("NAT \(nat.playStationType)") }
        return parts.joined(separator: " · ").prefix(1).uppercased() + parts.joined(separator: " · ").dropFirst()
    }
}

struct AwayResults: View {
    let output: RemoteOutput
    var r: Report { output.report }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            if let pair = output.pair {
                VerdictBanner(level: pair.overall, title: pairHeadline(pair.overall), detail: pairDetail(pair.overall))
                ConnectionDiagram(home: pair.home.overall, remote: pair.remote.overall, link: linkLevel(pair))
                FindingsCard(title: "PS5 ⇄ PS Portal connection", findings: pair.findings)
            } else {
                VerdictBanner(level: output.evaluation.overall,
                              title: output.evaluation.overall == .fail ? "This network has a blocking problem" :
                                     output.evaluation.overall == .warn ? "This network may cause issues" : "This network looks good",
                              detail: "Run the Home check too for the full connection verdict.")
            }

            if let live = r.live, live.ran == true {
                Text("Live test").font(.title3.bold()).padding(.top, 4)
                if output.homeFromHelper == true {
                    Label("Home results came straight from the home helper.", systemImage: "house.circle.fill")
                        .font(.callout).foregroundStyle(.secondary)
                }
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 200), spacing: 12)], spacing: 12) {
                    let sum = live.summary
                    MetricTile(symbol: "point.3.connected.trianglepath.dotted", title: "Direct connection",
                               value: sum.value, detail: sum.detail, level: sum.level)
                    if let rtt = live.rtt, let avg = rtt.avgMs {
                        MetricTile(symbol: "arrow.left.arrow.right", title: "Round trip to home",
                                   value: "\(Int(avg.rounded())) ms",
                                   detail: "jitter \(String(format: "%.1f", rtt.jitterMs ?? 0)) ms · loss \(Int(rtt.lossPct ?? 0))%",
                                   level: avg > 150 ? .fail : avg > 80 ? .warn : .ok)
                    }
                    if let st = live.stream {
                        let got = st.receivedMbps ?? 0, target = st.targetMbps ?? 15, loss = st.lossPct ?? 100
                        MetricTile(symbol: "play.tv.fill", title: "Test stream home → here",
                                   value: formatMbps(got),
                                   detail: "of \(Int(target)) Mbps sent · \(String(format: "%.1f", loss))% lost",
                                   level: (got < 5 || loss > 5) ? .fail : (got < target * 0.8 || loss > 1) ? .warn : .ok)
                    }
                }
            }

            Text("This network").font(.title3.bold()).padding(.top, 4)
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 200), spacing: 12)], spacing: 12) {
                MetricTile(symbol: "globe", title: "Internet", value: internetValue, detail: internetDetail, level: internetLevel)
                MetricTile(symbol: "person.badge.key.fill", title: "PlayStation Network",
                           value: r.psn?.reachable == true ? "Reachable" : "Blocked",
                           level: r.psn?.reachable == true ? .ok : .fail)
                MetricTile(symbol: "network", title: "NAT type", value: r.nat?.playStationType ?? "—",
                           detail: r.nat?.description, level: r.nat?.level)
                MetricTile(symbol: "waveform.path.ecg", title: "Latency", value: r.latency?.avgMs.map { "\(Int($0)) ms" } ?? "—",
                           detail: r.latency.map { "jitter \(Int($0.jitterMs ?? 0)) ms · loss \(Int($0.lossPct ?? 0))%" },
                           level: latencyLevel(r.latency))
                MetricTile(symbol: "arrow.down.circle.fill", title: "Download (stream)", value: formatMbps(r.speed?.downMbps),
                           detail: r.speed == nil ? "speed test skipped" : "upload \(formatMbps(r.speed?.upMbps)) · need ≥ 15",
                           level: speedLevel(r.speed?.downMbps))
                MetricTile(symbol: "globe", title: "Public IP", value: r.nat?.publicIp ?? "—", detail: "This Mac: \(r.localIp ?? "?")")
            }
            FindingsCard(title: "Away network details", findings: output.pair?.remote.findings ?? output.evaluation.findings)
            if let home = output.pair?.home {
                FindingsCard(title: "Home network (from the home check)", findings: home.findings)
            }
            if let date = r.date {
                Text("Checked \(relativeFormatter.localizedString(for: date, relativeTo: Date()))")
                    .font(.caption).foregroundStyle(.tertiary)
            }
        }
    }

    private func linkLevel(_ p: PairEvaluation) -> Level {
        let conn = p.findings.filter { $0.area == "Connection" }.map(\.level)
        return conn.contains(.fail) ? .fail : conn.contains(.warn) ? .warn : .ok
    }

    private func pairHeadline(_ l: Level) -> String {
        switch l {
        case .ok: return "Remote Play should work"
        case .warn: return "Remote Play may work, with issues"
        case .fail: return "Remote Play is unlikely to work"
        }
    }

    private func pairDetail(_ l: Level) -> String {
        switch l {
        case .ok: return "Your PS Portal should be able to reach your PS5 from this network."
        case .warn: return "It might connect, but see the suggestions below to make it reliable."
        case .fail: return "Something below blocks the connection. Fix the red items first."
        }
    }

    private var internetValue: String {
        if r.internet?.internet == false { return "Offline" }
        return r.internet?.captivePortal == true ? "Login page" : "Online"
    }

    private var internetDetail: String {
        r.internet?.captivePortal == true ? "Sign in to the Wi-Fi first" : "No captive portal"
    }

    private var internetLevel: Level {
        (r.internet?.internet == false || r.internet?.captivePortal == true) ? .fail : .ok
    }
}

/// PS5 ─ home router ─ internet/PSN ─ away network ─ PS Portal, coloured by each part's result.
struct ConnectionDiagram: View {
    let home: Level
    let remote: Level
    let link: Level

    var body: some View {
        Card {
            HStack(spacing: 0) {
                node("playstation.logo", "PS5", home)
                connector(home)
                node("wifi.router.fill", "Home router", home)
                connector(link)
                node("cloud.fill", "Internet · PSN", link)
                connector(link)
                node("wifi", "Away Wi-Fi", remote)
                connector(remote)
                node("gamecontroller.fill", "PS Portal", remote)
            }
            .frame(maxWidth: .infinity)
        }
    }

    private func node(_ symbol: String, _ label: String, _ level: Level) -> some View {
        VStack(spacing: 6) {
            Image(systemName: symbol)
                .font(.system(size: 20, weight: .semibold))
                .foregroundStyle(level.color)
                .frame(width: 48, height: 48)
                .background(Circle().fill(level.color.opacity(0.12)))
                .overlay(Circle().strokeBorder(level.color.opacity(0.5), lineWidth: 1.5))
            Text(label).font(.caption).foregroundStyle(.secondary).lineLimit(1).fixedSize()
        }
    }

    private func connector(_ level: Level) -> some View {
        Rectangle()
            .fill(level.color.opacity(0.6))
            .frame(height: 3)
            .frame(minWidth: 12, maxWidth: .infinity)
            .padding(.bottom, 20)
    }
}

struct PasteCodeSheet: View {
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    @State private var text = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Paste home code").font(.title2.bold())
            Text("On the computer that ran the home check, click \"Copy home code\" (or run `ps-remote-check home` in Terminal) and paste the code that starts with PSRC1.")
                .foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            TextEditor(text: $text)
                .font(.system(.body, design: .monospaced))
                .frame(height: 120)
                .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(Color.primary.opacity(0.15)))
            if !text.isEmpty && !valid {
                Label("The code should start with PSRC1.", systemImage: "exclamationmark.triangle.fill").foregroundStyle(.orange)
            }
            HStack {
                Spacer()
                Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction)
                Button("Use code") { state.setPastedCode(text); dismiss() }
                    .keyboardShortcut(.defaultAction).disabled(!valid)
            }
        }
        .padding(24)
        .frame(width: 520)
    }

    private var valid: Bool { text.trimmingCharacters(in: .whitespacesAndNewlines).hasPrefix("PSRC1.") }
}
