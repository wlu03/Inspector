import SwiftUI

/// Screen 1 — Settings. Hosts the original Save crash (BUG-01), the desynced
/// Notifications toggle (BUG-02), the a11y locator trap on Save (BUG-06), and
/// a fully-working Theme picker for contrast.
struct SettingsView: View {
    @EnvironmentObject var app: AppState

    @State private var savedConfirmation = ""        // stays empty: BUG-01 crashes first
    @State private var notificationsLabelOn = false  // BUG-02: label-only flag

    var body: some View {
        Form {
            Section("Your name") {
                TextField("Your name", text: $app.settingsName)
                    .accessibilityIdentifier("settings.name.field")

                HStack {
                    // Real, functional Save button — but BUG-06 ships it with NO
                    // accessible name and NO test id.
                    Button(action: save) {
                        Label("Save", systemImage: "square.and.arrow.down")
                    }
                    .buttonStyle(.borderless)
                    .accessibilityLabel(Text(""))     // primary action has no a11y name
                    // (intentionally no .accessibilityIdentifier)

                    Spacer()

                    // Decorative badge that wrongly owns the obvious "Save" locator,
                    // so naive label/id lookups tap this dead element instead.
                    Image(systemName: "checkmark.seal")
                        .foregroundStyle(.secondary)
                        .accessibilityIdentifier("save")
                        .accessibilityLabel("Save")
                        .accessibilityAddTraits(.isButton)
                }

                Text(savedConfirmation)
                    .foregroundColor(.green)
                    .accessibilityIdentifier("settings.savedConfirmation")
            }

            Section("Preferences") {
                // BUG-02: the toggle flips its own visual label but never writes
                // through to app.notificationsEnabled — underlying state desyncs.
                Toggle(isOn: Binding(
                    get: { notificationsLabelOn },
                    set: { _ in
                        NSLog("toggle state desync")
                        notificationsLabelOn.toggle()
                        // app.notificationsEnabled is intentionally left unchanged.
                    }
                )) {
                    Text("Notifications \(notificationsLabelOn ? "On" : "Off")")
                }
                .accessibilityIdentifier("settings.notifications.toggle")

                Picker("Theme", selection: $app.theme) {
                    ForEach(AppTheme.allCases) { Text($0.rawValue).tag($0) }
                }
                .accessibilityIdentifier("settings.theme.picker")
            }

            Section {
                NavigationLink("Profile", value: Route.profile)
                NavigationLink("About", value: Route.about)
            }
        }
        .navigationTitle("Settings")
        .onAppear {
            // BUG-06: the primary action (Save) renders without an accessible label.
            NSLog("missing a11y label on primary action")
        }
    }

    private func save() {
        // BUG-01: log, then crash before the confirmation is ever shown.
        NSLog("query not invalidated after save")
        let items: [String] = []
        _ = items[5]                  // Fatal error: Index out of range
        savedConfirmation = "Saved"   // unreachable
    }
}
