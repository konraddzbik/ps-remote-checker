import AppKit
import SwiftUI

enum Section: String, CaseIterable, Identifiable {
    case start, home, away, helper, help
    var id: String { rawValue }

    var title: String {
        switch self {
        case .start: return "Start here"
        case .home: return "1 · Home (PS5)"
        case .away: return "2 · Away (PS Portal)"
        case .helper: return "Home helper (live test)"
        case .help: return "Fixes & ports"
        }
    }

    var symbol: String {
        switch self {
        case .start: return "sparkles"
        case .home: return "house.fill"
        case .away: return "airplane"
        case .helper: return "antenna.radiowaves.left.and.right"
        case .help: return "wrench.and.screwdriver.fill"
        }
    }
}

struct HelperLogLine: Identifiable {
    let id = UUID()
    let time = Date()
    let text: String
    let level: Level
}

@MainActor
final class AppState: ObservableObject {
    // Home helper (live test, home side)
    @Published var helperRunning = false
    @Published var helperCode: String = UserDefaults.standard.string(forKey: "helperCode") ?? AppState.newCode() {
        didSet { UserDefaults.standard.set(helperCode, forKey: "helperCode") }
    }
    @Published var helperLog: [HelperLogLine] = []
    private var helperProcess: Process?
    private var sleepActivity: NSObjectProtocol?

    // Live test (away side)
    @Published var pairCode: String = UserDefaults.standard.string(forKey: "pairCode") ?? "" {
        didSet { UserDefaults.standard.set(pairCode, forKey: "pairCode") }
    }

    @Published var section: Section? = .start
    @Published var home: HomeOutput?
    @Published var remote: RemoteOutput?
    @Published var pastedHomeCode: String?          // home check done on another computer
    @Published var running: Section?
    @Published var step = ""
    @Published var error: String?
    @Published var ps5IP = ""
    @Published var speedTest = true

    private let dir: URL = {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        let url = base.appendingPathComponent("PS Remote Checker", isDirectory: true)
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }()
    private var homeReportURL: URL { dir.appendingPathComponent("home-report.json") }
    private var homeResultURL: URL { dir.appendingPathComponent("home-result.json") }
    private var remoteResultURL: URL { dir.appendingPathComponent("remote-result.json") }
    private var homeCodeURL: URL { dir.appendingPathComponent("pasted-home-code.txt") }

