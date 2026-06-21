import SwiftUI

/// A small native macOS (AppKit/SwiftUI) window with three AX-observable bugs.
/// The agent grounds via the macOS accessibility tree (macax dump) and CGEvent taps.
struct ContentView: View {
    @State private var count = 0
    @State private var name = ""
    @State private var saved = ""

    var body: some View {
        VStack(spacing: 16) {
            Text("Sample Buggy Mac").font(.title2)
            Text("Count: \(count)").font(.largeTitle)

            HStack(spacing: 12) {
                Button("Minus") { count -= 1 }
                Button("Plus") { count += 2 }    // BUG-01: increments by 2, not 1
                Button("Reset") { count = 1 }    // BUG-02: resets to 1, not 0
            }

            Divider().frame(width: 260)

            TextField("Your name", text: $name).frame(width: 220)
            // BUG-03: Save reports success but CLEARS the just-entered name.
            Button("Save") { saved = "Saved"; name = "" }
            Text(saved).foregroundColor(.green)
        }
        .padding(40)
        .frame(width: 360, height: 340)
    }
}
