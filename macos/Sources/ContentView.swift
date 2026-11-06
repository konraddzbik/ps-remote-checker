import SwiftUI

struct ContentView: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        NavigationSplitView {
            List(selection: $state.section) {
                ForEach(Section.allCases) { s in
                    NavigationLink(value: s) {
                        HStack {
                            Label(s.title, systemImage: s.symbol)
                            Spacer()
                            if state.running == s {
                                ProgressView().controlSize(.mini)
                            } else if let level = state.status(for: s) {
                                Image(systemName: level.symbol).foregroundStyle(level.color)
                            }
                        }
                    }
                }
            }
            .navigationSplitViewColumnWidth(min: 210, ideal: 230)
            .safeAreaInset(edge: .bottom) {
                Text("Checks run on this Mac. No account data or results leave it.")
                    .font(.caption2).foregroundStyle(.tertiary).padding(12)
            }
        } detail: {
            Group {
            switch state.section ?? .start {
            case .start: StartView()
            case .home: HomeView()
            case .away: AwayView()
            case .helper: HelperView()
            case .help: HelpView()
            }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color(nsColor: .windowBackgroundColor))
        }
    }
}
