// Explicit, one-shot keyboard commands addressed only to the running WeChat PID.
// Does not activate apps or install a service. UI identity must be verified by
// screenshot before typing or sending; this helper does not choose recipients.
import AppKit
import ApplicationServices
import Foundation
import Darwin

func report(_ object: [String: Any]) {
    let data = try! JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
    print(String(data: data, encoding: .utf8)!)
}

let args = Array(CommandLine.arguments.dropFirst())
let command = args.first ?? "status"
let apps = NSRunningApplication.runningApplications(withBundleIdentifier: "com.tencent.xinWeChat")
let trusted = AXIsProcessTrusted()
if command == "status" {
    report(["accessibilityGranted": trusted, "helperBundleId": Bundle.main.bundleIdentifier ?? "unknown",
            "wechatPid": apps.first?.processIdentifier ?? 0,
            "wechatInstances": apps.count, "wechatActive": apps.first?.isActive ?? false])
    exit(0)
}
if command == "request-permission" {
    let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
    report(["accessibilityGranted": AXIsProcessTrustedWithOptions(options)])
    exit(0)
}
guard trusted else { report(["error": "Accessibility permission required; no input sent"]); exit(2) }
guard apps.count == 1, let app = apps.first else {
    report(["error": "Expected exactly one running WeChat app; no input sent"]); exit(3)
}
func requireFrontmost() {
    guard NSWorkspace.shared.frontmostApplication?.processIdentifier == app.processIdentifier else {
        report(["error": "wechat_not_frontmost", "note": "No further input sent; verify any partial draft before retrying"])
        exit(7)
    }
}
requireFrontmost()
guard let source = CGEventSource(stateID: .privateState) else { exit(4) }
func key(_ code: CGKeyCode, flags: CGEventFlags = []) {
    let down = CGEvent(keyboardEventSource: source, virtualKey: code, keyDown: true)!
    let up = CGEvent(keyboardEventSource: source, virtualKey: code, keyDown: false)!
    down.flags = flags; up.flags = []
    down.postToPid(app.processIdentifier)
    usleep(30000)
    up.postToPid(app.processIdentifier)
}
switch command {
case "search": key(3, flags: .maskCommand)
case "select-all": key(0, flags: .maskCommand)
case "enter": key(36)
case "escape": key(53)
case "tab": key(48)
case "down": key(125)
case "up": key(126)
case "type":
    guard args.count == 2, let text = try? String(contentsOfFile: args[1], encoding: .utf8),
          text.count <= 200, !text.contains("\n"), !text.contains("\r") else {
        report(["error": "type requires a UTF-8 file containing at most 200 characters and no line breaks"]); exit(5)
    }
    for character in text {
        requireFrontmost()
        let units = Array(String(character).utf16)
        let down = CGEvent(keyboardEventSource: source, virtualKey: 0, keyDown: true)!
        let up = CGEvent(keyboardEventSource: source, virtualKey: 0, keyDown: false)!
        units.withUnsafeBufferPointer { buffer in
            down.keyboardSetUnicodeString(stringLength: buffer.count, unicodeString: buffer.baseAddress!)
            up.keyboardSetUnicodeString(stringLength: buffer.count, unicodeString: buffer.baseAddress!)
        }
        down.postToPid(app.processIdentifier); up.postToPid(app.processIdentifier)
        usleep(40000)
    }
default: report(["error": "Unknown command; no input sent"]); exit(6)
}
report(["event": "keyboard_command_posted", "command": command, "pid": app.processIdentifier,
        "note": "Posting is not proof of delivery; verify resulting screenshot."])
