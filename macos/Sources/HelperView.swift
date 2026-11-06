import AppKit
import SwiftUI

/// "Home helper" page: explains the live test and runs the helper on this Mac or prepares a Raspberry Pi.
struct HelperView: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                PageHeader(symbol: "antenna.radiowaves.left.and.right", title: "Home helper · live test",
                           subtitle: "Prove that the PS Portal's network can reach your home, instead of predicting it.",
                           tint: .teal)

                HowItWorksCard()

                Text("Choose where the helper runs at home").font(.title3.bold()).padding(.top, 4)
                Text("It must be connected to the **same router as the PS5** and stay on while you're away. Use one of these:")
                    .foregroundStyle(.secondary)

                ThisMacCard()
                RaspberryPiCard()

                Card {
                    Text("Then, away from home").font(.headline)
                    ChecklistItem(text: "Connect this Mac (or another computer) to the Wi-Fi the PS Portal will use, or to your phone hotspot.", symbol: "1.circle.fill")
                    ChecklistItem(text: "Open **2 · Away (PS Portal)**, enter the pairing code **\(state.helperCode)** and click Run.", symbol: "2.circle.fill")
                    ChecklistItem(text: "Look at the **Live test** tiles: *Direct connection*, *Round trip to home* and *Test stream home → here*.", symbol: "3.circle.fill")
                    Button { state.pairCode = state.helperCode; state.section = .away } label: {
                        Label("Use this code on the Away page", systemImage: "airplane")
                    }
                    .padding(.top, 2)
                }
            }
            .padding(28)
            .frame(maxWidth: 980, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
    }
}

private struct HowItWorksCard: View {
    var body: some View {
        Card {
            Text("How the direct connection works").font(.headline)
            HStack(alignment: .top, spacing: 0) {
                stepView("1", "house.fill", .blue, "Helper at home",
                         "Learns its public address from a STUN server, just like the PS5 does.")
                arrow
                stepView("2", "envelope.badge.shield.half.filled", .purple, "Exchange addresses",
                         "Both sides swap addresses through an encrypted relay (ntfy.sh), the role PSN plays for the PS5.")
                arrow
                stepView("3", "point.3.connected.trianglepath.dotted", .teal, "Punch through",
                         "Both send UDP packets at each other until the routers let them through.")
                arrow
                stepView("4", "play.tv.fill", .green, "Measure",
                         "Round trips plus a 15 Mbps test stream from home, like the PS5's video.")
            }
            Text("The helper sits behind the same router as the PS5, so it gets the same treatment from the router. If the helper connects, the PS5 can too.")
                .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
        }
    }

    private var arrow: some View {
        Image(systemName: "chevron.right").foregroundStyle(.tertiary).padding(.top, 14).padding(.horizontal, 4)
    }

    private func stepView(_ n: String, _ symbol: String, _ tint: Color, _ title: String, _ text: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Image(systemName: symbol).font(.system(size: 18, weight: .semibold)).foregroundStyle(tint)
                .frame(width: 40, height: 40).background(Circle().fill(tint.opacity(0.12)))
            Text("\(n). \(title)").font(.callout.weight(.semibold))
            Text(text).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct OptionBadge: View {
    let text: String
    let tint: Color
    var body: some View {
        Text(text).font(.caption.weight(.bold)).foregroundStyle(.white)
            .padding(.horizontal, 8).padding(.vertical, 3).background(Capsule().fill(tint))
    }
}

private struct ThisMacCard: View {
    @EnvironmentObject var state: AppState
    @State private var copied = false

    var body: some View {
        Card {
            HStack(spacing: 10) {
                OptionBadge(text: "OPTION A", tint: .blue)
                Image(systemName: "desktopcomputer").foregroundStyle(.blue)
                Text("This Mac stays at home").font(.headline)
                if state.helperRunning {
                    OptionBadge(text: "RUNNING", tint: .green)
                }
            }
            Text("Good if you have a Mac mini or iMac at home and take a different computer (or a friend's) with you. While the helper runs, this Mac won't idle-sleep. Keep it plugged in and leave the app open.")
                .foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)

            HStack(spacing: 12) {
                Text("Pairing code").foregroundStyle(.secondary)
                Text(state.helperCode)
                    .font(.system(size: 22, weight: .bold, design: .monospaced))
                    .textSelection(.enabled)
                    .padding(.horizontal, 12).padding(.vertical, 6)
                    .background(RoundedRectangle(cornerRadius: 8).fill(Color.primary.opacity(0.06)))
                Button {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(state.helperCode, forType: .string)
                    copied = true
                } label: { Label(copied ? "Copied" : "Copy", systemImage: copied ? "checkmark" : "doc.on.doc") }
                Button("New code") { state.helperCode = AppState.newCode(); copied = false }
                    .disabled(state.helperRunning)
                Spacer()
                if state.helperRunning {
                    Button(role: .destructive) { state.stopHelper() } label: { Label("Stop helper", systemImage: "stop.fill") }
                        .controlSize(.large)
                } else {
                    Button { state.startHelper() } label: { Label("Start helper", systemImage: "play.fill") }
                        .buttonStyle(.borderedProminent).tint(.teal).controlSize(.large)
                        .disabled(state.pythonMissing)
                }
            }

            if !state.helperLog.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(state.helperLog.suffix(8)) { line in
                        HStack(alignment: .top, spacing: 8) {
                            Circle().fill(line.level.color).frame(width: 7, height: 7).padding(.top, 5)
                            Text(line.time, style: .time).font(.caption.monospacedDigit()).foregroundStyle(.tertiary)
                            Text(line.text).font(.callout).fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
                .padding(10)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(RoundedRectangle(cornerRadius: 8).fill(Color.primary.opacity(0.04)))
            }
        }
    }
}

private struct RaspberryPiCard: View {
    @EnvironmentObject var state: AppState
    @State private var savedTo: URL?
    @State private var saveError: String?

    var body: some View {
        Card {
            HStack(spacing: 10) {
                OptionBadge(text: "OPTION B", tint: .pink)
                Image(systemName: "cpu").foregroundStyle(.pink)
                Text("Raspberry Pi, NAS or any Linux box").font(.headline)
            }
            Text("Best if you take this Mac with you. A Raspberry Pi uses about 3 W, runs the helper as a background service and restarts it automatically. Any Pi with Raspberry Pi OS works, as does a Debian/Ubuntu machine or a NAS with Python 3.")
                .foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)

            ChecklistItem(text: "Click **Save Raspberry Pi kit…**: it creates a `ps-remote-helper` folder with the checker, an installer and your pairing code.", symbol: "1.circle.fill")
            ChecklistItem(text: "Copy the folder to the Pi, e.g. in Terminal:", symbol: "2.circle.fill")
            CommandBox(command: "scp -r ps-remote-helper pi@raspberrypi.local:~")
            ChecklistItem(text: "On the Pi, install it as a service (it then starts on every boot):", symbol: "3.circle.fill")
            CommandBox(command: "ssh pi@raspberrypi.local 'sudo ~/ps-remote-helper/install.sh'")
            ChecklistItem(text: "Check it's running: `ssh pi@raspberrypi.local journalctl -u ps-remote-helper -f`. You should see \"Keep this running at home…\" and later the live tests.", symbol: "4.circle.fill")

            HStack {
                Button { saveKit() } label: { Label("Save Raspberry Pi kit…", systemImage: "square.and.arrow.down") }
                    .buttonStyle(.borderedProminent).tint(.pink).controlSize(.large)
                if let savedTo {
                    Label("Saved to \(savedTo.path)", systemImage: "checkmark.circle.fill")
                        .font(.callout).foregroundStyle(.green).lineLimit(1).truncationMode(.middle)
                }
                if let saveError {
                    Label(saveError, systemImage: "xmark.octagon.fill").font(.callout).foregroundStyle(.red)
                }
            }
            .padding(.top, 4)
            Text("Uses the same pairing code as Option A (\(state.helperCode)). Only run the helper in one place at a time.")
                .font(.caption).foregroundStyle(.tertiary)
        }
    }

    private func saveKit() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.prompt = "Save kit here"
        panel.message = "Choose where to create the ps-remote-helper folder"
        guard panel.runModal() == .OK, let base = panel.url else { return }
        do {
            savedTo = try HelperKit.write(to: base, code: state.helperCode)
            saveError = nil
            NSWorkspace.shared.activateFileViewerSelecting([savedTo!])
        } catch {
            saveError = error.localizedDescription
        }
    }
}

