import SwiftUI

/// Screen 1 — Settings. Three subtle, log-free defects:
///   BUG-02 input-edge: Save Int-normalizes the name, silently dropping leading
///          zeros ("007" -> "7") while the green "Saved" still claims success.
///   BUG-03 display-format: the character counter is off-by-one (boundary-safe, so
///          the empty field reads a correct-looking "0/30" with no first-paint tell).
///   BUG-06 control-mismatch: the segmented Theme picker's onChange applies the
///          PREVIOUS selection, so the highlighted segment and the "Current theme:"
///          caption disagree by one tap.
struct SettingsView: View {
    @EnvironmentObject var app: AppState

    @State private var savedConfirmation = ""
    @State private var themeSelection: AppTheme = .system

    var body: some View {
        Form {
            Section("Your name") {
                TextField("Your name", text: $app.settingsName)
                    .accessibilityIdentifier("settings.name.field")

                // BUG-03: off-by-one, but max(0,…) keeps the empty case at "0/30"
                // so there is no first-paint giveaway — only typing exposes it.
                Text("\(max(0, app.settingsName.count - 1))/30")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .accessibilityIdentifier("settings.name.counter")

                Button("Save", action: save)
                    .accessibilityIdentifier("settings.save.button")

                Text(savedConfirmation)
                    .foregroundColor(.green)
                    .accessibilityIdentifier("settings.savedConfirmation")
            }

            Section("Appearance") {
                Picker("Theme", selection: $themeSelection) {
                    ForEach(AppTheme.allCases) { Text($0.rawValue).tag($0) }
                }
                .pickerStyle(.segmented)
                .accessibilityIdentifier("settings.theme.picker")
                .onChange(of: themeSelection) { oldValue, _ in
                    // BUG-06: applies the PREVIOUS selection (oldValue) instead of the
                    // new one — the textbook onChange(old,new) swap.
                    app.theme = oldValue
                }

                Text("Current theme: \(app.theme.rawValue)")
                    .accessibilityIdentifier("settings.theme.current")
            }

            Section {
                NavigationLink("Profile", value: Route.profile)
                NavigationLink("About", value: Route.about)
            }
        }
        .navigationTitle("Settings")
    }

    private func save() {
        // BUG-02: "normalize" the name as if it were a numeric id — drops leading
        // zeros. The field is bound to $app.settingsName, so the mutated value
        // re-renders straight back into the field while "Saved" still appears.
        if let n = Int(app.settingsName) {
            app.settingsName = String(n)        // "007" -> "7"
        }
        savedConfirmation = "Saved"             // honeypot: always claims success
    }
}
