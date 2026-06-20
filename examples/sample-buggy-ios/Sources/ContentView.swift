import SwiftUI

struct ContentView: View {
    @State private var name = ""
    @State private var toast = ""

    var body: some View {
        VStack(spacing: 16) {
            Text("Settings").font(.largeTitle).bold()
            TextField("Your name", text: $name)
                .textFieldStyle(.roundedBorder)
            Button("Save") {
                // Same bug as the other samples: Save should show a "Saved"
                // confirmation but crashes first (index out of range), so the
                // toast is never set. LoopBack catches the crash via the
                // simulator log / crash report and via verify-after-act.
                NSLog("query not invalidated after save")
                let items: [String] = []
                _ = items[5] // BUG: Fatal error: Index out of range
                toast = "Saved" // unreachable
            }
            Text(toast).foregroundColor(.green)
        }
        .padding()
    }
}

#Preview {
    ContentView()
}
