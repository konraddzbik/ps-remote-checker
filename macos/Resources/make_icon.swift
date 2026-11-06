// Renders the app icon (gradient squircle + controller + signal waves) to a .iconset folder.
import AppKit

let out = CommandLine.arguments[1]
try? FileManager.default.createDirectory(atPath: out, withIntermediateDirectories: true)

func render(_ size: Int) -> Data {
    let s = CGFloat(size)
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size, bitsPerSample: 8,
                               samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                               bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    let inset = s * 0.1
    let rect = NSRect(x: inset, y: inset, width: s - 2 * inset, height: s - 2 * inset)
    let path = NSBezierPath(roundedRect: rect, xRadius: rect.width * 0.225, yRadius: rect.width * 0.225)
    NSGradient(colors: [NSColor(red: 0.16, green: 0.32, blue: 0.95, alpha: 1),
                        NSColor(red: 0.50, green: 0.20, blue: 0.90, alpha: 1)])!.draw(in: path, angle: -60)
    let cfg = NSImage.SymbolConfiguration(pointSize: s * 0.36, weight: .semibold)
        .applying(.init(paletteColors: [.white]))
    if let pad = NSImage(systemSymbolName: "gamecontroller.fill", accessibilityDescription: nil)?.withSymbolConfiguration(cfg) {
        let w = pad.size.width, h = pad.size.height
        pad.draw(in: NSRect(x: (s - w) / 2, y: s * 0.27, width: w, height: h))
    }
    let cfg2 = NSImage.SymbolConfiguration(pointSize: s * 0.17, weight: .bold)
        .applying(.init(paletteColors: [NSColor.white.withAlphaComponent(0.85)]))
    if let waves = NSImage(systemSymbolName: "wifi", accessibilityDescription: nil)?.withSymbolConfiguration(cfg2) {
        let w = waves.size.width, h = waves.size.height
        waves.draw(in: NSRect(x: (s - w) / 2, y: s * 0.60, width: w, height: h))
    }
    NSGraphicsContext.restoreGraphicsState()
    return rep.representation(using: .png, properties: [:])!
}

for base in [16, 32, 128, 256, 512] {
    try! render(base).write(to: URL(fileURLWithPath: "\(out)/icon_\(base)x\(base).png"))
    try! render(base * 2).write(to: URL(fileURLWithPath: "\(out)/icon_\(base)x\(base)@2x.png"))
}
