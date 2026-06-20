import SwiftUI

/// Screen 3 — About. Static info plus the "Reset all" navigation defect (BUG-05).
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
        // BUG-05: should clear all state and return to Settings (the root).
        // Instead it clears nothing and pushes the wrong screen (Profile).
        NSLog("reset no-op, wrong route")
        path.append(.profile)
    }
}
