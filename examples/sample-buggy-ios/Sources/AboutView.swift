import SwiftUI

/// Screen 3 — About. Static info plus a "Clear wishlist" that works CORRECTLY (clears
/// state and returns to the Wishlist root). It is a deliberate non-bug: a correctly-
/// behaving destructive control raises the precision bar — an agent that flags it is wrong.
struct AboutView: View {
    @EnvironmentObject var app: AppState
    @Binding var path: [Route]

    var body: some View {
        Form {
            Section("App") {
                Text("Wishlist").font(.headline)
                Text("A deterministic, multi-screen UI-testing fixture.")
                    .foregroundStyle(.secondary)
                LabeledContent("Version", value: "2.0.0")
                    .accessibilityIdentifier("about.version")
            }

            Section {
                Button("Clear wishlist", role: .destructive, action: clearAll)
                    .accessibilityIdentifier("about.reset.button")
            }
        }
        .navigationTitle("About")
    }

    private func clearAll() {
        app.newItemName = ""
        app.savedItemName = ""
        app.savedItemPrice = ""
        app.items.removeAll()
        path.removeAll()        // correctly returns to the Wishlist root
    }
}
