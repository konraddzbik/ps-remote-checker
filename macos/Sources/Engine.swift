import Foundation

/// Runs the bundled Python checker (Contents/Resources/ps_remote_checker) and streams its progress.
enum EngineError: LocalizedError {
    case pythonNotFound
    case failed(String)

    var errorDescription: String? {
        switch self {
        case .pythonNotFound:
            return "Python 3 was not found. Install it with Homebrew (`brew install python`) or from python.org, "
                + "or install the Xcode Command Line Tools (`xcode-select --install`)."
        case .failed(let msg):
            return msg
        }
    }
}

enum Engine {
    static let pythonCandidates = [
        "/opt/homebrew/bin/python3",
        "/usr/local/bin/python3",
        "/Library/Frameworks/Python.framework/Versions/Current/bin/python3",
        "/usr/bin/python3",
    ]

    static func findPython() -> String? {
        let fm = FileManager.default
        for path in pythonCandidates where fm.isExecutableFile(atPath: path) {
            // /usr/bin/python3 is only a stub until the Command Line Tools / Xcode are installed.
            if path == "/usr/bin/python3" {
                let hasTools = fm.fileExists(atPath: "/Library/Developer/CommandLineTools/usr/bin/python3")
                    || fm.fileExists(atPath: "/Applications/Xcode.app/Contents/Developer/usr/bin/python3")
                if !hasTools { continue }
            }
            return path
        }
        return nil
    }

    /// Directory that contains the `ps_remote_checker` package.
    static var enginePath: String {
        if let res = Bundle.main.resourcePath,
           FileManager.default.fileExists(atPath: res + "/ps_remote_checker/__init__.py") {
            return res
        }
        // Running unbundled during development: repo root is two levels above the binary's folder.
        return FileManager.default.currentDirectoryPath
    }

    /// Run the checker with `--json` and decode the final stdout line as `T`.
    static func run<T: Decodable>(_ args: [String], as type: T.Type,
                                  progress: @escaping @MainActor (String) -> Void) async throws -> (T, Data) {
        guard let python = findPython() else { throw EngineError.pythonNotFound }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = ["-m", "ps_remote_checker", "--json"] + args
        process.currentDirectoryURL = URL(fileURLWithPath: enginePath)
        var env = ProcessInfo.processInfo.environment
        env["PYTHONPATH"] = enginePath
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["NO_COLOR"] = "1"
        process.environment = env

        let out = Pipe(), err = Pipe()
        process.standardOutput = out
        process.standardError = err

        let stdoutBuffer = LockedData()
        let stderrBuffer = LockedData()
        out.fileHandleForReading.readabilityHandler = { h in stdoutBuffer.append(h.availableData) }
        err.fileHandleForReading.readabilityHandler = { h in
            let chunk = h.availableData
            stderrBuffer.append(chunk)
            let text = String(decoding: chunk, as: UTF8.self)
            for line in text.split(separator: "\n") where line.hasPrefix("STEP\t") {
                let msg = String(line.dropFirst(5))
                Task { @MainActor in progress(msg) }
            }
        }

        try await withCheckedThrowingContinuation { (cont: CheckedContinuation<Void, Error>) in
            process.terminationHandler = { _ in cont.resume() }
            do { try process.run() } catch {
                process.terminationHandler = nil
                cont.resume(throwing: error)
            }
        }
        out.fileHandleForReading.readabilityHandler = nil
        err.fileHandleForReading.readabilityHandler = nil
        stdoutBuffer.append(out.fileHandleForReading.readDataToEndOfFile())
        stderrBuffer.append(err.fileHandleForReading.readDataToEndOfFile())

        let data = stdoutBuffer.data
        let lastLine = data.split(separator: UInt8(ascii: "\n")).last.map { Data($0) } ?? Data()
        if let e = try? JSONDecoder.checker.decode(ErrorOutput.self, from: lastLine),
           e.kind == "error" {
            throw EngineError.failed(e.error ?? "Unknown error")
        }
        do {
            return (try JSONDecoder.checker.decode(T.self, from: lastLine), lastLine)
        } catch {
            let errText = String(decoding: stderrBuffer.data, as: UTF8.self)
                .split(separator: "\n").filter { !$0.hasPrefix("STEP\t") }.suffix(6).joined(separator: "\n")
            throw EngineError.failed("The check did not finish (exit \(process.terminationStatus)).\n\(errText)")
        }
    }
}

extension Engine {
    /// Start the long-running home helper. Each stdout line is a JSON event.
    static func startHelper(_ args: [String],
                            onEvent: @escaping @MainActor ([String: Any]) -> Void,
                            onExit: @escaping @MainActor (Int32, String) -> Void) throws -> Process {
        guard let python = findPython() else { throw EngineError.pythonNotFound }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = ["-u", "-m", "ps_remote_checker", "--json"] + args
        process.currentDirectoryURL = URL(fileURLWithPath: enginePath)
        var env = ProcessInfo.processInfo.environment
        env["PYTHONPATH"] = enginePath
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        process.environment = env
        let out = Pipe(), err = Pipe()
        process.standardOutput = out
        process.standardError = err
        let pending = LockedData()
        let errTail = LockedData()
        out.fileHandleForReading.readabilityHandler = { h in
            pending.append(h.availableData)
            for line in pending.takeLines() {
                if let obj = try? JSONSerialization.jsonObject(with: line) as? [String: Any] {
                    Task { @MainActor in onEvent(obj) }
                }
            }
        }
        err.fileHandleForReading.readabilityHandler = { h in errTail.append(h.availableData) }
        process.terminationHandler = { p in
            out.fileHandleForReading.readabilityHandler = nil
            err.fileHandleForReading.readabilityHandler = nil
            let tail = String(decoding: errTail.data, as: UTF8.self)
                .split(separator: "\n").filter { !$0.hasPrefix("STEP\t") }.suffix(3).joined(separator: "\n")
            let status = p.terminationStatus
            Task { @MainActor in onExit(status, tail) }
        }
        try process.run()
        return process
    }
}

final class LockedData: @unchecked Sendable {
    private var storage = Data()
    private let lock = NSLock()
    func append(_ d: Data) { lock.lock(); storage.append(d); lock.unlock() }
    var data: Data { lock.lock(); defer { lock.unlock() }; return storage }

    /// Remove and return complete newline-terminated lines.
    func takeLines() -> [Data] {
        lock.lock(); defer { lock.unlock() }
        var lines = [Data]()
        while let nl = storage.firstIndex(of: UInt8(ascii: "\n")) {
            lines.append(storage[storage.startIndex..<nl])
            storage.removeSubrange(storage.startIndex...nl)
        }
        return lines
    }
}
