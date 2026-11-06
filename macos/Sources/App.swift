import SwiftUI

@main
struct PSRemoteCheckerApp: App {
    @StateObject private var state = AppState()

    var body: some Scene {
        WindowGroup("PS Remote Checker") {
            ContentView()
                .environmentObject(state)
                .frame(minWidth: 900, minHeight: 640)
        }
        .windowToolbarStyle(.unified)
        .commands {
            CommandGroup(replacing: .newItem) {}
            CommandMenu("Check") {
                Button("Run Home Check") { state.section = .home; state.runHome() }
                    .keyboardShortcut("1", modifiers: [.command, .shift])
                    .disabled(state.running != nil)
                Button("Run Away Check") { state.section = .away; state.runAway() }
                    .keyboardShortcut("2", modifiers: [.command, .shift])
                    .disabled(state.running != nil)
            }
        }
    }
}
