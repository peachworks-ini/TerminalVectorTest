import AppKit
import WebKit

final class TerminalVectorViewer: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private let baseURL: URL
    private var windows: [NSWindow] = []

    init(baseURL: URL) {
        self.baseURL = baseURL
        super.init()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        guard let screen = NSScreen.main else {
            NSApp.terminate(nil)
            return
        }

        let screenTop = screen.frame.maxY
        makeWindow(
            path: "/",
            title: "TerminalVector | Control Room",
            contentWidth: 1084,
            contentHeight: 746,
            x: screen.frame.minX + 10,
            top: screenTop - 220
        )
        makeWindow(
            path: "/obs",
            title: "OBS Studio Simulator · Program",
            contentWidth: 560,
            contentHeight: 372,
            x: screen.frame.minX + 1105,
            top: screenTop - 40
        )

        NSApp.activate(ignoringOtherApps: true)
    }

    private func makeWindow(path: String, title: String, contentWidth: CGFloat,
                            contentHeight: CGFloat, x: CGFloat, top: CGFloat) {
        let style: NSWindow.StyleMask = [.titled, .closable, .miniaturizable]
        let contentRect = NSRect(x: 0, y: 0, width: contentWidth, height: contentHeight)
        let window = NSWindow(contentRect: contentRect, styleMask: style,
                              backing: .buffered, defer: false)
        window.title = title
        window.isReleasedWhenClosed = false
        window.isRestorable = false
        window.delegate = self
        window.setFrameTopLeftPoint(NSPoint(x: x, y: top))

        let configuration = WKWebViewConfiguration()
        configuration.mediaTypesRequiringUserActionForPlayback = []
        let webView = WKWebView(frame: contentRect, configuration: configuration)
        webView.autoresizingMask = [.width, .height]
        window.contentView = webView
        windows.append(window)

        window.makeKeyAndOrderFront(nil)
        webView.load(URLRequest(url: baseURL.appendingPathComponent(path == "/" ? "" : String(path.dropFirst()))))
    }

    func windowWillClose(_ notification: Notification) {
        DispatchQueue.main.async { [weak self] in
            guard let self, self.windows.allSatisfy({ !$0.isVisible }) else { return }
            NSApp.terminate(nil)
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }
}

let base = CommandLine.arguments.dropFirst().first ?? "http://127.0.0.1:8080"
let application = NSApplication.shared
application.setActivationPolicy(.regular)
let viewer = TerminalVectorViewer(baseURL: URL(string: base)!)
application.delegate = viewer
application.run()