    init() {
        if let d = try? Data(contentsOf: homeResultURL) { home = try? JSONDecoder.checker.decode(HomeOutput.self, from: d) }
        if let d = try? Data(contentsOf: remoteResultURL) { remote = try? JSONDecoder.checker.decode(RemoteOutput.self, from: d) }
        pastedHomeCode = try? String(contentsOf: homeCodeURL, encoding: .utf8)
        if home != nil || remote != nil { section = remote != nil ? .away : .home }
        UserDefaults.standard.set(helperCode, forKey: "helperCode")
        NotificationCenter.default.addObserver(forName: NSApplication.willTerminateNotification, object: nil,
                                               queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.helperProcess?.terminate() }
        }
    }

    static func newCode() -> String {
        let alphabet = Array("ABCDEFGHJKMNPQRSTUVWXYZ23456789")
        let raw = (0..<12).map { _ in String(alphabet.randomElement()!) }.joined()
        return stride(from: 0, to: 12, by: 4).map { i in
            String(raw[raw.index(raw.startIndex, offsetBy: i)..<raw.index(raw.startIndex, offsetBy: i + 4)])
        }.joined(separator: "-")
    }

    static func isValidCode(_ code: String) -> Bool {
        let raw = code.uppercased().filter { $0.isLetter || $0.isNumber }
        return raw.count == 12 && raw.allSatisfy { "ABCDEFGHJKMNPQRSTUVWXYZ23456789".contains($0) }
    }

    // MARK: home helper

    func startHelper() {
        guard helperProcess == nil else { return }
        var args = ["helper", "--code", helperCode]
        let ip = ps5IP.trimmingCharacters(in: .whitespaces)
        if !ip.isEmpty { args += ["--ps5-ip", ip] }
        if !speedTest { args.append("--no-speed") }
        helperLog = []
        do {
            helperProcess = try Engine.startHelper(args, onEvent: { [weak self] in self?.helperEvent($0) },
                                                   onExit: { [weak self] status, tail in self?.helperExited(status, tail) })
            helperRunning = true
            sleepActivity = ProcessInfo.processInfo.beginActivity(
                options: [.idleSystemSleepDisabled, .userInitiated],
                reason: "Home helper is waiting for live tests")
            logHelper("Starting helper…", .ok)
        } catch {
            logHelper(error.localizedDescription, .fail)
        }
    }

    func stopHelper() {
        helperProcess?.terminate()
    }

    private func helperExited(_ status: Int32, _ tail: String) {
        helperProcess = nil
        helperRunning = false
        if let a = sleepActivity { ProcessInfo.processInfo.endActivity(a); sleepActivity = nil }
        if status == 0 || status == 15 || status == -15 {
            logHelper("Helper stopped.", .warn)
        } else {
            logHelper("Helper stopped unexpectedly (exit \(status)). \(tail)", .fail)
        }
    }

    private func logHelper(_ text: String, _ level: Level) {
        helperLog.append(HelperLogLine(text: text, level: level))
        if helperLog.count > 50 { helperLog.removeFirst(helperLog.count - 50) }
    }

    private func helperEvent(_ e: [String: Any]) {
        let s = { (k: String) in (e[k] as? String) ?? "" }
        switch s("event") {
        case "ready": logHelper("Waiting for live tests (relay \(s("relay")))", .ok)
        case "home_check_started": logHelper("Running the home self-check…", .ok)
        case "home_check_done":
            let lvl = Level(rawValue: s("overall")) ?? .warn
            logHelper("Home self-check: \(lvl == .ok ? "ready" : lvl == .warn ? "needs attention" : "problem")", lvl)
        case "home_check_failed": logHelper("Home self-check failed: \(s("error"))", .warn)
        case "relay_error": logHelper("Relay not reachable: \(s("error"))", .warn)
        case "session_start": logHelper("Live test requested from \(s("from"))", .ok)
        case "session_connected": logHelper("Connected to \(s("peer"))", .ok)
        case "session_end":
            let ok = (e["connected"] as? Bool) == true
            logHelper(ok ? "Live test finished: connected" : "Live test finished: no direct connection"
                      + (s("error").isEmpty ? "" : " (\(s("error")))"), ok ? .ok : .fail)
        default: break
        }
    }

    var pythonMissing: Bool { Engine.findPython() == nil }

    /// What the away check compares against: the pasted code wins over the local home run.
    var homeReference: String? {
        if let code = pastedHomeCode, !code.isEmpty { return code }
        return FileManager.default.fileExists(atPath: homeReportURL.path) && home != nil ? homeReportURL.path : nil
    }

    func runHome() {
        var args = ["home", "-o", homeReportURL.path]
        let ip = ps5IP.trimmingCharacters(in: .whitespaces)
        if !ip.isEmpty { args += ["--ps5-ip", ip] }
        if !speedTest { args.append("--no-speed") }
        run(.home) { [self] in
            let (out, raw) = try await Engine.run(args, as: HomeOutput.self, progress: { self.step = $0 })
            try? raw.write(to: homeResultURL)
            home = out
            // A fresh local home check replaces a code pasted earlier.
            clearPastedCode()
        }
    }

    func runAway() {
        var args = ["remote"]
        if let ref = homeReference { args += ["--home", ref] }
        if AppState.isValidCode(pairCode) { args += ["--pair", pairCode] }
        if !speedTest { args.append("--no-speed") }
        run(.away) { [self] in
            let (out, raw) = try await Engine.run(args, as: RemoteOutput.self, progress: { self.step = $0 })
            try? raw.write(to: remoteResultURL)
            remote = out
        }
    }

    private func run(_ which: Section, _ body: @escaping () async throws -> Void) {
        guard running == nil else { return }
        running = which
        step = "Starting…"
        error = nil
        Task {
            do { try await body() } catch { self.error = error.localizedDescription }
            running = nil
            step = ""
        }
    }

    func setPastedCode(_ code: String) {
        let c = code.trimmingCharacters(in: .whitespacesAndNewlines)
        pastedHomeCode = c
        try? c.write(to: homeCodeURL, atomically: true, encoding: .utf8)
    }

    func clearPastedCode() {
        pastedHomeCode = nil
        try? FileManager.default.removeItem(at: homeCodeURL)
    }

    func copyHomeCode() {
        guard let code = home?.code else { return }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(code, forType: .string)
    }

    func status(for s: Section) -> Level? {
        switch s {
        case .home: return home?.evaluation.overall
        case .away: return remote?.pair?.overall ?? remote?.evaluation.overall
        case .helper: return helperRunning ? .ok : nil
        default: return nil
        }
    }
}
