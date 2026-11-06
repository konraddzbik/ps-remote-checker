import SwiftUI

// JSON produced by `python3 -m ps_remote_checker --json ...` (decoded with convertFromSnakeCase).

enum Level: String, Codable {
    case ok, warn, fail

    var color: Color {
        switch self {
        case .ok: return .green
        case .warn: return .orange
        case .fail: return .red
        }
    }

    var symbol: String {
        switch self {
        case .ok: return "checkmark.circle.fill"
        case .warn: return "exclamationmark.triangle.fill"
        case .fail: return "xmark.octagon.fill"
        }
    }
}

struct Finding: Codable, Identifiable {
    let id = UUID()
    let level: Level
    let area: String
    let message: String
    let fix: String?

    private enum CodingKeys: String, CodingKey { case level, area, message, fix }
}

struct Evaluation: Codable {
    let overall: Level
    let findings: [Finding]
}

struct PairEvaluation: Codable {
    let overall: Level
    let findings: [Finding]
    let home: Evaluation
    let remote: Evaluation
}

struct NatInfo: Codable {
    let type: String?
    let publicIp: String?
    let portPreserved: Bool?
    let multiplePublicIps: Bool?

    var playStationType: String {
        switch type {
        case "open": return "Type 1"
        case "eim": return "Type 2"
        case "symmetric": return "Type 3"
        case "udp_blocked": return "Blocked"
        default: return "Unknown"
        }
    }

    var description: String {
        switch type {
        case "open": return "Open, no NAT"
        case "eim": return "Cone NAT (hole punching friendly)"
        case "symmetric": return "Symmetric NAT (strict)"
        case "udp_blocked": return "UDP traffic is blocked"
        case "dns_failed": return "No DNS / no internet"
        default: return "Could not determine"
        }
    }

    var level: Level {
        switch type {
        case "open", "eim": return .ok
        case "udp_blocked", "dns_failed": return .fail
        default: return .warn
        }
    }
}

struct Latency: Codable {
    let sent: Int?
    let received: Int?
    let lossPct: Double?
    let avgMs: Double?
    let jitterMs: Double?
}

struct Speed: Codable {
    let downMbps: Double?
    let upMbps: Double?
    let error: String?
}

struct PS5Info: Codable {
    let found: Bool?
    let ip: String?
    let status: String?
    let name: String?
    let systemVersion: String?
    let port9295Open: Bool?
}

struct PortMapping: Codable {
    let `protocol`: String?
    let externalPort: Int?
}

struct UPnPInfo: Codable {
    let found: Bool?
    let device: String?
    let externalIp: String?
    let cgnat: Bool?
    let doubleNat: Bool?
    let ps5Mappings: [PortMapping]?
}

struct InternetInfo: Codable {
    let internet: Bool?
    let captivePortal: Bool?
}

struct PSNInfo: Codable {
    let reachable: Bool?
}

struct LiveRTT: Codable {
    let received: Int?
    let avgMs: Double?
    let jitterMs: Double?
    let lossPct: Double?
}

struct LiveStream: Codable {
    let targetMbps: Double?
    let receivedMbps: Double?
    let lossPct: Double?
    let error: String?
}

struct LiveTest: Codable {
    let ran: Bool?
    let relayOk: Bool?
    let helperFound: Bool?
    let connected: Bool?
    let path: String?
    let error: String?
    let punchMs: Double?
    let rtt: LiveRTT?
    let stream: LiveStream?

    var summary: (value: String, detail: String, level: Level) {
        if relayOk != true { return ("Not started", error ?? "Relay unreachable", .warn) }
        if helperFound != true { return ("Helper offline", "No answer from the home helper", .warn) }
        if let error { return ("Failed", error, .fail) }
        if connected != true { return ("No connection", "Direct UDP path could not be opened", .fail) }
        if path == "lan" { return ("Local only", "Ran at home, test again away", .warn) }
        return ("Verified", "Direct path opened in \(Int(punchMs ?? 0)) ms", .ok)
    }
}

struct Report: Codable {
    let kind: String
    let timestamp: String?
    let localIp: String?
    let gateway: String?
    let nat: NatInfo?
    let latency: Latency?
    let speed: Speed?
    let ps5: PS5Info?
    let upnp: UPnPInfo?
    let internet: InternetInfo?
    let psn: PSNInfo?
    let live: LiveTest?

    var date: Date? {
        guard let timestamp else { return nil }
        return ISO8601DateFormatter().date(from: timestamp)
    }
}

struct HomeOutput: Codable {
    let report: Report
    let evaluation: Evaluation
    let code: String
}

struct RemoteOutput: Codable {
    let report: Report
    let evaluation: Evaluation
    let pair: PairEvaluation?
    let homeFromHelper: Bool?
}

struct ErrorOutput: Codable {
    let kind: String
    let error: String?
}

extension JSONDecoder {
    static var checker: JSONDecoder {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }
}
