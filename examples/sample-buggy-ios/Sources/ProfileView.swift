import SwiftUI

/// Screen 2 — Profile. Hosts the validation bypass (BUG-03) and the broken
/// cross-screen summary that should mirror the Settings name (BUG-04).
struct ProfileView: View {
    @EnvironmentObject var app: AppState

    @State private var displayName = ""
    @State private var email = ""
    @State private var didContinue = false
    @State private var validationError = ""

    // BUG-04: this is meant to mirror app.settingsName, but it is a private
    // snapshot that is never assigned, so the summary is always blank/stale.
    @State private var summaryName = ""

    var body: some View {
        Form {
            Section("Saved from Settings") {
                Text(summaryName.isEmpty ? "—" : summaryName)
                    .accessibilityIdentifier("profile.summary")
            }

            Section("Profile") {
                TextField("Display name", text: $displayName)
                    .accessibilityIdentifier("profile.displayName.field")

                TextField("Email", text: $email)
                    .accessibilityIdentifier("profile.email.field")

                Button("Continue", action: submit)
                    .accessibilityIdentifier("profile.continue.button")
            }

            if !validationError.isEmpty {
                Section("Error") {
                    Text(validationError)
                        .foregroundColor(.red)
                        .accessibilityIdentifier("profile.validationError")
                }
            }

            if didContinue {
                Section("Result") {
                    Text("Continued as \(displayName.isEmpty ? "(empty)" : displayName)")
                        .accessibilityIdentifier("profile.result")
                }
            }
        }
        .navigationTitle("Profile")
        .onAppear {
            // BUG-04: the Settings name never makes it across to this screen.
            NSLog("state not propagated across screens")
        }
    }

    private func submit() {
        let isValid = !displayName.isEmpty && email.contains("@")
        if !isValid {
            var errors: [String] = []
            if displayName.isEmpty { errors.append("Display name is required.") }
            if !email.contains("@") { errors.append("Email must contain '@'.") }
            validationError = errors.joined(separator: " ")
            return
        }
        validationError = ""
        app.profileDisplayName = displayName
        app.profileEmail = email
        didContinue = true
    }
}
