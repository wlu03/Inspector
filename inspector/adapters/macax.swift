// macax — a tiny Accessibility + CGEvent helper for the macOS-native adapter.
// The Mac analog of `idb`: dump the a11y tree of an app's front window as JSON
// (screen points, top-left origin) and post synthetic taps/keystrokes via CGEvent.
//
// Build:  swiftc -O macax.swift -o macax -framework Cocoa -framework ApplicationServices
// Usage:  macax dump <appName|pid> | tap <x> <y> | type <text> | key <keycode>
//
// Requires the controlling process to hold Accessibility permission (read AX +
// post events) and Screen Recording (for the separate screencapture call).

import AppKit
import ApplicationServices
import CoreGraphics
import Foundation

func pidFor(_ ident: String) -> pid_t? {
    if let p = Int32(ident) { return p }  // numeric pid
    for app in NSWorkspace.shared.runningApplications {
        if app.localizedName == ident || app.bundleIdentifier == ident { return app.processIdentifier }
    }
    return nil
}

func axStr(_ el: AXUIElement, _ attr: String) -> String {
    var v: CFTypeRef?
    if AXUIElementCopyAttributeValue(el, attr as CFString, &v) == .success {
        if let s = v as? String { return s }
        if let n = v as? NSNumber { return n.stringValue }
    }
    return ""
}

func axFrame(_ el: AXUIElement) -> (CGPoint, CGSize)? {
    var pv: CFTypeRef?
    var sv: CFTypeRef?
    guard AXUIElementCopyAttributeValue(el, kAXPositionAttribute as CFString, &pv) == .success,
          AXUIElementCopyAttributeValue(el, kAXSizeAttribute as CFString, &sv) == .success
    else { return nil }
    var pos = CGPoint.zero
    var size = CGSize.zero
    AXValueGetValue(pv as! AXValue, .cgPoint, &pos)
    AXValueGetValue(sv as! AXValue, .cgSize, &size)
    return (pos, size)
}

func axChildren(_ el: AXUIElement) -> [AXUIElement] {
    var v: CFTypeRef?
    if AXUIElementCopyAttributeValue(el, kAXChildrenAttribute as CFString, &v) == .success,
       let arr = v as? [AXUIElement] { return arr }
    return []
}

func walk(_ el: AXUIElement, _ depth: Int, _ out: inout [[String: Any]]) {
    if out.count >= 500 || depth > 40 { return }
    let role = axStr(el, kAXRoleAttribute as String)
    var label = axStr(el, kAXTitleAttribute as String)
    if label.isEmpty { label = axStr(el, kAXDescriptionAttribute as String) }
    let value = axStr(el, kAXValueAttribute as String)
    if let (p, s) = axFrame(el), s.width > 0, s.height > 0 {
        out.append(["role": role, "label": label, "value": value,
                    "x": Double(p.x), "y": Double(p.y), "w": Double(s.width), "h": Double(s.height)])
    }
    for c in axChildren(el) { walk(c, depth + 1, &out) }
}

func dump(_ ident: String) {
    guard let pid = pidFor(ident) else { print("{}"); return }
    let app = AXUIElementCreateApplication(pid)
    var window: [String: Any] = [:]
    var elements: [[String: Any]] = []
    var wv: CFTypeRef?
    if AXUIElementCopyAttributeValue(app, kAXWindowsAttribute as CFString, &wv) == .success,
       let wins = wv as? [AXUIElement], let w0 = wins.first {
        if let (p, s) = axFrame(w0) {
            window = ["x": Double(p.x), "y": Double(p.y), "w": Double(s.width), "h": Double(s.height)]
        }
        walk(w0, 0, &elements)
    }
    let obj: [String: Any] = ["pid": Int(pid), "window": window, "elements": elements]
    if let data = try? JSONSerialization.data(withJSONObject: obj),
       let str = String(data: data, encoding: .utf8) { print(str) } else { print("{}") }
}

let src = CGEventSource(stateID: .hidSystemState)

func tap(_ x: Double, _ y: Double) {
    let p = CGPoint(x: x, y: y)
    CGEvent(mouseEventSource: src, mouseType: .mouseMoved, mouseCursorPosition: p, mouseButton: .left)?.post(tap: .cghidEventTap)
    CGEvent(mouseEventSource: src, mouseType: .leftMouseDown, mouseCursorPosition: p, mouseButton: .left)?.post(tap: .cghidEventTap)
    usleep(40_000)
    CGEvent(mouseEventSource: src, mouseType: .leftMouseUp, mouseCursorPosition: p, mouseButton: .left)?.post(tap: .cghidEventTap)
}

func typeText(_ s: String) {
    for ch in s.utf16 {
        var u = ch
        let down = CGEvent(keyboardEventSource: src, virtualKey: 0, keyDown: true)
        down?.keyboardSetUnicodeString(stringLength: 1, unicodeString: &u)
        down?.post(tap: .cghidEventTap)
        let up = CGEvent(keyboardEventSource: src, virtualKey: 0, keyDown: false)
        up?.keyboardSetUnicodeString(stringLength: 1, unicodeString: &u)
        up?.post(tap: .cghidEventTap)
        usleep(8_000)
    }
}

func key(_ code: UInt16) {
    CGEvent(keyboardEventSource: src, virtualKey: code, keyDown: true)?.post(tap: .cghidEventTap)
    CGEvent(keyboardEventSource: src, virtualKey: code, keyDown: false)?.post(tap: .cghidEventTap)
}

let a = CommandLine.arguments
switch a.count > 1 ? a[1] : "" {
case "dump" where a.count > 2: dump(a[2])
case "tap" where a.count > 3:  tap(Double(a[2]) ?? 0, Double(a[3]) ?? 0)
case "type" where a.count > 2: typeText(a[2])
case "key" where a.count > 2:  key(UInt16(a[2]) ?? 0)
default:
    FileHandle.standardError.write("usage: macax dump <app|pid> | tap <x> <y> | type <text> | key <code>\n".data(using: .utf8)!)
    exit(1)
}
