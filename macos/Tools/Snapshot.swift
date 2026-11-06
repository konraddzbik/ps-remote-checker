// Dev tool: renders app pages offscreen to PNGs (no screen-recording permission needed).
// Build: swiftc -swift-version 5 -parse-as-library Tools/Snapshot.swift $(ls Sources/*.swift | grep -v App.swift) -o build/snapshot
//
//   build/snapshot <out_dir>            every page, light + dark (design review)
//   SNAP_MEDIA=1 build/snapshot <out>   README media frames (use PSRC_STATE_DIR with demo data)
import AppKit
import SwiftUI

@MainActor
func render(_ state: AppState, _ section: Section, dark: Bool, size: NSSize, to path: String,
            configure: (AppState) -> Void = { _ in }) {
    state.section = section
    configure(state)
    let host = NSHostingView(rootView: ContentView().environmentObject(state))
    let window = NSWindow(contentRect: NSRect(origin: .zero, size: size), styleMask: [.titled],
                          backing: .buffered, defer: false)
    window.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
    window.contentView = host
    host.layoutSubtreeIfNeeded()
    RunLoop.main.run(until: Date().addingTimeInterval(0.6))
    let rep = host.bitmapImageRepForCachingDisplay(in: host.bounds)!
    host.cacheDisplay(in: host.bounds, to: rep)
    try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: path))
    print(path)
}

@main
struct Snapshot {
    @MainActor static func main() {
        NSApplication.shared.setActivationPolicy(.prohibited)
        let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "."
        let state = AppState()

        guard ProcessInfo.processInfo.environment["SNAP_MEDIA"] != nil else {
            for dark in [false, true] {
                for s in Section.allCases {
                    let h: CGFloat = (s == .home || s == .helper) ? 2400 : 1500
                    render(state, s, dark: dark, size: NSSize(width: 1180, height: h),
                           to: "\(out)/\(s.rawValue)\(dark ? "-dark" : "").png")
                }
            }
            return
        }

        let view = NSSize(width: 1280, height: 800)
        let tall = NSSize(width: 1280, height: 2300)
        let savedRemote = state.remote
        // Page tour (light + dark)
        for dark in [false, true] {
            for s in Section.allCases {
                render(state, s, dark: dark, size: view, to: "\(out)/tour-\(s.rawValue)\(dark ? "-dark" : "").png")
            }
        }
        // Away check while running
        let steps = ["checking internet / captive portal", "detecting NAT type with STUN",
                     "opening a direct connection to home (UDP hole punching)",
                     "streaming test video traffic from home (15 Mbps for 6 s)"]
        for (i, step) in steps.enumerated() {
            render(state, .away, dark: false, size: view, to: "\(out)/away-run-\(i).png") { st in
                st.remote = nil
                st.running = .away
                st.step = step
            }
        }
        state.running = nil
        state.remote = savedRemote
        render(state, .away, dark: false, size: tall, to: "\(out)/away-tall.png")
        render(state, .away, dark: true, size: tall, to: "\(out)/away-tall-dark.png")
        render(state, .home, dark: false, size: tall, to: "\(out)/home-tall.png")
    }
}
