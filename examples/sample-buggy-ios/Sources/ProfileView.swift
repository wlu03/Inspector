import SwiftUI

/// Screen 2 — Profile. Three subtle, log-free defects:
///   BUG-01 state-sync: the editable fields are fresh @State that is NEVER seeded
///          back from the model (.onAppear read-back missing), so a committed name
///          is lost on re-entry — while the model-backed "Saved profile" row still
///          shows it. Two nodes in the same tree contradict each other.
///   BUG-04 display-format: "Profile completeness" uses Int division, so 2-of-3
///          fields truncates 66.67% to "66%" instead of rounding to "67%".
///   BUG-05 navigation-focus: Continue pushes a DUPLICATE Profile before About, so
///          backing out of About lands on a blank Profile and two Backs never reach
///          the Settings root (the stack is one screen too deep).
struct ProfileView: View {
    @EnvironmentObject var app: AppState
    @Binding var path: [Route]

    // BUG-01: fresh, view-local state — never seeded from app.profileDisplayName.
    @State private var displayName = ""
    @State private var email = ""
    @State private var phone = ""
    @State private var didContinue = false

    var body: some View {
        Form {
            Section("Saved profile") {
                // Unconditional, model-backed: a committed name shows here even when
                // the editable field above has reverted to empty (the contradiction).
                Text(app.profileDisplayName.isEmpty ? "—" : app.profileDisplayName)
                    .accessibilityIdentifier("profile.savedName")
            }

            Section("Profile") {
                TextField("Display name", text: $displayName)
                    .accessibilityIdentifier("profile.displayName.field")
                TextField("Email", text: $email)
                    .accessibilityIdentifier("profile.email.field")
                TextField("Phone", text: $phone)
                    .accessibilityIdentifier("profile.phone.field")

                // BUG-04: Int division truncates instead of rounding.
                Text("Profile completeness \(completenessPercent)%")
                    .accessibilityIdentifier("profile.completeness")

                Button("Continue", action: submit)
                    .accessibilityIdentifier("profile.continue.button")
            }

            if didContinue {
                Section("Result") {
                    Text("Continued as \(displayName.isEmpty ? "(empty)" : displayName)")
                        .accessibilityIdentifier("profile.result")
                }
            }
        }
        .navigationTitle("Profile")
        // BUG-01: NO .onAppear { displayName = app.profileDisplayName; email = app.profileEmail }
        // — the model is written on Continue but never read back into the fields.
    }

    private var completenessPercent: Int {
        let filled = [displayName, email, phone]
            .filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
            .count
        return filled * 100 / 3        // BUG-04: 2/3 -> 66, not round(66.67) == 67
    }

    private func submit() {
        app.profileDisplayName = displayName
        app.profileEmail = email
        didContinue = true
        // BUG-05: should be just `path.append(.about)`. The stray duplicate Profile
        // makes the stack one screen too deep, so Back never returns to the root.
        path.append(.profile)
        path.append(.about)
    }
}
