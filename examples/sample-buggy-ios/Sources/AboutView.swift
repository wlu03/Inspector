import SwiftUI

/// Screen 3 — About. Static info plus a "Reset all" button that clears state and pops to root.
struct AboutView: View {
    @EnvironmentObject var app: AppState
    @Binding var path: [Route]

    var body: some View {
        Form {
            Section("App") {
                Text("Sample Buggy App").font(.headline)
                Text("A deterministic, multi-screen UI-testing fixture.")
                    .foregroundStyle(.secondary)
                LabeledContent("Version", value: "1.0.0 (M0)")
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
        app.notificationsEnabled = false
        app.theme = .system
        app.profileDisplayName = ""
        app.profileEmail = ""
        path = []
    }
}