struct CommandBox: View {
    let command: String
    @State private var copied = false

    var body: some View {
        HStack {
            Text(command).font(.system(.callout, design: .monospaced)).textSelection(.enabled)
            Spacer()
            Button {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(command, forType: .string)
                copied = true
            } label: { Image(systemName: copied ? "checkmark" : "doc.on.doc") }
            .buttonStyle(.borderless)
            .help("Copy command")
        }
        .padding(10)
        .background(RoundedRectangle(cornerRadius: 8).fill(Color.primary.opacity(0.06)))
        .padding(.leading, 28)
    }
}

enum HelperKit {
    /// Creates `<base>/ps-remote-helper/` with the checker package, installer and pairing code.
    static func write(to base: URL, code: String) throws -> URL {
        let fm = FileManager.default
        let kit = base.appendingPathComponent("ps-remote-helper", isDirectory: true)
        if fm.fileExists(atPath: kit.path) { try fm.removeItem(at: kit) }
        try fm.createDirectory(at: kit, withIntermediateDirectories: true)

        let engine = URL(fileURLWithPath: Engine.enginePath)
        try fm.copyItem(at: engine.appendingPathComponent("ps_remote_checker"),
                        to: kit.appendingPathComponent("ps_remote_checker"))
        for cache in (try? fm.subpathsOfDirectory(atPath: kit.path)) ?? [] where cache.hasSuffix("__pycache__") {
            try? fm.removeItem(at: kit.appendingPathComponent(cache))
        }
        guard let installer = Bundle.main.url(forResource: "install", withExtension: "sh", subdirectory: "rpi")
                ?? [engine.appendingPathComponent("deploy/rpi/install.sh")].first(where: { fm.fileExists(atPath: $0.path) })
        else { throw EngineError.failed("install.sh is missing from the app bundle") }
        let installDest = kit.appendingPathComponent("install.sh")
        try fm.copyItem(at: installer, to: installDest)
        try fm.setAttributes([.posixPermissions: 0o755], ofItemAtPath: installDest.path)
        try (code + "\n").write(to: kit.appendingPathComponent("pairing-code.txt"), atomically: true, encoding: .utf8)
        let readme = """
        PS Remote Checker – home helper kit
        ===================================
        Pairing code: \(code)

        1. Copy this folder to the Raspberry Pi (same router as the PS5):
             scp -r ps-remote-helper pi@raspberrypi.local:~
        2. Install it as a service on the Pi:
             ssh pi@raspberrypi.local 'sudo ~/ps-remote-helper/install.sh'
        3. Watch it:  journalctl -u ps-remote-helper -f

        Run it once without installing:   python3 -m ps_remote_checker helper --code \(code)
        Away from home, enter the pairing code on the app's Away page,
        or run:  python3 -m ps_remote_checker remote --pair \(code)
        """
        try readme.write(to: kit.appendingPathComponent("README.txt"), atomically: true, encoding: .utf8)
        return kit
    }
}
