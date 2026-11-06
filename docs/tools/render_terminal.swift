// Renders a terminal transcript (JSON from terminal_transcript.py) into PNG frames + an ffmpeg concat list.
//   swiftc docs/tools/render_terminal.swift -o build/render_terminal
//   build/render_terminal transcript.json out_dir
import AppKit

struct Frame: Decodable { let text: String; let duration: Double }

let args = CommandLine.arguments
let frames = try! JSONDecoder().decode([Frame].self, from: Data(contentsOf: URL(fileURLWithPath: args[1])))
let outDir = args[2]
try? FileManager.default.createDirectory(atPath: outDir, withIntermediateDirectories: true)

let size = NSSize(width: 1180, height: 760)   // points; rendered at 2x
let chrome: CGFloat = 38
let pad: CGFloat = 22
let font = NSFont.monospacedSystemFont(ofSize: 13.5, weight: .regular)
let bold = NSFont.monospacedSystemFont(ofSize: 13.5, weight: .bold)
let bg = NSColor(red: 0.07, green: 0.08, blue: 0.10, alpha: 1)
let fg = NSColor(red: 0.86, green: 0.88, blue: 0.91, alpha: 1)
let palette: [Int: NSColor] = [
    31: NSColor(red: 0.97, green: 0.40, blue: 0.40, alpha: 1),
    32: NSColor(red: 0.30, green: 0.85, blue: 0.50, alpha: 1),
    33: NSColor(red: 0.98, green: 0.72, blue: 0.30, alpha: 1),
]

func attributed(_ ansi: String) -> NSAttributedString {
    let out = NSMutableAttributedString()
    var isBold = false, isDim = false
    var color: NSColor = fg
    var i = ansi.startIndex
    var buf = ""
    let para = NSMutableParagraphStyle()
    para.lineSpacing = 3.5
    func flush() {
        guard !buf.isEmpty else { return }
        out.append(NSAttributedString(string: buf, attributes: [
            .font: isBold ? bold : font,
            .foregroundColor: isDim ? fg.withAlphaComponent(0.45) : color,
            .paragraphStyle: para,
        ]))
        buf = ""
    }
    while i < ansi.endIndex {
        if ansi[i] == "\u{1B}", let m = ansi[i...].firstIndex(of: "m") {
            flush()
            let codes = ansi[ansi.index(i, offsetBy: 2)..<m].split(separator: ";").compactMap { Int($0) }
            for c in codes.isEmpty ? [0] : codes {
                switch c {
                case 0: isBold = false; isDim = false; color = fg
                case 1: isBold = true
                case 2: isDim = true
                default: if let p = palette[c] { color = p }
                }
            }
            i = ansi.index(after: m)
        } else {
            buf.append(ansi[i]); i = ansi.index(after: i)
        }
    }
    flush()
    return out
}

var concat = ""
for (n, frame) in frames.enumerated() {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size.width * 2), pixelsHigh: Int(size.height * 2),
                               bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                               colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    rep.size = size
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    // window background + title bar
    NSColor(red: 0.93, green: 0.94, blue: 0.96, alpha: 1).setFill()
    NSRect(origin: .zero, size: size).fill()
    let win = NSBezierPath(roundedRect: NSRect(origin: .zero, size: size), xRadius: 12, yRadius: 12)
    bg.setFill(); win.fill()
    NSColor(red: 0.15, green: 0.16, blue: 0.19, alpha: 1).setFill()
    NSBezierPath(roundedRect: NSRect(x: 0, y: size.height - chrome, width: size.width, height: chrome), xRadius: 12, yRadius: 12).fill()
    NSRect(x: 0, y: size.height - chrome, width: size.width, height: 12).fill()
    for (k, c) in [NSColor.systemRed, .systemYellow, .systemGreen].enumerated() {
        c.setFill()
        NSBezierPath(ovalIn: NSRect(x: 16 + CGFloat(k) * 20, y: size.height - chrome / 2 - 6, width: 12, height: 12)).fill()
    }
    let title = NSAttributedString(string: "ps-remote-check — zsh", attributes: [
        .font: NSFont.systemFont(ofSize: 12.5, weight: .medium), .foregroundColor: NSColor.white.withAlphaComponent(0.6)])
    title.draw(at: NSPoint(x: (size.width - title.size().width) / 2, y: size.height - chrome / 2 - 8))
    // text, anchored to the bottom once it overflows (like a scrolling terminal)
    // U+2714 falls back to the (grey) emoji font; the plain check mark keeps the ANSI colour.
    let text = attributed(frame.text.replacingOccurrences(of: "✔", with: "✓"))
    let width = size.width - pad * 2
    let available = size.height - chrome - pad * 2
    let h = text.boundingRect(with: NSSize(width: width, height: 10_000), options: [.usesLineFragmentOrigin]).height
    let shift = max(0, h - available)
    NSGraphicsContext.current!.cgContext.clip(to: NSRect(x: pad, y: pad, width: width, height: available))
    text.draw(with: NSRect(x: pad, y: pad + available - h + shift, width: width, height: h),
              options: [.usesLineFragmentOrigin])
    NSGraphicsContext.restoreGraphicsState()
    let name = String(format: "term-%03d.png", n)
    try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: "\(outDir)/\(name)"))
    concat += "file '\(name)'\nduration \(frame.duration)\n"
}
if let last = frames.indices.last { concat += String(format: "file 'term-%03d.png'\n", last) }
try! concat.write(toFile: "\(outDir)/concat.txt", atomically: true, encoding: .utf8)
print("\(frames.count) terminal frames")
