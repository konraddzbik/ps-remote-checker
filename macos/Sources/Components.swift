import SwiftUI

struct Card<Content: View>: View {
    var padding: CGFloat = 16
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 10) { content }
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(Color(nsColor: .controlBackgroundColor)))
            .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous)
                .strokeBorder(Color.primary.opacity(0.08)))
    }
}

struct PageHeader: View {
    let symbol: String
    let title: String
    let subtitle: String
    var tint: Color = .blue

    var body: some View {
        HStack(alignment: .center, spacing: 16) {
            Image(systemName: symbol)
                .font(.system(size: 26, weight: .semibold))
                .foregroundStyle(.white)
                .frame(width: 56, height: 56)
                .background(RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .fill(LinearGradient(colors: [tint, tint.opacity(0.65)], startPoint: .topLeading, endPoint: .bottomTrailing)))
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.system(size: 26, weight: .bold))
                Text(subtitle).foregroundStyle(.secondary)
            }
        }
    }
}

struct VerdictBanner: View {
    let level: Level
    let title: String
    let detail: String

    var body: some View {
        HStack(spacing: 16) {
            Image(systemName: level.symbol)
                .font(.system(size: 38, weight: .semibold))
                .foregroundStyle(.white)
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.title2.bold()).foregroundStyle(.white)
                Text(detail).foregroundStyle(.white.opacity(0.9))
            }
            Spacer()
        }
        .padding(20)
        .background(RoundedRectangle(cornerRadius: 16, style: .continuous)
            .fill(LinearGradient(colors: [level.color, level.color.opacity(0.75)],
                                 startPoint: .topLeading, endPoint: .bottomTrailing)))
        .shadow(color: .black.opacity(0.12), radius: 4, y: 2)
    }
}

struct MetricTile: View {
    let symbol: String
    let title: String
    let value: String
    var detail: String? = nil
    var level: Level? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Image(systemName: symbol).foregroundStyle(level?.color ?? .accentColor)
                Text(title).font(.caption.weight(.semibold)).foregroundStyle(.secondary).textCase(.uppercase)
                Spacer()
                if let level { Circle().fill(level.color).frame(width: 8, height: 8) }
            }
            Text(value).font(.system(size: 20, weight: .semibold, design: .rounded))
                .lineLimit(1).minimumScaleFactor(0.6)
            if let detail {
                Text(detail).font(.caption).foregroundStyle(.secondary).lineLimit(2)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, minHeight: 96, alignment: .topLeading)
        .background(RoundedRectangle(cornerRadius: 12, style: .continuous)
            .fill(Color(nsColor: .controlBackgroundColor)))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous)
            .strokeBorder((level?.color ?? .primary).opacity(level == nil ? 0.08 : 0.35)))
    }
}

struct FindingRow: View {
    let finding: Finding

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: finding.level.symbol)
                .foregroundStyle(finding.level.color)
                .font(.system(size: 17))
                .frame(width: 22)
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    Text(finding.area).font(.caption.weight(.bold)).foregroundStyle(finding.level.color)
                        .padding(.horizontal, 7).padding(.vertical, 2)
                        .background(Capsule().fill(finding.level.color.opacity(0.12)))
                }
                Text(finding.message).fixedSize(horizontal: false, vertical: true)
                if let fix = finding.fix, finding.level != .ok {
                    HStack(alignment: .top, spacing: 6) {
                        Image(systemName: "lightbulb.fill").foregroundStyle(.yellow).font(.caption)
                        Text(fix).font(.callout).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: 8).fill(Color.yellow.opacity(0.08)))
                }
            }
        }
        .padding(.vertical, 6)
        .textSelection(.enabled)
    }
}

struct FindingsCard: View {
    let title: String
    let findings: [Finding]

    var body: some View {
        Card {
            Text(title).font(.headline)
            ForEach(findings.sorted { rank($0.level) < rank($1.level) }) { f in
                FindingRow(finding: f)
                if f.id != findings.last?.id { Divider().opacity(0.5) }
            }
        }
    }

    private func rank(_ l: Level) -> Int { l == .fail ? 0 : l == .warn ? 1 : 2 }
}

struct RunPanel: View {
    @EnvironmentObject var state: AppState
    let section: Section
    let buttonTitle: String
    let action: () -> Void

    var body: some View {
        Card {
            HStack(spacing: 16) {
                if state.running == section {
                    ProgressView().controlSize(.small)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Checking…").font(.headline)
                        Text(state.step.prefix(1).uppercased() + state.step.dropFirst())
                            .font(.callout).foregroundStyle(.secondary)
                    }
                } else {
                    Toggle("Include speed test (~15 s)", isOn: $state.speedTest)
                }
                Spacer()
                Button(action: action) {
                    Label(buttonTitle, systemImage: "play.fill").padding(.horizontal, 8).padding(.vertical, 4)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .disabled(state.running != nil || state.pythonMissing)
            }
            if let err = state.error, state.running == nil {
                Label(err, systemImage: "xmark.octagon.fill").foregroundStyle(.red).textSelection(.enabled)
            }
            if state.pythonMissing {
                Label(EngineError.pythonNotFound.errorDescription ?? "", systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.orange)
            }
        }
    }
}

struct ChecklistItem: View {
    let text: String
    var symbol = "checkmark.circle"

    var body: some View {
        Label { Text(LocalizedStringKey(text)).fixedSize(horizontal: false, vertical: true) } icon: {
            Image(systemName: symbol).foregroundStyle(.blue).frame(width: 20)
        }
    }
}

func formatMbps(_ v: Double?) -> String {
    guard let v else { return "—" }
    return v >= 100 ? String(format: "%.0f Mbps", v) : String(format: "%.1f Mbps", v)
}

func speedLevel(_ v: Double?) -> Level? {
    guard let v else { return nil }
    return v < 5 ? .fail : v < 15 ? .warn : .ok
}

func latencyLevel(_ l: Latency?) -> Level? {
    guard let l, let avg = l.avgMs else { return nil }
    let jitter = l.jitterMs ?? 0, loss = l.lossPct ?? 0
    if loss > 5 || avg > 150 || jitter > 40 { return .fail }
    if loss > 1 || avg > 80 || jitter > 20 { return .warn }
    return .ok
}

let relativeFormatter: RelativeDateTimeFormatter = {
    let f = RelativeDateTimeFormatter()
    f.unitsStyle = .full
    return f
}()
