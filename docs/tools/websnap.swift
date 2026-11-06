// Renders a web page (the Home Assistant add-on panel) to PNG in light and dark mode with WebKit.
//   swiftc docs/tools/websnap.swift -o build/websnap
//   build/websnap <url> <out_dir> [width] [height]
import AppKit
import WebKit

final class Snap: NSObject, WKNavigationDelegate {
    let web: WKWebView
    let out: String
    var done = false
    init(url: URL, out: String, dark: Bool, size: NSSize) {
        self.out = out
        web = WKWebView(frame: NSRect(origin: .zero, size: size))
        web.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
        super.init()
        web.navigationDelegate = self
        web.load(URLRequest(url: url))
    }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) {
            webView.takeSnapshot(with: nil) { img, _ in
                let rep = NSBitmapImageRep(data: img!.tiffRepresentation!)!
                try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: self.out))
                self.done = true
            }
        }
    }
}

let a = CommandLine.arguments
let size = NSSize(width: Double(a.count > 3 ? a[3] : "1100")!, height: Double(a.count > 4 ? a[4] : "1900")!)
NSApplication.shared.setActivationPolicy(.prohibited)
let win = NSWindow(contentRect: NSRect(origin: .zero, size: size), styleMask: [.titled], backing: .buffered, defer: false)
for (dark, name) in [(false, "panel.png"), (true, "panel-dark.png")] {
    let s = Snap(url: URL(string: a[1])!, out: a[2] + "/" + name, dark: dark, size: size)
    win.contentView = s.web
    while !s.done { RunLoop.main.run(until: Date().addingTimeInterval(0.1)) }
    print(name)
}
