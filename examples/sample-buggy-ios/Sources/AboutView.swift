import SwiftUI

/// Screen 3 — About. Static info plus a "Reset all" that now works CORRECTLY
/// (clears state and returns to the Settings root). It is a deliberate non-bug:
/// a correctly-behaving destructive control raises the precision bar — an agent
/// that flags it is wrong.
struct AboutView: View {
    @EnvironmentObject var app: AppState
    @Binding var path: [Route]

    var body: some View {
        Form {
            Section("App") {
                Text("Sample Buggy App").font(.headline)
                Text("A deterministic, multi-screen UI-testing fixture.")
                    .foregroundStyle(.secondary)
                LabeledContent("Version", value: "1.0.0")
                    .accessibilityIdentifier("about.version")
            }

            Section {
                Button("Reset all", role: .destructive, action: resetAll)
                    .accessibilityIdentifier("about.reset.button")
            }
        }
        .navigationTitle("About")
    }

    private func resetAll() {
        app.settingsName = ""
        app.profileDisplayName = ""
        app.profileEmail = ""
        path.removeAll()        // correctly returns to the Settings root
    }
}
