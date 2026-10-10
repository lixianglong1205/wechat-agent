// Local, read-only capture experiment. No keyboard/mouse events, no activation,
// no permission changes, no network requests, and no WeChat process changes.
import Foundation
import ScreenCaptureKit
import CoreMedia
import CoreImage
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers
import Darwin

final class Frames: NSObject, SCStreamOutput, SCStreamDelegate, @unchecked Sendable {
    private let lock = NSLock()
    private var image: CGImage?
    private var capturedAt = Date.distantPast
    private var counts: [Int: Int] = [:]
    private let context = CIContext()

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
                of type: SCStreamOutputType) {
        guard type == .screen, sampleBuffer.isValid,
              let attachments = CMSampleBufferGetSampleAttachmentsArray(sampleBuffer, createIfNecessary: false) as? [[SCStreamFrameInfo: Any]],
              let raw = attachments.first?[.status] as? Int else { return }
        lock.lock(); counts[raw, default: 0] += 1; lock.unlock()
        guard raw == SCFrameStatus.complete.rawValue,
              let buffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        let ci = CIImage(cvPixelBuffer: buffer)
        guard let rendered = context.createCGImage(ci, from: ci.extent) else { return }
        lock.lock(); image = rendered; capturedAt = Date(); lock.unlock()
    }

    func latest(after time: Date) -> CGImage? {
        lock.lock(); defer { lock.unlock() }
        return capturedAt >= time ? image : nil
    }

    func statistics() -> [String: Int] {
        lock.lock(); defer { lock.unlock() }
        return Dictionary(uniqueKeysWithValues: counts.map { (String($0.key), $0.value) })
    }
}

func emit(_ fields: [String: Any]) {
    if let data = try? JSONSerialization.data(withJSONObject: fields, options: [.sortedKeys]),
       let text = String(data: data, encoding: .utf8) { print(text) }
    fflush(stdout)
}

func save(_ image: CGImage, to url: URL) throws {
    guard let destination = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil) else {
        throw NSError(domain: "CaptureProbe", code: 2, userInfo: [NSLocalizedDescriptionKey: "Cannot create PNG"])
    }
    CGImageDestinationAddImage(destination, image, nil)
    guard CGImageDestinationFinalize(destination) else {
        throw NSError(domain: "CaptureProbe", code: 3, userInfo: [NSLocalizedDescriptionKey: "PNG write failed"])
    }
    try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
    emit(["event": "image_saved", "path": url.path, "width": image.width, "height": image.height])
}

@main
struct Probe {
    static func main() async {
        umask(0o077)
        do { try await run() }
        catch { emit(["event": "error", "message": String(describing: error)]); exit(1) }
    }

    static func run() async throws {
        let argument = CommandLine.arguments.dropFirst().first
        if argument == "--status" {
            emit(["screenCaptureGranted": CGPreflightScreenCaptureAccess()])
            return
        }
        if argument == "--request-permission" {
            emit(["screenCaptureGranted": CGRequestScreenCaptureAccess()])
            return
        }
        guard let argument, !argument.hasPrefix("--") else {
            emit(["event": "error", "message": "Provide a private output directory, --status, or --request-permission"])
            exit(2)
        }
        let folder = URL(fileURLWithPath: argument, isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let permitted = CGPreflightScreenCaptureAccess()
        emit(["event": "screen_capture_permission", "granted": permitted])
        // No permission prompt or private TCC modifications.
        guard permitted else {
            emit(["event": "blocked", "reason": "Screen capture permission is not granted to this execution context; no capture attempted."])
            exit(2)
        }
        let content = try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: true)
        let windows = content.windows.filter {
            $0.owningApplication?.bundleIdentifier == "com.tencent.xinWeChat" &&
            $0.windowLayer == 0 && $0.frame.width > 280 && $0.frame.height > 180
        }.sorted { $0.frame.width * $0.frame.height > $1.frame.width * $1.frame.height }
        guard let window = windows.first, let app = window.owningApplication else {
            emit(["event": "blocked", "reason": "No visible WeChat main window. No app was activated."])
            exit(3)
        }
        let displays = content.displays.sorted {
            let a = $0.frame.intersection(window.frame), b = $1.frame.intersection(window.frame)
            return a.width * a.height > b.width * b.height
        }
        guard let display = displays.first, display.frame.intersects(window.frame) else {
            emit(["event": "blocked", "reason": "WeChat window does not intersect a display."])
            exit(3)
        }
        emit(["event": "target", "pid": app.processID, "windowId": window.windowID,
              "width": window.frame.width, "height": window.frame.height, "displayId": display.displayID])
        let scale = CGFloat(CGDisplayPixelsWide(display.displayID)) / display.frame.width
        let oneShot = SCStreamConfiguration()
        oneShot.width = Int(window.frame.width * scale)
        oneShot.height = Int(window.frame.height * scale)
        oneShot.showsCursor = false
        oneShot.ignoreShadowsSingleWindow = true
        do {
            let image = try await SCScreenshotManager.captureImage(
                contentFilter: SCContentFilter(desktopIndependentWindow: window), configuration: oneShot)
            try save(image, to: folder.appendingPathComponent("01-direct-window.png"))
        } catch { emit(["event": "direct_capture_failed", "message": String(describing: error)]) }

        let configuration = SCStreamConfiguration()
        configuration.width = oneShot.width
        configuration.height = oneShot.height
        configuration.sourceRect = window.frame.offsetBy(dx: -display.frame.minX, dy: -display.frame.minY)
        configuration.showsCursor = false
        configuration.capturesAudio = false
        configuration.pixelFormat = kCVPixelFormatType_32BGRA
        configuration.queueDepth = 5
        configuration.minimumFrameInterval = CMTime(value: 1, timescale: 10)
        let sink = Frames()
        let filter = SCContentFilter(display: display, including: [app], exceptingWindows: [])
        // Include app-owned search popovers, which a single-window capture omits.
        do {
            let image = try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: configuration)
            try save(image, to: folder.appendingPathComponent("03-app-windows.png"))
        } catch { emit(["event": "app_capture_failed", "message": String(describing: error)]) }
        let stream = SCStream(filter: filter, configuration: configuration, delegate: sink)
        try stream.addStreamOutput(sink, type: .screen, sampleHandlerQueue: DispatchQueue(label: "wechat.capture.probe"))
        try await stream.startCapture()
        do {
            try await Task.sleep(for: .milliseconds(250))
            let changedAt = Date()
            try await stream.updateContentFilter(SCContentFilter(display: display, including: [window]))
            emit(["event": "filter_updated", "mode": "application_to_window"])
            var captured: CGImage?
            for _ in 0..<40 {
                try await Task.sleep(for: .milliseconds(200))
                if let image = sink.latest(after: changedAt) { captured = image; break }
            }
            if let image = captured {
                try save(image, to: folder.appendingPathComponent("02-refreshed-stream.png"))
            } else { emit(["event": "no_complete_frame", "frameStatusCounts": sink.statistics()]) }
            try await stream.stopCapture()
            emit(["event": "finished", "frameStatusCounts": sink.statistics()])
            if captured == nil { exit(4) }
        } catch {
            try? await stream.stopCapture()
            throw error
        }
    }
}
