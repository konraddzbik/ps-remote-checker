// Dev tool: renders each page of the app offscreen to PNGs (no screen-recording permission needed).
// Build: swiftc -swift-version 5 -parse-as-library Tools/Snapshot.swift $(ls Sources/*.swift | grep -v App.swift) -o build/snapshot
import AppKit
import SwiftUI

@main
struct Snapshot {
    @MainActor static func main() {
        let app = NSApplication.shared
        app.setActivationPolicy(.prohibited)
        let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "."
        let state = AppState()
        for dark in [false, true] {
            for section in Section.allCases {
                state.section = section
                let view = ContentView().environmentObject(state)
                let host = NSHostingView(rootView: view)
                let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1180, height: (section == .home || section == .helper) ? 2400 : 1500),
                                      styleMask: [.titled], backing: .buffered, defer: false)
                window.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
                window.contentView = host
                host.layoutSubtreeIfNeeded()
                RunLoop.main.run(until: Date().addingTimeInterval(0.6))
                let rep = host.bitmapImageRepForCachingDisplay(in: host.bounds)!
                host.cacheDisplay(in: host.bounds, to: rep)
                let name = "\(out)/\(section.rawValue)\(dark ? "-dark" : "").png"
                try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: name))
                print(name)
            }
        }
    }
}
